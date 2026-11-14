# -*- coding: utf-8 -*-
"""CAN 帧模型与信号编解码。

只做本项目需要的那一部分：8 字节数据段、按位打包的整型信号、DLC 校验。
不引 cantools，避免为了一个字段去解析 DBC 文件。
"""
from __future__ import annotations

from dataclasses import dataclass


class FrameError(ValueError):
    """帧本身不合法（长度、ID 范围）。"""


@dataclass(frozen=True)
class Frame:
    arbitration_id: int
    data: bytes
    is_extended_id: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.arbitration_id <= (0x1FFFFFFF if self.is_extended_id else 0x7FF):
            raise FrameError("arbitration_id out of range: 0x%X" % self.arbitration_id)
        if len(self.data) > 8:
            raise FrameError("classic CAN payload must be <= 8 bytes, got %d" % len(self.data))

    @property
    def dlc(self) -> int:
        return len(self.data)

    def to_can(self):
        import can

        return can.Message(
            arbitration_id=self.arbitration_id, data=self.data, is_extended_id=self.is_extended_id
        )

    @classmethod
    def from_can(cls, msg) -> "Frame":
        return cls(msg.arbitration_id, bytes(msg.data), bool(msg.is_extended_id))

    def with_data(self, data: bytes) -> "Frame":
        return Frame(self.arbitration_id, data, self.is_extended_id)

    def hex(self) -> str:
        return "0x%03X [%d] %s" % (self.arbitration_id, self.dlc, self.data.hex(" ").upper())


def pack_u16(value: int, offset: int = 0) -> bytes:
    """把 16 位无符号整数按大端写进 8 字节数据段。"""
    if not 0 <= value <= 0xFFFF:
        raise FrameError("u16 out of range: %d" % value)
    if offset + 2 > 8:
        raise FrameError("offset %d leaves no room for u16" % offset)
    buf = bytearray(8)
    buf[offset] = (value >> 8) & 0xFF
    buf[offset + 1] = value & 0xFF
    return bytes(buf)


def unpack_u16(data: bytes, offset: int = 0) -> int:
    if len(data) < offset + 2:
        raise FrameError("payload too short for u16 at offset %d" % offset)
    return (data[offset] << 8) | data[offset + 1]


def set_nibble(data: bytes, index: int, high: bool, value: int) -> bytes:
    """改写某个字节的高/低 4 位，用来做「信号值越界」这类注入。"""
    if not 0 <= index < len(data):
        raise FrameError("byte index %d out of range" % index)
    if not 0 <= value <= 0xF:
        raise FrameError("nibble value out of range: %d" % value)
    buf = bytearray(data)
    if high:
        buf[index] = (buf[index] & 0x0F) | (value << 4)
    else:
        buf[index] = (buf[index] & 0xF0) | value
    return bytes(buf)
