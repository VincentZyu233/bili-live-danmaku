from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ProtoField:
    number: int
    wire_type: int
    value: int | bytes


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data) and shift < 70:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
    raise ValueError("invalid protobuf varint")


class ProtoMessage:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self.fields = self._parse()

    def _parse(self) -> list[ProtoField]:
        fields: list[ProtoField] = []
        offset = 0
        while offset < len(self._data):
            key, offset = _read_varint(self._data, offset)
            number, wire_type = key >> 3, key & 7
            if number <= 0:
                raise ValueError("invalid protobuf field")
            if wire_type == 0:
                value, offset = _read_varint(self._data, offset)
                fields.append(ProtoField(number, wire_type, value))
            elif wire_type == 1:
                if offset + 8 > len(self._data):
                    raise ValueError("truncated fixed64 field")
                fields.append(ProtoField(number, wire_type, self._data[offset : offset + 8]))
                offset += 8
            elif wire_type == 2:
                length, offset = _read_varint(self._data, offset)
                end = offset + length
                if end > len(self._data):
                    raise ValueError("truncated bytes field")
                fields.append(ProtoField(number, wire_type, self._data[offset:end]))
                offset = end
            elif wire_type == 5:
                if offset + 4 > len(self._data):
                    raise ValueError("truncated fixed32 field")
                fields.append(ProtoField(number, wire_type, self._data[offset : offset + 4]))
                offset += 4
            else:
                raise ValueError(f"unsupported protobuf wire type {wire_type}")
        return fields

    def _first(self, number: int) -> Any:
        for field in self.fields:
            if field.number == number:
                return field.value
        return None

    def get_str(self, number: int) -> str:
        value = self._first(number)
        if not isinstance(value, bytes):
            return ""
        try:
            return value.decode("utf-8", errors="replace")
        except UnicodeDecodeError:
            return ""

    def get_num(self, number: int) -> int:
        value = self._first(number)
        return value if isinstance(value, int) else 0

    def get_sub(self, number: int) -> ProtoMessage:
        value = self._first(number)
        return ProtoMessage(value) if isinstance(value, bytes) else ProtoMessage(b"")


def decode_pb_base64(value: object) -> ProtoMessage | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return ProtoMessage(base64.b64decode(value, validate=True))
    except (ValueError, TypeError):
        return None
