from __future__ import annotations

import json
import struct
from typing import Iterable

MAGIC = b"\xAB\xCD"
PACKET_TYPE_IMAGE_CHUNK = 0x01
PACKET_TYPE_TELEMETRY = 0x02

IMAGE_HEADER_SIZE = 9  # magic(2) + type(1) + image_id(2) + index(2) + total(2)


def build_image_chunks(image_id: int, jpeg_data: bytes, chunk_size: int) -> list[bytes]:
    if chunk_size <= IMAGE_HEADER_SIZE:
        raise ValueError("chunk_size must be greater than protocol header size")

    data_size = chunk_size - IMAGE_HEADER_SIZE
    chunks = [jpeg_data[i : i + data_size] for i in range(0, len(jpeg_data), data_size)]
    total = len(chunks)

    payloads: list[bytes] = []
    for index, chunk in enumerate(chunks):
        header = (
            MAGIC
            + bytes([PACKET_TYPE_IMAGE_CHUNK])
            + struct.pack(">H", image_id)
            + struct.pack(">H", index)
            + struct.pack(">H", total)
        )
        payloads.append(header + chunk)
    return payloads


def build_telemetry_packet(telemetry: dict[str, float | int]) -> bytes:
    body = json.dumps(telemetry, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return MAGIC + bytes([PACKET_TYPE_TELEMETRY]) + body


def iter_debug_packet_types(payloads: Iterable[bytes]) -> list[int]:
    packet_types: list[int] = []
    for payload in payloads:
        packet_types.append(payload[2] if len(payload) >= 3 else -1)
    return packet_types
