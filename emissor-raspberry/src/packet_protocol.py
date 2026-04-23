from __future__ import annotations

import struct
from typing import Iterable

MAGIC = b"\xAB\xCD"
PACKET_TYPE_IMAGE_CHUNK = 0x01
PACKET_TYPE_TELEMETRY = 0x02

IMAGE_HEADER_SIZE = 9  # magic(2) + type(1) + image_id(2) + index(2) + total(2)

# Binary telemetry: >q11fH = 54 bytes payload, 57 total with header
# Fields (in order): time(i64), alt_ms5611(f32), alt_bme280(f32), pressure(f32),
# temperature(f32), velocity_z(f32), accel_x(f32), accel_y(f32), accel_z(f32),
# gyro_z(f32), voltage(f32), current(f32), packets_received(u16)
TELEMETRY_STRUCT_FMT = ">q11fH"
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
    values = []
    for field_name in TELEMETRY_FIELDS_ORDER:
        val = telemetry.get(field_name, 0)
        if field_name == "time":
            values.append(int(val))
        elif field_name == "packets_received":
            values.append(int(val) & 0xFFFF)
        else:
            values.append(float(val))
    body = struct.pack(TELEMETRY_STRUCT_FMT, *values)
    return MAGIC + bytes([PACKET_TYPE_TELEMETRY]) + body


def iter_debug_packet_types(payloads: Iterable[bytes]) -> list[int]:
    packet_types: list[int] = []
    for payload in payloads:
        packet_types.append(payload[2] if len(payload) >= 3 else -1)
    return packet_types
