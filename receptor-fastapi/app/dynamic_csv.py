from __future__ import annotations

import csv
from pathlib import Path
from threading import Lock

KNOWN_ORDER = [
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


class DynamicCsvWriter:
    def __init__(self, csv_path: Path) -> None:
        self.csv_path = csv_path
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._fieldnames = self._read_existing_fieldnames()

    def _read_existing_fieldnames(self) -> list[str]:
        if not self.csv_path.exists() or self.csv_path.stat().st_size == 0:
            return []
        with self.csv_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            row = next(reader, None)
            return row or []

    @staticmethod
    def _ordered_fieldnames(keys: set[str]) -> list[str]:
        remaining = sorted(k for k in keys if k not in KNOWN_ORDER)
        ordered = [k for k in KNOWN_ORDER if k in keys]
        ordered.extend(remaining)
        return ordered

    def _rewrite_with_new_header(self, new_fieldnames: list[str]) -> None:
        rows: list[dict[str, str]] = []

        if self.csv_path.exists() and self.csv_path.stat().st_size > 0:
            with self.csv_path.open("r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

        with self.csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=new_fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in new_fieldnames})

        self._fieldnames = new_fieldnames

    def append(self, row: dict[str, float | int]) -> None:
        with self._lock:
            row_keys = set(row.keys())
            if not self._fieldnames:
                self._fieldnames = self._ordered_fieldnames(row_keys)
                self._rewrite_with_new_header(self._fieldnames)
            elif not row_keys.issubset(set(self._fieldnames)):
                merged = set(self._fieldnames).union(row_keys)
                self._rewrite_with_new_header(self._ordered_fieldnames(merged))

            with self.csv_path.open("a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self._fieldnames)
                writer.writerow({field: row.get(field, 0) for field in self._fieldnames})
