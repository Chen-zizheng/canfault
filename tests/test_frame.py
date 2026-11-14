# -*- coding: utf-8 -*-
import pytest

from canfault.frame import Frame, FrameError, pack_u16, set_nibble, unpack_u16


def test_frame_rejects_oversized_payload():
    with pytest.raises(FrameError):
        Frame(0x100, bytes(9))


def test_frame_rejects_bad_id():
    with pytest.raises(FrameError):
        Frame(0x800, bytes(8))
    with pytest.raises(FrameError):
        Frame(0x20000000, bytes(8), is_extended_id=True)


def test_dlc_matches_payload_length():
    assert Frame(0x100, bytes(8)).dlc == 8
    assert Frame(0x100, b"").dlc == 0


def test_pack_unpack_roundtrip():
    data = pack_u16(0x1234, offset=2)
    assert data[2:4] == b"\x12\x34"
    assert unpack_u16(data, offset=2) == 0x1234


def test_pack_u16_range_and_room():
    with pytest.raises(FrameError):
        pack_u16(0x10000)
    with pytest.raises(FrameError):
        pack_u16(1, offset=7)


def test_set_nibble_high_and_low():
    data = bytes([0x12, 0x34])
    assert set_nibble(data, 0, True, 0xF)[0] == 0xF2
    assert set_nibble(data, 0, False, 0xF)[0] == 0x1F
    with pytest.raises(FrameError):
        set_nibble(data, 5, True, 0x1)


def test_hex_format():
    assert Frame(0x1AB, bytes([1, 2])).hex() == "0x1AB [2] 01 02"
