from __future__ import annotations

import struct
from dataclasses import dataclass

try:
    import serial
except Exception:
    serial = None


@dataclass
class TxStatus:
    frame_id: int
    status: int


class XBeeTransmitter:
    def __init__(
        self,
        port: str,
        baudrate: int,
        dest_addr_64: bytes,
        retries: int,
        ack_timeout_s: float,
        logger,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.dest_addr_64 = dest_addr_64
        self.retries = retries
        self.ack_timeout_s = ack_timeout_s
        self.logger = logger
        self.serial_port = None
        self._frame_id = 1

    def open(self) -> None:
        if serial is None:
            self.logger.warning("pyserial no instalado en emisor, TX serial deshabilitado")
            self.serial_port = None
            return

        try:
            self.serial_port = serial.Serial(self.port, self.baudrate, timeout=self.ack_timeout_s)
            self.serial_port.reset_input_buffer()
            self.logger.info("XBee serial abierto en %s @ %s", self.port, self.baudrate)
        except Exception as exc:
            self.serial_port = None
            self.logger.warning("No se pudo abrir puerto XBee %s: %s", self.port, exc)

    def close(self) -> None:
        if self.serial_port is not None:
            try:
                self.serial_port.close()
            except Exception:
                pass
        self.serial_port = None

    def _next_frame_id(self) -> int:
        frame_id = self._frame_id
        self._frame_id = (self._frame_id % 255) + 1
        return frame_id

    @staticmethod
    def build_tx64_frame(frame_id: int, dest64: bytes, data: bytes) -> bytes:
        options = 0x00
        frame_data = bytes([0x00, frame_id]) + dest64 + bytes([options]) + data
        length = len(frame_data)
        checksum = (0xFF - (sum(frame_data) & 0xFF)) & 0xFF
        return b"\x7E" + struct.pack(">H", length) + frame_data + bytes([checksum])

    def _read_api_frame(self) -> bytes | None:
        if self.serial_port is None:
            return None

        start = self.serial_port.read(1)
        if not start or start[0] != 0x7E:
            return None

        length_bytes = self.serial_port.read(2)
        if len(length_bytes) < 2:
            return None

        length = struct.unpack(">H", length_bytes)[0]
        payload = self.serial_port.read(length + 1)
        if len(payload) < length + 1:
            return None

        return b"\x7E" + length_bytes + payload

    @staticmethod
    def parse_tx_status(raw: bytes) -> TxStatus | None:
        if len(raw) < 7 or raw[0] != 0x7E:
            return None
        if raw[3] != 0x89:
            return None
        return TxStatus(frame_id=raw[4], status=raw[5])

    def send_payload(self, payload: bytes) -> bool:
        if self.serial_port is None:
            return False

        frame_id = self._next_frame_id()
        frame = self.build_tx64_frame(frame_id, self.dest_addr_64, payload)

        for attempt in range(1, self.retries + 1):
            try:
                self.serial_port.reset_input_buffer()
                self.serial_port.write(frame)
                self.serial_port.flush()
                raw = self._read_api_frame()
                if raw is None:
                    self.logger.warning("Sin respuesta TX status (intento %s/%s)", attempt, self.retries)
                    continue

                status = self.parse_tx_status(raw)
                if status is None:
                    self.logger.warning("Respuesta no TX status en intento %s/%s", attempt, self.retries)
                    continue

                if status.status == 0:
                    return True

                self.logger.warning(
                    "TX status error=0x%02X (intento %s/%s)",
                    status.status,
                    attempt,
                    self.retries,
                )
            except Exception as exc:
                self.logger.warning("Error enviando payload por XBee: %s", exc)

        return False
