from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ReceiverConfig:
    enable_image_transmission: bool
    serial_port: str
    baudrate: int
    serial_timeout_s: float

    host: str
    port: int

    root_dir: Path
    received_dir: Path
    telemetry_csv_path: Path


def load_config() -> ReceiverConfig:
    app_dir = Path(__file__).resolve().parent
    root_dir = app_dir.parent

    received_dir = Path(os.getenv("RECEIVED_DIR", str(root_dir / "received"))).expanduser()
    telemetry_csv_path = Path(
        os.getenv("RECEIVER_TELEMETRY_CSV", str(root_dir / "data" / "telemetry.csv"))
    ).expanduser()

    return ReceiverConfig(
        enable_image_transmission=_env_bool("ENABLE_IMAGE_TRANSMISSION", True),
        serial_port=os.getenv("XBEE_SERIAL_PORT", "/dev/ttyUSB0"),
        baudrate=int(os.getenv("XBEE_BAUDRATE", "9600")),
        serial_timeout_s=float(os.getenv("XBEE_SERIAL_TIMEOUT_S", "0.5")),
        host=os.getenv("FASTAPI_HOST", "0.0.0.0"),
        port=int(os.getenv("FASTAPI_PORT", "8000")),
        root_dir=root_dir,
        received_dir=received_dir,
        telemetry_csv_path=telemetry_csv_path,
    )
