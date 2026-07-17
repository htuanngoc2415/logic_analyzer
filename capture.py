import struct
import time
from datetime import datetime

import numpy as np
import serial
from serial.tools import list_ports

from capture_model import Capture


MAGIC = bytes([0xAA, 0x55, 0xA5, 0x5A])
HEADER_SIZE = 12
CMD_ARM = b"a"


class CaptureProtocolError(Exception):
    pass


def list_serial_ports() -> list[str]:
    return [port.device for port in list_ports.comports()]


def find_default_port() -> str | None:
    ports = list(list_ports.comports())
    for port in ports:
        if (
            port.vid == 0x2E8A
            or "Pico" in (port.description or "")
            or "USB Serial" in (port.description or "")
        ):
            return port.device
    return ports[0].device if ports else None


def create_mock_capture(
    rate_hz: int,
    trig_type: int,
    trig_ch: int,
    pat_mask: int = 0,
    pat_val: int = 0,
    num_samples: int = 200_000,
) -> Capture:
    sample_index = np.arange(num_samples, dtype=np.uint32)
    samples = np.zeros(num_samples, dtype=np.uint8)

    # Deterministic digital signals with different periods for visual testing.
    periods = [32, 67, 128, 251, 511, 997, 2048, 4096]
    for channel, period in enumerate(periods):
        signal = ((sample_index // (period // 2)) & 1).astype(np.uint8)
        samples |= signal << channel

    # Add a short UART-like burst on CH0 so decoder annotations can be tested.
    baud = 115200
    samples_per_bit = max(2, int(rate_hz / baud))
    start = min(num_samples // 5, max(0, num_samples - samples_per_bit * 120))
    samples[:, ...] |= 1
    cursor = start
    for byte in b"LA":
        bits = [0] + [(byte >> bit) & 1 for bit in range(8)] + [1]
        for bit in bits:
            end = min(cursor + samples_per_bit, num_samples)
            if bit:
                samples[cursor:end] |= 1
            else:
                samples[cursor:end] &= 0xFE
            cursor = end

    return Capture(
        sample_rate=int(rate_hz),
        num_samples=int(num_samples),
        channels=8,
        raw_samples=samples,
        trigger_type=int(trig_type),
        trigger_channel=int(trig_ch),
        pattern_mask=int(pat_mask),
        pattern_value=int(pat_val),
        triggered=True,
        capture_time=datetime.now(),
    )


def read_exact(ser: serial.Serial, count: int) -> bytes:
    data = bytearray()
    while len(data) < count:
        chunk = ser.read(count - len(data))
        if not chunk:
            raise TimeoutError(f"Timed out while reading frame ({len(data)}/{count} bytes)")
        data.extend(chunk)
    return bytes(data)


def sync_to_magic(ser: serial.Serial) -> None:
    window = bytearray()
    while True:
        byte = ser.read(1)
        if not byte:
            raise TimeoutError("Timed out waiting for capture frame magic")
        window.extend(byte)
        if len(window) > len(MAGIC):
            del window[0]
        if bytes(window) == MAGIC:
            return


def arm_and_receive(
    port: str,
    rate_hz: int,
    trig_type: int,
    trig_ch: int,
    pat_mask: int = 0,
    pat_val: int = 0,
    baudrate: int = 115200,
    timeout: float = 8.0,
) -> Capture:
    with serial.Serial(port, baudrate, timeout=timeout) as ser:
        time.sleep(0.25)
        ser.reset_input_buffer()
        ser.write(
            CMD_ARM
            + struct.pack("<I", int(rate_hz))
            + bytes([trig_type & 0xFF, trig_ch & 0xFF, pat_mask & 0xFF, pat_val & 0xFF])
        )
        ser.flush()

        sync_to_magic(ser)
        header = read_exact(ser, HEADER_SIZE)
        version, channels, reserved, sample_rate, num_samples = struct.unpack("<BBHII", header)
        if version != 1:
            raise CaptureProtocolError(f"Unsupported frame version: {version}")
        if channels < 1 or channels > 8:
            raise CaptureProtocolError(f"Invalid channel count: {channels}")
        if num_samples == 0:
            raise CaptureProtocolError("Capture frame has no samples")

        payload = read_exact(ser, num_samples)
        checksum_recv = struct.unpack("<I", read_exact(ser, 4))[0]
        checksum_calc = sum(payload) & 0xFFFFFFFF
        if checksum_recv != checksum_calc:
            raise CaptureProtocolError(
                f"Checksum mismatch: received 0x{checksum_recv:08X}, calculated 0x{checksum_calc:08X}"
            )

    return Capture(
        sample_rate=int(sample_rate),
        num_samples=int(num_samples),
        channels=int(channels),
        raw_samples=np.frombuffer(payload, dtype=np.uint8).copy(),
        trigger_type=int(trig_type),
        trigger_channel=int(trig_ch),
        pattern_mask=int(pat_mask),
        pattern_value=int(pat_val),
        triggered=bool(reserved & 1),
        capture_time=datetime.now(),
    )
