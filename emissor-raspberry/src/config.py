from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip().lower()
    return value in {"1", "true", "yes", "on"}


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value).expanduser() if value else default


@dataclass(frozen=True)
class PipelineConfig:
    enable_image_transmission: bool

    serial_port: str
    baudrate: int
    destination_addr_64: bytes
    xbee_retries: int
    xbee_ack_timeout_s: float
    inter_packet_delay_s: float

    image_chunk_size: int
    image_chunks_per_cycle: int
    telemetry_only_interval_s: float
    loop_sleep_s: float

    sensor_poll_interval_s: float

    capture_start_delay_s: float
    capture_interval_s: float
    capture_count: int

    camera_device_id: int
    camera_input_width: int
    camera_input_height: int
    output_width: int
    output_height: int
    jpeg_quality: int

    sea_level_pressure_hpa: float
    ms5611_addr: int
    mmc56x3_addr: int
    ina226_addr: int
    bmi160_addr: int
    bme280_addr: int
    ina226_r_shunt_ohm: float

    root_dir: Path
    storage_dir: Path
    images_dir: Path
    telemetry_csv_path: Path

    cpp_dir: Path
    cpp_build_dir: Path
    cpp_binary_path: Path



def load_config() -> PipelineConfig:
    src_dir = Path(__file__).resolve().parent
    root_dir = src_dir.parent

    default_storage = root_dir / "storage"
    storage_dir = _env_path("EMISSOR_STORAGE_DIR", default_storage)
    images_dir = _env_path("EMISSOR_IMAGES_DIR", storage_dir / "images")
    telemetry_csv_path = _env_path("EMISSOR_TELEMETRY_CSV", storage_dir / "telemetry.csv")

    cpp_dir = _env_path("CPP_PROJECT_DIR", src_dir / "cpp")
    cpp_build_dir = _env_path("CPP_BUILD_DIR", cpp_dir / "build")
    cpp_binary_path = _env_path("CPP_IMAGE_TOOL", cpp_build_dir / "cansat_image_tool")

    dest_addr = os.getenv("XBEE_DEST_ADDR_64", "0013A200406EFB43").strip()

    return PipelineConfig(
        enable_image_transmission=_env_bool("ENABLE_IMAGE_TRANSMISSION", True),
        serial_port=os.getenv("XBEE_SERIAL_PORT", "/dev/ttyUSB0"),
        baudrate=int(os.getenv("XBEE_BAUDRATE", "9600")),
        destination_addr_64=bytes.fromhex(dest_addr),
        xbee_retries=int(os.getenv("XBEE_RETRIES", "3")),
        xbee_ack_timeout_s=float(os.getenv("XBEE_ACK_TIMEOUT_S", "0.3")),
        inter_packet_delay_s=float(os.getenv("XBEE_INTER_PACKET_DELAY_S", "0.03")),
        image_chunk_size=int(os.getenv("IMAGE_CHUNK_SIZE", "80")),
        image_chunks_per_cycle=int(os.getenv("IMAGE_CHUNKS_PER_CYCLE", "7")),
        telemetry_only_interval_s=float(os.getenv("TELEMETRY_ONLY_INTERVAL_S", "1.0")),
        loop_sleep_s=float(os.getenv("PIPELINE_LOOP_SLEEP_S", "0.02")),
        sensor_poll_interval_s=float(os.getenv("SENSOR_POLL_INTERVAL_S", "0.5")),
        capture_start_delay_s=float(os.getenv("CAPTURE_START_DELAY_S", "5.0")),
        capture_interval_s=float(os.getenv("CAPTURE_INTERVAL_S", "5.0")),
        capture_count=int(os.getenv("CAPTURE_COUNT", "3")),
        camera_device_id=int(os.getenv("CAMERA_DEVICE_ID", "0")),
        camera_input_width=int(os.getenv("CAMERA_INPUT_WIDTH", "2560")),
        camera_input_height=int(os.getenv("CAMERA_INPUT_HEIGHT", "720")),
        output_width=int(os.getenv("OUTPUT_WIDTH", "256")),
        output_height=int(os.getenv("OUTPUT_HEIGHT", "144")),
        jpeg_quality=int(os.getenv("JPEG_QUALITY", "45")),
        sea_level_pressure_hpa=float(os.getenv("SEA_LEVEL_PRESSURE_HPA", "1013.25")),
        ms5611_addr=int(os.getenv("MS5611_ADDR", "0x77"), 0),
        mmc56x3_addr=int(os.getenv("MMC56X3_ADDR", "0x30"), 0),
        ina226_addr=int(os.getenv("INA226_ADDR", "0x40"), 0),
        bmi160_addr=int(os.getenv("BMI160_ADDR", "0x69"), 0),
        bme280_addr=int(os.getenv("BME280_ADDR", "0x76"), 0),
        ina226_r_shunt_ohm=float(os.getenv("INA226_R_SHUNT_OHM", "0.1")),
        root_dir=root_dir,
        storage_dir=storage_dir,
        images_dir=images_dir,
        telemetry_csv_path=telemetry_csv_path,
        cpp_dir=cpp_dir,
        cpp_build_dir=cpp_build_dir,
        cpp_binary_path=cpp_binary_path,
    )
