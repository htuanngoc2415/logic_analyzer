import numpy as np


def measure_channel(bits, sample_rate):
    bits = np.asarray(bits).astype(np.int8)
    if bits.size == 0:
        return {"n_edges": 0, "level": 0}

    dt = 1.0 / sample_rate
    changes = np.diff(bits)
    rising = np.nonzero(changes == 1)[0] + 1
    falling = np.nonzero(changes == -1)[0] + 1
    result = {"n_edges": int(len(rising) + len(falling)), "level": int(bits[0])}

    if len(rising) >= 2:
        periods = np.diff(rising) * dt
        result["period"] = float(np.mean(periods))
        result["freq"] = 1.0 / result["period"] if result["period"] else 0.0
        result["jitter"] = float(np.std(periods))

    if len(rising) and len(falling):
        high_indexes = np.searchsorted(falling, rising, side="right")
        high_ok = high_indexes < len(falling)
        high_widths = (falling[high_indexes[high_ok]] - rising[high_ok]) * dt
        if len(high_widths):
            result["high_avg"] = float(high_widths.mean())
            result["high_min"] = float(high_widths.min())
            result["high_max"] = float(high_widths.max())

        low_indexes = np.searchsorted(rising, falling, side="right")
        low_ok = low_indexes < len(rising)
        low_widths = (rising[low_indexes[low_ok]] - falling[low_ok]) * dt
        if len(low_widths):
            result["low_avg"] = float(low_widths.mean())
            result["low_min"] = float(low_widths.min())
            result["low_max"] = float(low_widths.max())

        if "high_avg" in result and result.get("period", 0) > 0:
            result["duty"] = result["high_avg"] / result["period"] * 100.0

    return result


def measure_capture(capture):
    capture.measurements = {
        ch: measure_channel(capture.channel_bits(ch), capture.sample_rate)
        for ch in range(capture.channels)
    }
    return capture.measurements
