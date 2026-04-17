from __future__ import annotations

import csv
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from config import PipelineConfig, load_config
from logging_utils import setup_logging
from packet_protocol import build_image_chunks, build_telemetry_packet
from sensors import SensorSuite
from xbee_api import XBeeTransmitter


TELEMETRY_FIELDS = [
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


class TelemetryCsvWriter:
    def __init__(self, csv_path: Path) -> None:
        self.csv_path = csv_path
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.csv_path.open("a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=TELEMETRY_FIELDS)

        if self.csv_path.stat().st_size == 0:
            self._writer.writeheader()
            self._file.flush()

    def append(self, telemetry: dict[str, float | int]) -> None:
        row = {field: telemetry.get(field, 0) for field in TELEMETRY_FIELDS}
        self._writer.writerow(row)
        self._file.flush()

    def close(self) -> None:
        self._file.close()


class SensorPollingWorker:
    def __init__(
        self,
        sensor_suite: SensorSuite,
        csv_writer: TelemetryCsvWriter,
        poll_interval_s: float,
        logger,
    ) -> None:
        self.sensor_suite = sensor_suite
        self.csv_writer = csv_writer
        self.poll_interval_s = poll_interval_s
        self.logger = logger

        self._lock = threading.Lock()
        self._latest = {field: 0 for field in TELEMETRY_FIELDS}
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=2.0)

    def latest(self) -> dict[str, float | int]:
        with self._lock:
            return dict(self._latest)

    def _run(self) -> None:
        self.logger.info("Inicio lectura continua de sensores")
        while not self._stop_event.is_set():
            t0 = time.perf_counter()
            telemetry = self.sensor_suite.read_telemetry()
            self.csv_writer.append(telemetry)
            with self._lock:
                self._latest = telemetry
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self.logger.info("sensors_step_ms=%.2f", elapsed_ms)
            self._stop_event.wait(self.poll_interval_s)


@dataclass
class CaptureResult:
    output_path: Path
    size_bytes: int
    elapsed_ms: float


class CppImageTool:
    def __init__(self, cfg: PipelineConfig, logger) -> None:
        self.cfg = cfg
        self.logger = logger

    def ensure_built(self) -> None:
        if self.cfg.cpp_binary_path.exists():
            self.logger.info("Binario C++ detectado: %s", self.cfg.cpp_binary_path)
            return

        self.cfg.cpp_build_dir.mkdir(parents=True, exist_ok=True)

        t0 = time.perf_counter()
        configure_cmd = [
            "cmake",
            "-S",
            str(self.cfg.cpp_dir),
            "-B",
            str(self.cfg.cpp_build_dir),
        ]
        build_cmd = [
            "cmake",
            "--build",
            str(self.cfg.cpp_build_dir),
            "-j2",
        ]

        self.logger.info("Configurando C++: %s", " ".join(configure_cmd))
        subprocess.run(configure_cmd, check=True)

        self.logger.info("Compilando C++: %s", " ".join(build_cmd))
        subprocess.run(build_cmd, check=True)

        if not self.cfg.cpp_binary_path.exists():
            raise RuntimeError(f"No se genero binario C++ en {self.cfg.cpp_binary_path}")

        self.logger.info("cpp_build_ms=%.2f", (time.perf_counter() - t0) * 1000.0)

    def capture_processed_image(self, output_path: Path) -> CaptureResult:
        cmd = [
            str(self.cfg.cpp_binary_path),
            "--output",
            str(output_path),
            "--device-id",
            str(self.cfg.camera_device_id),
            "--input-width",
            str(self.cfg.camera_input_width),
            "--input-height",
            str(self.cfg.camera_input_height),
            "--output-width",
            str(self.cfg.output_width),
            "--output-height",
            str(self.cfg.output_height),
            "--jpeg-quality",
            str(self.cfg.jpeg_quality),
        ]

        t0 = time.perf_counter()
        subprocess.run(cmd, check=True)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        size_bytes = output_path.stat().st_size
        return CaptureResult(output_path=output_path, size_bytes=size_bytes, elapsed_ms=elapsed_ms)


class EmissorPipeline:
    def __init__(self, cfg: PipelineConfig) -> None:
        self.cfg = cfg
        self.logger = setup_logging("emissor.pipeline")

        self.cfg.storage_dir.mkdir(parents=True, exist_ok=True)
        self.cfg.images_dir.mkdir(parents=True, exist_ok=True)

        self.csv_writer = TelemetryCsvWriter(self.cfg.telemetry_csv_path)
        self.sensor_suite = SensorSuite(self.cfg, self.logger)
        self.sensor_worker = SensorPollingWorker(
            sensor_suite=self.sensor_suite,
            csv_writer=self.csv_writer,
            poll_interval_s=self.cfg.sensor_poll_interval_s,
            logger=self.logger,
        )

        self.xbee = XBeeTransmitter(
            port=self.cfg.serial_port,
            baudrate=self.cfg.baudrate,
            dest_addr_64=self.cfg.destination_addr_64,
            retries=self.cfg.xbee_retries,
            ack_timeout_s=self.cfg.xbee_ack_timeout_s,
            logger=self.logger,
        )

        self.cpp_tool = CppImageTool(self.cfg, self.logger)

        self._image_packet_queue: deque[bytes] = deque()
        self._next_image_id = 1
        self._image_burst_counter = 0
        self._last_telemetry_sent_s = 0.0
        self._packets_sent = 0

    def _capture_and_queue_image(self, capture_number: int) -> None:
        timestamp_ms = int(time.time() * 1000)
        output_path = self.cfg.images_dir / f"anaglyph_{capture_number:02d}_{timestamp_ms}.jpg"

        self.logger.info("capture_step_start index=%s", capture_number)
        result = self.cpp_tool.capture_processed_image(output_path)
        self.logger.info(
            "capture_step_done index=%s output=%s size=%sB elapsed_ms=%.2f",
            capture_number,
            result.output_path,
            result.size_bytes,
            result.elapsed_ms,
        )

        image_data = output_path.read_bytes()
        chunks = build_image_chunks(
            image_id=self._next_image_id,
            jpeg_data=image_data,
            chunk_size=self.cfg.image_chunk_size,
        )

        for payload in chunks:
            self._image_packet_queue.append(payload)

        self.logger.info(
            "image_queue_add image_id=%s chunks=%s queue_size=%s",
            self._next_image_id,
            len(chunks),
            len(self._image_packet_queue),
        )

        self._next_image_id += 1

    def _send_payload(self, payload: bytes, payload_type: str) -> None:
        t0 = time.perf_counter()
        ok = self.xbee.send_payload(payload)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        if ok:
            self._packets_sent += 1
            self.logger.info(
                "tx_ok type=%s bytes=%s elapsed_ms=%.2f packets_sent=%s",
                payload_type,
                len(payload),
                elapsed_ms,
                self._packets_sent,
            )
        else:
            self.logger.warning(
                "tx_fail type=%s bytes=%s elapsed_ms=%.2f",
                payload_type,
                len(payload),
                elapsed_ms,
            )

        time.sleep(self.cfg.inter_packet_delay_s)

    def run(self) -> None:
        self.logger.info("Pipeline iniciado")
        self.logger.info("ENABLE_IMAGE_TRANSMISSION=%s", self.cfg.enable_image_transmission)

        image_enabled = self.cfg.enable_image_transmission
        if image_enabled:
            try:
                self.cpp_tool.ensure_built()
            except Exception as exc:
                self.logger.warning("No se pudo preparar binario C++ (%s). Se continua solo telemetria", exc)
                image_enabled = False

        self.sensor_worker.start()
        self.xbee.open()

        start_s = time.monotonic()
        next_capture_s = start_s + self.cfg.capture_start_delay_s
        captures_done = 0

        try:
            while True:
                now_s = time.monotonic()
                telemetry = self.sensor_worker.latest()

                if (
                    image_enabled
                    and captures_done < self.cfg.capture_count
                    and now_s >= next_capture_s
                ):
                    captures_done += 1
                    try:
                        self._capture_and_queue_image(captures_done)
                    except Exception as exc:
                        self.logger.warning("Fallo captura/proceso en toma %s: %s", captures_done, exc)
                    next_capture_s += self.cfg.capture_interval_s
                    if captures_done >= self.cfg.capture_count:
                        self.logger.info("Se completaron %s capturas, camara apagada", self.cfg.capture_count)

                if image_enabled and self._image_packet_queue:
                    if self._image_burst_counter < self.cfg.image_chunks_per_cycle:
                        payload = self._image_packet_queue.popleft()
                        self._send_payload(payload, "image")
                        self._image_burst_counter += 1
                    else:
                        telemetry_payload = build_telemetry_packet(telemetry)
                        self._send_payload(telemetry_payload, "telemetry")
                        self._image_burst_counter = 0
                        self._last_telemetry_sent_s = now_s
                else:
                    if now_s - self._last_telemetry_sent_s >= self.cfg.telemetry_only_interval_s:
                        telemetry_payload = build_telemetry_packet(telemetry)
                        self._send_payload(telemetry_payload, "telemetry")
                        self._last_telemetry_sent_s = now_s

                time.sleep(self.cfg.loop_sleep_s)
        except KeyboardInterrupt:
            self.logger.info("Pipeline detenido por usuario")
        finally:
            self.sensor_worker.stop()
            self.sensor_suite.close()
            self.xbee.close()
            self.csv_writer.close()
            self.logger.info("Pipeline finalizado")


def main() -> None:
    config = load_config()
    pipeline = EmissorPipeline(config)
    pipeline.run()


if __name__ == "__main__":
    main()
