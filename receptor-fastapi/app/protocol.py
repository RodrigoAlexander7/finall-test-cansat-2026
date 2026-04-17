from __future__ import annotations

import json
import struct
from dataclasses import dataclass

MAGIC = b"\xAB\xCD"
PACKET_TYPE_IMAGE_CHUNK = 0x01
PACKET_TYPE_TELEMETRY = 0x02


@dataclass
class ImageChunkPacket:
    image_id: int
    chunk_index: int
    total_chunks: int
    data: bytes


@dataclass
class TelemetryPacket:
    telemetry: dict[str, float | int]


def parse_application_payload(payload: bytes) -> ImageChunkPacket | TelemetryPacket | None:
    if len(payload) < 3:
        return None
    if payload[:2] != MAGIC:
        return None

    packet_type = payload[2]

    if packet_type == PACKET_TYPE_IMAGE_CHUNK:
        if len(payload) < 9:
            return None
        image_id = struct.unpack(">H", payload[3:5])[0]
        chunk_index = struct.unpack(">H", payload[5:7])[0]
        total_chunks = struct.unpack(">H", payload[7:9])[0]
        data = payload[9:]
        return ImageChunkPacket(
            image_id=image_id,
            chunk_index=chunk_index,
            total_chunks=total_chunks,
            data=data,
        )

    if packet_type == PACKET_TYPE_TELEMETRY:
        try:
            body = payload[3:].decode("utf-8")
            data = json.loads(body)
            if not isinstance(data, dict):
                return None
            return TelemetryPacket(telemetry=data)
        except Exception:
            return None

    return None
