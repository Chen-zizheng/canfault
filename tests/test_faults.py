# -*- coding: utf-8 -*-
import pytest

from canfault.ecu import nominal_frames
from canfault.faults import FAULT_KINDS, FaultPlan, fault_report, inject

SEEDS = list(nominal_frames())


def test_plan_rejects_unknown_kind():
    with pytest.raises(ValueError):
        FaultPlan(kind="bit_flip")


def test_plan_rejects_bad_rate():
    with pytest.raises(ValueError):
        FaultPlan(kind="drop", rate=1.5)


def test_drop_removes_frames():
    out = list(inject(SEEDS, FaultPlan("drop", rate=1.0)))
    assert out == []


def test_duplicate_doubles_frames():
    out = list(inject(SEEDS, FaultPlan("duplicate", rate=1.0)))
    assert len(out) == 2 * len(SEEDS)


def test_dlc_tamper_shortens_payload():
    out = list(inject(SEEDS, FaultPlan("dlc_tamper", rate=1.0)))
    assert all(f.dlc < 8 for f in out)


def test_out_of_range_sets_high_nibble():
    out = list(inject(SEEDS, FaultPlan("out_of_range", rate=1.0, seed=1)))
    assert any(b & 0xF0 == 0xF0 for f in out for b in f.data)


def test_bus_load_multiplies_frames():
    # 每条被判为「负载故障」的报文重发 8 次，用来把总线占用率拉高
    out = list(inject(SEEDS, FaultPlan("bus_load", rate=1.0)))
    assert len(out) == 8 * len(SEEDS)


def test_report_counts():
    row = fault_report(SEEDS, FaultPlan("drop", rate=0.5, seed=3))
    assert row["input"] == len(SEEDS)
    assert row["output"] < row["input"]
    assert row["delta"] == row["output"] - row["input"]


def test_all_kinds_have_a_plan():
    for kind in FAULT_KINDS:
        assert FaultPlan(kind).kind == kind
