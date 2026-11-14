# -*- coding: utf-8 -*-
"""被测对象（DUT）：一个按严格规则解析报文的 ECU 模拟器。

真实项目里 DUT 是黑盒，这里必须自己造一个，否则「发现崩溃」这句话没法验证。
解析器对收到的每一帧都做三件事：查 ID、查 DLC、查信号范围。
任何一条不满足就抛异常——异常就是一次崩溃，会被原样记录，供后续去重与最小化。
"""
from __future__ import annotations

import re
import threading
import time
import traceback
from dataclasses import dataclass, field

from .frame import Frame, FrameError, pack_u16, unpack_u16

# 报文 ID -> 信号规格（名称，最小值，最大值）
SIGNALS = {
    0x100: ("throttle", 0, 1000),
    0x200: ("brake", 0, 100),
    0x300: ("gear", 0, 5),
    0x400: ("speed", 0, 2500),
    0x500: ("coolant", -40, 150),
}

HEARTBEAT_ID = 0x600
EXPECTED_DLC = 8


@dataclass
class Crash:
    """一次崩溃：报文原文 + 异常 + 调用栈 + 时间。"""

    frame_hex: str
    frame_id: int
    data_hex: str
    exc_type: str
    message: str
    trace: str
    occurred_at: float

    @property
    def signature(self) -> str:
        """去重键：异常类型 + 帧 ID + 把数字抹平后的异常信息。

        抹平数字是故意的——「DLC 期望 8 实到 0」和「实到 1」是同一个缺陷的两副面孔，
        不去重就会把一条规则报成十几种崩溃。
        """
        return "%s@%s:%s" % (self.exc_type, hex(self.frame_id), re.sub(r"-?\d+", "#", self.message))

    def to_dict(self) -> dict:
        return {
            "frame": self.frame_hex,
            "id": hex(self.frame_id),
            "data": self.data_hex,
            "exc": self.exc_type,
            "message": self.message,
            "signature": self.signature,
        }


@dataclass
class EcuState:
    frames_seen: int = 0
    crashes: list = field(default_factory=list)
    _heartbeat_next: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, crash: Crash) -> None:
        with self._lock:
            self.crashes.append(crash)

    def unique_crashes(self) -> list:
        seen, out = set(), []
        for c in self.crashes:
            if c.signature not in seen:
                seen.add(c.signature)
                out.append(c)
        return out


class EcuSim:
    """在一条 can.Bus 上按严格规则解析报文。"""

    def __init__(self, bus):
        self.bus = bus
        self.state = EcuState()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="ecu-sim", daemon=True)

    def start(self) -> "EcuSim":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            msg = self.bus.recv(timeout=0.2)
            if msg is None:
                continue
            try:
                self.handle(msg)
            except Exception as exc:  # noqa: BLE001 - 这里就是要抓住 DUT 的一切崩溃
                self.state.record(
                    Crash(
                        frame_hex="0x%03X [%d] %s"
                        % (msg.arbitration_id, len(msg.data), bytes(msg.data).hex(" ").upper()),
                        frame_id=msg.arbitration_id,
                        data_hex=bytes(msg.data).hex(),
                        exc_type=type(exc).__name__,
                        message=str(exc),
                        trace=traceback.format_exc(),
                        occurred_at=time.time(),
                    )
                )

    # ---- 解析规则 ----
    def handle(self, msg) -> None:
        data = bytes(msg.data)
        self.state.frames_seen += 1
        if len(data) != EXPECTED_DLC:
            raise FrameError("DLC mismatch: expected %d, got %d" % (EXPECTED_DLC, len(data)))
        if msg.arbitration_id == HEARTBEAT_ID:
            self._check_heartbeat(data)
            return
        if msg.arbitration_id not in SIGNALS:
            raise FrameError("unknown arbitration id 0x%03X" % msg.arbitration_id)
        name, lo, hi = SIGNALS[msg.arbitration_id]
        raw = unpack_u16(data) if name != "gear" else (data[2] >> 4)
        if name == "coolant":
            raw = int.from_bytes(data[0:1], "big", signed=True)
        if not lo <= raw <= hi:
            raise FrameError("%s out of range: %d not in [%d, %d]" % (name, raw, lo, hi))

    def _check_heartbeat(self, data: bytes) -> None:
        counter = data[1]
        if counter != self.state._heartbeat_next:
            last, self.state._heartbeat_next = self.state._heartbeat_next, (counter + 1) & 0xFF
            raise FrameError("heartbeat gap: expected %d, got %d" % (last, counter))
        self.state._heartbeat_next = (counter + 1) & 0xFF


def nominal_frames():
    """一段「正常驾驶」报文序列，作为模糊测试的种子语料。"""
    for tick in range(64):
        yield Frame(0x100, (tick * 8 % 900).to_bytes(2, "big") + bytes(6))
        yield Frame(0x200, pack_u16(tick % 40) )
        yield Frame(0x300, bytes([0, 0, ((tick % 6) << 4)]) + bytes(5))
        yield Frame(0x400, (tick * 30 % 2400).to_bytes(2, "big") + bytes(6))
        yield Frame(0x500, bytes([(20 + tick % 60) & 0xFF]) + bytes(7))
        yield Frame(0x600, bytes([tick & 0xFF, tick & 0xFF]) + bytes(6))
