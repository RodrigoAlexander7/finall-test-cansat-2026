"""
XBee Pro S1 - Image Transmitter (API Mode 1)
=============================================
Config used:  AP=1, BD=115200, MM=0, RR=3
Destination:  0013A200406EFB43  (receiver SH+SL)
"""

import serial
import time
import struct
import os
import sys

# ── Serial port ──────────────────────────────────────────────────────────────
PORT       = "COM3"        # Change to your port (Linux: "/dev/ttyUSB0")
BAUDRATE   = 9600

# ── XBee destination (receiver SH + SL) ─────────────────────────────────────
DEST_ADDR_64 = bytes.fromhex("0013A200406EFB43")

# ── Protocol ─────────────────────────────────────────────────────────────────
MAGIC       = b'\xAB\xCD'   # 2-byte packet identifier
HEADER_SIZE = 6             # magic(2) + chunk_index(2) + total_chunks(2)
CHUNK_SIZE  = 80            # bytes of image data per packet
INTER_PACKET_DELAY = 0.05   # 50 ms between packets (give receiver time)

# ── XBee API helpers ──────────────────────────────────────────────────────────

def build_tx64_frame(frame_id: int, dest64: bytes, data: bytes) -> bytes:
    """Build a TX Request (64-bit address) API frame — frame type 0x00."""
    options = 0x00  # 0x01 = disable ACK; keep 0x00 to use RR retries
    frame_data = bytes([0x00, frame_id]) + dest64 + bytes([options]) + data
    length     = len(frame_data)
    checksum   = (0xFF - (sum(frame_data) & 0xFF)) & 0xFF
    return (
        b'\x7E'
        + struct.pack('>H', length)
        + frame_data
        + bytes([checksum])
    )


def parse_response(raw: bytes):
    """Minimally parse a TX Status (0x89) frame to check delivery."""
    # 7E | LEN(2) | 0x89 | frame_id | status | checksum
    if len(raw) < 7 or raw[0] != 0x7E:
        return None
    frame_type = raw[3]
    if frame_type == 0x89:
        return {"type": "TX_STATUS", "frame_id": raw[4], "status": raw[5]}
    return {"type": hex(frame_type)}


def read_api_frame(ser: serial.Serial, timeout: float = 0.3) -> bytes | None:
    """Read one API frame from the serial port. Returns raw bytes or None."""
    ser.timeout = timeout
    start = ser.read(1)
    if not start or start[0] != 0x7E:
        return None
    length_bytes = ser.read(2)
    if len(length_bytes) < 2:
        return None
    length = struct.unpack('>H', length_bytes)[0]
    payload = ser.read(length + 1)  # +1 for checksum
    if len(payload) < length + 1:
        return None
    return b'\x7E' + length_bytes + payload


# ── Main transmit logic ───────────────────────────────────────────────────────

def transmit_image(image_path: str):
    if not os.path.isfile(image_path):
        print(f"[ERROR] File not found: {image_path}")
        sys.exit(1)

    with open(image_path, 'rb') as f:
        image_data = f.read()

    file_size = len(image_data)
    chunks    = [image_data[i:i + CHUNK_SIZE]
                 for i in range(0, file_size, CHUNK_SIZE)]
    total     = len(chunks)

    print(f"[INFO] File: {image_path} ({file_size} bytes)")
    print(f"[INFO] Chunks: {total} × up to {CHUNK_SIZE} B = "
          f"{HEADER_SIZE + CHUNK_SIZE} B/frame max")
    print(f"[INFO] Opening {PORT} @ {BAUDRATE} baud …\n")

    with serial.Serial(PORT, BAUDRATE, timeout=0.3) as ser:
        time.sleep(0.1)         # let port settle
        ser.reset_input_buffer()

        for idx, chunk in enumerate(chunks):
            # Build payload: MAGIC + chunk_index (2B) + total (2B) + data
            payload = (MAGIC
                       + struct.pack('>H', idx)
                       + struct.pack('>H', total)
                       + chunk)

            frame_id = (idx % 255) + 1  # 1-255; 0 = no ACK
            frame    = build_tx64_frame(frame_id, DEST_ADDR_64, payload)

            for attempt in range(3):
                ser.write(frame)
                if attempt == 0:
                    print(f"  → Chunk {idx+1:4}/{total}  ({len(chunk):3} B)  "
                          f"frame {len(frame):3} B …", end=' ', flush=True)
                else:
                    print(f"  → [Reintento {attempt}/3] Chunk {idx+1:4} …", end=' ', flush=True)

                # Optional: wait for TX Status (0x89)
                response = read_api_frame(ser, timeout=0.3)
                success = False
                if response:
                    parsed = parse_response(response)
                    if parsed and parsed.get("type") == "TX_STATUS":
                        status = parsed["status"]
                        if status == 0:
                            print("ACK OK")
                            success = True
                        else:
                            print(f"status=0x{status:02X}")
                    else:
                        print("(no status frame)")
                else:
                    print("(no response)")
                    
                if success:
                    break
                else:
                    time.sleep(INTER_PACKET_DELAY * 2)

            time.sleep(INTER_PACKET_DELAY)

    print(f"\n[DONE] {total} chunks sent for '{os.path.basename(image_path)}'")


if __name__ == "__main__":
    image = sys.argv[1] if len(sys.argv) > 1 else "foto.jpg"
    transmit_image(image)