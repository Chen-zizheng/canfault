# -*- coding: utf-8 -*-
"""报文模糊测试：种子变异、崩溃去重、崩溃最小化。

策略上是「结构化 + 无脑变异」两条腿：
- 结构化：已知报文 ID 的边界值（DLC 0/1/2/7/8、信号上下沿、计数器跳变）；
- 无脑变异：按位翻转、按字节置随机、跨帧拼接。
崩溃去重按「异常类型 + 帧 ID + 栈位置」算签名，最小化用逐字节回退（delta debugging 的简化版）。
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

from .ecu import EcuSim
from .frame import Frame

BOUNDARY_DLCS = (0, 1, 2, 7, 8)


@dataclass
class FuzzStats:
    sent: int = 0
    duration_s: float = 0.0
    crashes: list = field(default_factory=list)

    @property
    def unique(self) -> list:
        seen, out = set(), []
        for c in self.crashes:
            if c.signature not in seen:
                seen.add(c.signature)
                out.append(c)
        return out

    @property
    def rate(self) -> float:
        return self.sent / self.duration_s if self.duration_s else 0.0

    def to_dict(self) -> dict:
        return {
            "sent": self.sent,
            "duration_s": round(self.duration_s, 3),
            "frames_per_s": round(self.rate, 1),
            "crashes": len(self.crashes),
            "unique_crashes": len(self.unique),
            "unique": [c.to_dict() for c in self.unique],
        }


def mutate(rng: random.Random, seeds: list, structural_bias: float = 0.3) -> Frame:
    base = rng.choice(seeds)
    data = bytearray(base.data)
    if rng.random() < structural_bias:
        target_len = rng.choice(BOUNDARY_DLCS)
        data = data[:target_len]
        if rng.random() < 0.5 and data:
            data[-1] = rng.choice((0x00, 0xFF, 0x7F, 0x80))
        return base.with_data(bytes(data))
    action = rng.randrange(4)
    if action == 0 and data:
        idx = rng.randrange(len(data))
        data[idx] ^= 1 << rng.randrange(8)
    elif action == 1 and data:
        data[rng.randrange(len(data))] = rng.randrange(256)
    elif action == 2:
        other = rng.choice(seeds)
        cut = rng.randrange(1, 5)
        data = bytearray(bytes(data)[:cut] + bytes(other.data)[cut:])
        data = data[:8]
    else:
        data = bytearray(rng.randrange(256) for _ in range(rng.choice(BOUNDARY_DLCS)))
    return base.with_data(bytes(data))


def run_fuzz(bus, ecu: EcuSim, seeds: list, seconds: float = 10.0, seed: int = 7) -> FuzzStats:
    """在真实总线上跑模糊测试，返回统计。"""
    rng = random.Random(seed)
    stats = FuzzStats()
    start = time.time()
    deadline = start + seconds
    while time.time() < deadline:
        frame = mutate(rng, seeds)
        try:
            bus.send(frame.to_can())
        except Exception:  # 发送失败（如总线已满）也算一次有效尝试，不计崩溃
            pass
        stats.sent += 1
        time.sleep(0.0002)
    stats.duration_s = time.time() - start
    time.sleep(0.2)  # 留给 ECU 线程消费最后一批
    stats.crashes = list(ecu.state.crashes)
    return stats


def minimize(bus, ecu: EcuSim, crash, seeds: list, rounds: int = 8) -> str:
    """把触发崩溃的报文缩到最短：从后往前逐字节删，仍然崩溃就留下删短的那版。

    DUT 是黑盒，只能靠重放判定；所以这里直接复用同一个 ECU 实例，
    用「清空历史 → 重放 → 看是否新增同签名崩溃」的方式判断。
    """
    target = crash.signature
    best = bytes.fromhex(crash.data_hex) if crash.data_hex else b""
    frame_id = crash.frame_id
    if not best:
        return "%s [0] （已经是最小：0 字节数据段）" % hex(frame_id)
    original = best
    for _ in range(rounds):
        improved = False
        for cut in range(len(best) - 1, -1, -1):
            candidate = best[:cut] + best[cut + 1 :]
            if _still_crashes(bus, ecu, Frame(frame_id, candidate), target):
                best = candidate
                improved = True
                break
        if not improved:
            break
    if best == original:
        return "%s [%d] %s（已最短）" % (hex(frame_id), len(best), best.hex())
    return "%s [%d] %s" % (hex(frame_id), len(best), best.hex())


def _still_crashes(bus, ecu: EcuSim, frame: Frame, signature: str) -> bool:
    before = len(ecu.state.crashes)
    try:
        bus.send(frame.to_can())
    except Exception:
        return False
    time.sleep(0.05)
    return any(c.signature == signature for c in ecu.state.crashes[before:])
