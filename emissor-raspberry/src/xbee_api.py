from __future__ import annotations

import struct
from dataclasses import dataclass

try:
    import serial
except Exception:
    serial = None


class XBeeTransmitter:
    def __init__(
        self,
        port: str,
        baudrate: int,
        dest_addr_64: bytes,
        inter_packet_delay_s: float,
        logger,
        **_extra,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.dest_addr_64 = dest_addr_64
        self.inter_packet_delay_s = inter_packet_delay_s
        self.logger = logger
        self.serial_port = None

    def open(self) -> None:
        if serial is None:
            self.logger.warning("pyserial no instalado en emisor, TX serial deshabilitado")
            self.serial_port = None
            return

        try:
            self.serial_port = serial.Serial(self.port, self.baudrate, timeout=0.1)
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

    @staticmethod
    def build_tx64_frame(dest64: bytes, data: bytes) -> bytes:
        """Build a TX Request 64-bit frame with frame_id=0 (fire-and-forget, no TX Status)."""
        frame_id = 0x00  # no TX Status response
        options = 0x00
        frame_data = bytes([0x00, frame_id]) + dest64 + bytes([options]) + data
        length = len(frame_data)
        checksum = (0xFF - (sum(frame_data) & 0xFF)) & 0xFF
        return b"\x7E" + struct.pack(">H", length) + frame_data + bytes([checksum])

    def send_payload(self, payload: bytes) -> bool:
        if self.serial_port is None:
            return False

        frame = self.build_tx64_frame(self.dest_addr_64, payload)

        try:
            self.serial_port.write(frame)
            self.serial_port.flush()
            return True
        except Exception as exc:
            self.logger.warning("Error enviando payload por XBee: %s", exc)
            return False
