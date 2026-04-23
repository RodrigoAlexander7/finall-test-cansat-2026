from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"\xAB\xCD"
PACKET_TYPE_IMAGE_CHUNK = 0x01
PACKET_TYPE_TELEMETRY = 0x02

# Must match emissor-raspberry/src/packet_protocol.py
TELEMETRY_STRUCT_FMT = ">q11fH"
TELEMETRY_STRUCT_SIZE = struct.calcsize(TELEMETRY_STRUCT_FMT)  # 54
TELEMETRY_FIELDS_ORDER = [
    "time",
    "alt_ms5611",
    "alt_bme280",
    "pressure",
    "temperature",
    "velocity_z",
    "accel_x",
    "accel_y",
    "accel_z",
    "gyro_z",
    "voltage",
    "current",
    "packets_received",
]


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
        body = payload[3:]
        if len(body) < TELEMETRY_STRUCT_SIZE:
            return None
        try:
            values = struct.unpack(TELEMETRY_STRUCT_FMT, body[:TELEMETRY_STRUCT_SIZE])
            telemetry = dict(zip(TELEMETRY_FIELDS_ORDER, values))
            return TelemetryPacket(telemetry=telemetry)
        except Exception:
            return None

    return None
