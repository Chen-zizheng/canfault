# -*- coding: utf-8 -*-
"""6 类总线故障注入。

注入器是纯函数：输入一批「正常报文」，输出一批「被动手脚的报文」。
不碰总线，才能被单元测试直接断言，也才能在任何 interface 上复用。
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .frame import Frame, set_nibble

FAULT_KINDS = (
    "drop",
    "duplicate",
    "dlc_tamper",
    "out_of_range",
    "bus_load",
    "timing_drift",
)


@dataclass
class FaultPlan:
    kind: str
    rate: float = 0.05          # 触发比例，0~1
    seed: int = 20260101

    def __post_init__(self) -> None:
        if self.kind not in FAULT_KINDS:
            raise ValueError("unknown fault kind %r, choose from %s" % (self.kind, FAULT_KINDS))
        if not 0.0 <= self.rate <= 1.0:
            raise ValueError("rate must be within [0, 1], got %r" % self.rate)


def inject(frames, plan: FaultPlan):
    """按 plan 对 frames 逐帧注入，返回生成器；调用方决定写不写总线。"""
    rng = random.Random(plan.seed)
    for frame in frames:
        hit = rng.random() < plan.rate
        if not hit:
            yield frame
            continue
        if plan.kind == "drop":
            continue
        if plan.kind == "duplicate":
            yield frame
            yield frame
        elif plan.kind == "dlc_tamper":
            shorter = frame.data[: max(0, len(frame.data) - rng.choice((1, 2, 3)))]
            yield frame.with_data(shorter)
        elif plan.kind == "out_of_range":
            yield _out_of_range(frame, rng)
        elif plan.kind == "bus_load":
            # 用同一 ID 的高频重发把总线负载拉起来，测 DUT 的队列与丢帧行为
            for _ in range(8):
                yield frame
        elif plan.kind == "timing_drift":
            # 时序漂移不改内容，由 runner 按 delay 发送，这里只标记
            yield frame


def _out_of_range(frame: Frame, rng: random.Random) -> Frame:
    if not frame.data:
        return frame
    idx = rng.randrange(len(frame.data))
    if rng.random() < 0.5:
        return frame.with_data(set_nibble(frame.data, idx, True, 0xF))
    return frame.with_data(set_nibble(frame.data, idx, False, 0xF))


def fault_report(frames, plan: FaultPlan) -> dict:
    """跑一遍注入，返回「输入 / 输出 / 各类动作次数」，用于断言与报告。"""
    produced = dropped = duplicated = tampered = 0
    for frame in inject(frames, plan):
        produced += 1
        if frame.dlc != 8:
            tampered += 1
    # 再扫一遍原始输入，算丢弃与重复的净量
    src = list(frames)
    return {
        "kind": plan.kind,
        "rate": plan.rate,
        "input": len(src),
        "output": produced,
        "delta": produced - len(src),
        "dlc_modified": tampered,
    }
