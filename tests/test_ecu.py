# -*- coding: utf-8 -*-
import pytest

from canfault.ecu import EcuSim, FrameError, nominal_frames


class _Msg:
    def __init__(self, arbitration_id, data):
        self.arbitration_id = arbitration_id
        self.data = data
        self.is_extended_id = False


def _ecu():
    return EcuSim(bus=None)


def test_nominal_traffic_does_not_crash():
    ecu = _ecu()
    for frame in nominal_frames():
        ecu.handle(_Msg(frame.arbitration_id, frame.data))
    assert ecu.state.crashes == []
    assert ecu.state.frames_seen == len(list(nominal_frames()))


def test_dlc_mismatch_is_a_crash():
    ecu = _ecu()
    with pytest.raises(FrameError):
        ecu.handle(_Msg(0x100, b"\x00\x01"))


def test_unknown_id_is_a_crash():
    with pytest.raises(FrameError):
        _ecu().handle(_Msg(0x7AB, bytes(8)))


def test_signal_out_of_range_is_a_crash():
    with pytest.raises(FrameError) as info:
        _ecu().handle(_Msg(0x100, b"\xFF\xFF" + bytes(6)))
    assert "throttle out of range" in str(info.value)


def test_gear_nibble_out_of_range():
    with pytest.raises(FrameError):
        _ecu().handle(_Msg(0x300, bytes([0, 0, 0xF0]) + bytes(5)))


def test_heartbeat_gap_is_a_crash():
    ecu = _ecu()
    ecu.handle(_Msg(0x600, bytes([0, 0]) + bytes(6)))
    with pytest.raises(FrameError) as info:
        ecu.handle(_Msg(0x600, bytes([0, 5]) + bytes(6)))
    assert "heartbeat gap" in str(info.value)
