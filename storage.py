import csv
import json
from datetime import datetime

import numpy as np

from capture_model import Capture


DECODE_FIELDS = ("decoded_uart", "decoded_i2c", "decoded_spi", "decoded_onewire")


def _json_default(value):
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def save_capture(path: str, capture: Capture) -> None:
    decode_data = {name: getattr(capture, name) for name in DECODE_FIELDS}
    np.savez_compressed(
        path,
        sample_rate=int(capture.sample_rate),
        num_samples=int(capture.num_samples),
        channels=int(capture.channels),
        raw_samples=np.asarray(capture.raw_samples, dtype=np.uint8),
        trigger_type=int(capture.trigger_type),
        trigger_channel=int(capture.trigger_channel),
        pattern_mask=int(capture.pattern_mask),
        pattern_value=int(capture.pattern_value),
        triggered=int(capture.triggered),
        capture_time=capture.capture_time.isoformat(),
        measurements=json.dumps(capture.measurements, default=_json_default),
        decoders=json.dumps(decode_data, default=_json_default),
    )


def open_capture(path: str) -> Capture:
    data = np.load(path, allow_pickle=False)
    capture = Capture(
        sample_rate=int(data["sample_rate"]),
        num_samples=int(data["num_samples"]),
        channels=int(data["channels"]),
        raw_samples=data["raw_samples"].astype(np.uint8),
        trigger_type=int(data["trigger_type"]) if "trigger_type" in data else 0,
        trigger_channel=int(data["trigger_channel"]) if "trigger_channel" in data else 0,
        pattern_mask=int(data["pattern_mask"]) if "pattern_mask" in data else 0,
        pattern_value=int(data["pattern_value"]) if "pattern_value" in data else 0,
        triggered=bool(int(data["triggered"])) if "triggered" in data else False,
        capture_time=datetime.fromisoformat(str(data["capture_time"]))
        if "capture_time" in data
        else datetime.now(),
    )
    if "measurements" in data:
        raw_measurements = json.loads(str(data["measurements"]))
        capture.measurements = {int(k): v for k, v in raw_measurements.items()}
    if "decoders" in data:
        decoded = json.loads(str(data["decoders"]))
        for name in DECODE_FIELDS:
            setattr(capture, name, decoded.get(name, []))
    return capture


def export_raw_csv(path: str, capture: Capture) -> None:
    samples = np.asarray(capture.raw_samples, dtype=np.uint8)
    time_us = np.arange(capture.num_samples) / capture.sample_rate * 1e6
    columns = [((samples >> ch) & 1) for ch in range(capture.channels)]
    table = np.column_stack([time_us] + columns)
    header = "Time (us)," + ",".join(f"CH{ch}" for ch in range(capture.channels))
    np.savetxt(
        path,
        table,
        delimiter=",",
        header=header,
        comments="",
        fmt=["%.6f"] + ["%d"] * capture.channels,
    )


def export_decode_csv(path: str, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["Time (us)", "Protocol", "Event", "Value"])
        for row in rows:
            writer.writerow([row["time_us"], row["protocol"], row["event"], row["value"]])
