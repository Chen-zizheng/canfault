# -*- coding: utf-8 -*-
import random

from canfault.ecu import EcuSim, nominal_frames
from canfault.fuzz import mutate, minimize, run_fuzz
from canfault.report import render_markdown

SEEDS = list(nominal_frames())


def test_mutate_stays_within_limits():
    rng = random.Random(1)
    for _ in range(200):
        frame = mutate(rng, SEEDS)
        assert frame.dlc <= 8
        assert frame.arbitration_id in {0x100, 0x200, 0x300, 0x400, 0x500, 0x600}


def test_fuzz_finds_crashes_on_virtual_bus(bus_pair):
    tx, rx = bus_pair
    ecu = EcuSim(rx).start()
    try:
        stats = run_fuzz(tx, ecu, SEEDS, seconds=1.5, seed=7)
    finally:
        ecu.stop()
    assert stats.sent > 100
    assert stats.unique, "模糊测试至少应找到一类崩溃"
    assert all(c.frame_id in {0x100, 0x200, 0x300, 0x400, 0x500, 0x600} for c in stats.unique)


def test_minimize_never_grows(bus_pair):
    tx, rx = bus_pair
    ecu = EcuSim(rx).start()
    try:
        stats = run_fuzz(tx, ecu, SEEDS, seconds=1.0, seed=3)
        crash = stats.unique[0]
        short = minimize(tx, ecu, crash, SEEDS)
    finally:
        ecu.stop()
    dlc = int(short.split("[")[1].split("]")[0])
    assert dlc <= len(bytes.fromhex(crash.data_hex))


def test_markdown_report_has_tables():
    md = render_markdown(
        {
            "interface": "virtual",
            "channel": "t",
            "fuzz": {
                "sent": 100,
                "duration_s": 1.0,
                "frames_per_s": 100.0,
                "crashes": 3,
                "unique_crashes": 1,
                "unique": [{"frame": "0x100 [2] 00 01", "message": "DLC mismatch", "signature": "s"}],
            },
        }
    )
    assert "| 发送帧数 | 100 |" in md
    assert "## 去重后的崩溃" in md
