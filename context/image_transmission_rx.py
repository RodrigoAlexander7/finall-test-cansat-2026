"""
XBee Pro S1 - Image Receiver (API Mode 1)
==========================================
Config used:  AP=1, BD=115200, MM=0
Listens for RX64 (0x80) frames, reassembles image from chunks.
"""

import serial
import struct
import time
import os
import sys

# ── Serial port ──────────────────────────────────────────────────────────────
PORT     = "/dev/ttyUSB0"        # Change to your port (Linux: "/dev/ttyUSB1")
BAUDRATE = 9600

# ── Protocol (must match transmitter) ────────────────────────────────────────
MAGIC       = b'\xAB\xCD'
HEADER_SIZE = 6           # magic(2) + chunk_index(2) + total_chunks(2)
OUTPUT_FILE = "received_foto.jpg"

# ── XBee API helpers ──────────────────────────────────────────────────────────

# def read_api_frame(ser: serial.Serial) -> bytes | None:
#     """
#     Block until a full API frame arrives.
#     Returns raw bytes starting with 0x7E, or None on timeout/error.
#     """
#     # Sync to start delimiter
#     while True:
#         b = ser.read(1)
#         if not b:
#             return None          # timeout
#         if b[0] == 0x7E:
#             break

#     length_bytes = ser.read(2)
#     if len(length_bytes) < 2:
#         return None
#     length = struct.unpack('>H', length_bytes)[0]

#     payload = ser.read(length + 1)   # +1 for checksum
#     if len(payload) < length + 1:
#         return None

#     return b'\x7E' + length_bytes + payload

def read_api_frame(ser: serial.Serial) -> bytes | None:
    # Sync to start delimiter
    while True:
        b = ser.read(1)
        if not b:
            return None          # timeout
        
        if b[0] == 0x7E:
            break

    length_bytes = ser.read(2)
    if len(length_bytes) < 2:
        return None
    length = struct.unpack('>H', length_bytes)[0]

    payload = ser.read(length + 1)   # +1 for checksum
    if len(payload) < length + 1:
        return None

    return b'\x7E' + length_bytes + payload

def parse_rx64_frame(raw: bytes) -> dict | None:
    """
    Parse an RX64 (0x80) or RX16 (0x81) frame.
    Returns dict with keys: src_addr(bytes), rssi(int), options(int), data(bytes).
    Returns None if frame is malformed.
    """
    if len(raw) < 9 or raw[0] != 0x7E:
        return None

    frame_type = raw[3]

    if frame_type == 0x80:
        if len(raw) < 15: return None
        src_addr = raw[4:12]
        rssi     = raw[12]
        options  = raw[13]
        data     = raw[14:-1]
    elif frame_type == 0x81:
        if len(raw) < 9: return None
        src_addr = raw[4:6]
        rssi     = raw[6]
        options  = raw[7]
        data     = raw[8:-1]
    else:
        return None

    # Verify checksum
    body     = raw[3:-1]
    checksum = raw[-1]
    if (sum(body) + checksum) & 0xFF != 0xFF:
        print(f"[WARN] Checksum mismatch — frame dropped. sum: {(sum(body) + checksum) & 0xFF}")
        return None

    return {
        "src_addr": src_addr,
        "rssi":     rssi,
        "options":  options,
        "data":     data,
    }


# ── Packet protocol parser ────────────────────────────────────────────────────

def parse_chunk(data: bytes) -> tuple[int, int, bytes] | None:
    """
    Parse application-level chunk payload.
    Returns (chunk_index, total_chunks, image_bytes) or None if invalid.
    """
    if len(data) < HEADER_SIZE:
        return None
    if data[:2] != MAGIC:
        return None
    chunk_index  = struct.unpack('>H', data[2:4])[0]
    total_chunks = struct.unpack('>H', data[4:6])[0]
    chunk_data   = data[6:]
    return chunk_index, total_chunks, chunk_data


# ── Main receive loop ─────────────────────────────────────────────────────────

def receive_image():
    print(f"[INFO] Opening {PORT} @ {BAUDRATE} baud …")
    print(f"[INFO] Waiting for packets (CTRL+C to abort) …\n")

    chunks_store: dict[int, bytes] = {}
    total_expected = None

    with serial.Serial(PORT, BAUDRATE, timeout=5.0) as ser:
        time.sleep(0.1)
        ser.reset_input_buffer()
        
        timeouts_occurred = 0

        while True:
            raw = read_api_frame(ser)
            if raw is None:
                if total_expected is not None:
                    missing = [i for i in range(total_expected)
                               if i not in chunks_store]
                    if missing:
                        print(f"[WAIT] Still missing {len(missing)} chunk(s): "
                              f"{missing[:10]}{'…' if len(missing) > 10 else ''}")
                        
                        timeouts_occurred += 1
                        if timeouts_occurred >= 3: # 15 seconds waiting total
                            print("[WARN] Se acabó el tiempo de espera. Procediendo con los chunks recuperados...")
                            break
                    else:
                        break   # all chunks received, exit loop
                continue

            timeouts_occurred = 0  # reset on valid packet

            parsed = parse_rx64_frame(raw)
            if parsed is None:
                print(f"[DEBUG] Failed to parse: type=0x{raw[3]:02X} len={len(raw)} raw={raw.hex().upper()}")
                continue

            result = parse_chunk(parsed["data"])
            if result is None:
                print(f"[SKIP] Non-image packet from "
                      f"{parsed['src_addr'].hex().upper()}")
                continue

            idx, total, chunk_data = result

            if total_expected is None:
                total_expected = total
                print(f"[INFO] Transfer started — expecting {total} chunks")

            if idx in chunks_store:
                print(f"  ↩  Chunk {idx+1:4}/{total} (duplicate, ignored)")
                continue

            chunks_store[idx] = chunk_data
            received = len(chunks_store)
            pct = received / total * 100

            src = parsed['src_addr'].hex().upper()
            print(f"  ← Chunk {idx+1:4}/{total}  "
                  f"({len(chunk_data):3} B)  RSSI -{ parsed['rssi']}dBm  "
                  f"[{'█' * (received * 20 // total):<20}] {pct:5.1f}%")

            # Check completion
            if received == total:
                print(f"\n[INFO] All {total} chunks received — reassembling …")
                break

    # Reassemble in order
    if not chunks_store:
        print("[ERROR] No data received.")
        sys.exit(1)

    received_total = len(chunks_store)
    if total_expected and received_total < total_expected:
        missing = [i for i in range(total_expected) if i not in chunks_store]
        print(f"[WARN] Missing {len(missing)} chunk(s): {missing}")
        print("[WARN] Image may be incomplete/corrupt.")

    image_data = b''.join(chunks_store[i]
                          for i in range(max(chunks_store.keys()) + 1)
                          if i in chunks_store)

    with open(OUTPUT_FILE, 'wb') as f:
        f.write(image_data)

    print(f"[DONE] Saved {len(image_data)} bytes → '{OUTPUT_FILE}'")


if __name__ == "__main__":
    try:
        receive_image()
    except KeyboardInterrupt:
        print("\n[ABORT] Interrupted by user.")