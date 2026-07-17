import numpy as np


def channel_bits(raw_samples, channel):
    return ((np.asarray(raw_samples, dtype=np.uint8) >> channel) & 1).astype(np.int8)


def decode_uart(bits, baud, sample_rate):
    bits = np.asarray(bits, dtype=np.int8)
    bit_time = sample_rate / baud
    if bit_time < 2:
        return []

    rows = []
    index = 1
    while index < len(bits):
        if bits[index - 1] == 1 and bits[index] == 0:
            start = index
            value = 0
            valid = True
            for bit in range(8):
                sample_index = index + int((bit + 1.5) * bit_time)
                if sample_index >= len(bits):
                    valid = False
                    break
                value |= (int(bits[sample_index]) & 1) << bit
            if not valid:
                break
            end = min(index + int(bit_time * 10), len(bits) - 1)
            rows.append({"start": int(start), "end": int(end), "value": int(value)})
            index += max(1, int(bit_time * 9.5))
        else:
            index += 1
    return rows


def decode_i2c(sda, scl, sample_rate=None):
    sda = np.asarray(sda, dtype=np.int8)
    scl = np.asarray(scl, dtype=np.int8)
    if len(sda) == 0:
        return []

    events = []
    prev_scl = int(scl[0])
    prev_sda = int(sda[0])
    in_frame = False
    bit_count = 0
    value = 0
    byte_start = 0

    for index in range(1, len(sda)):
        cur_scl = int(scl[index])
        cur_sda = int(sda[index])
        if prev_scl == 1 and cur_scl == 1 and cur_sda != prev_sda:
            if prev_sda == 1 and cur_sda == 0:
                events.append({"kind": "START", "start": index, "end": index, "value": None})
                in_frame = True
                bit_count = 0
                value = 0
            elif prev_sda == 0 and cur_sda == 1:
                events.append({"kind": "STOP", "start": index, "end": index, "value": None})
                in_frame = False
                bit_count = 0
            prev_scl = cur_scl
            prev_sda = cur_sda
            continue

        if prev_scl == 0 and cur_scl == 1 and in_frame:
            if bit_count == 0:
                byte_start = index
            if bit_count < 8:
                value = (value << 1) | cur_sda
                bit_count += 1
                if bit_count == 8:
                    events.append({"kind": "BYTE", "start": byte_start, "end": index, "value": int(value)})
            else:
                events.append({"kind": "ACK" if cur_sda == 0 else "NACK", "start": index, "end": index, "value": None})
                bit_count = 0
                value = 0

        prev_scl = cur_scl
        prev_sda = cur_sda

    return events


def decode_spi(mosi, sck, cs, sample_rate=None, miso=None, mode=0):
    mosi = np.asarray(mosi, dtype=np.int8)
    sck = np.asarray(sck, dtype=np.int8)
    cs = np.asarray(cs, dtype=np.int8)
    miso = None if miso is None else np.asarray(miso, dtype=np.int8)

    cpol = (mode >> 1) & 1
    cpha = mode & 1
    sample_rising = cpol == cpha
    prev_clk = int(sck[0]) if len(sck) else 0
    mosi_byte = 0
    miso_byte = 0
    bit_count = 0
    start = 0
    rows = []

    for index in range(len(sck)):
        if int(cs[index]) == 0:
            clk = int(sck[index])
            edge = (prev_clk == 0 and clk == 1) if sample_rising else (prev_clk == 1 and clk == 0)
            if edge:
                if bit_count == 0:
                    start = index
                mosi_byte = (mosi_byte << 1) | int(mosi[index])
                if miso is not None:
                    miso_byte = (miso_byte << 1) | int(miso[index])
                bit_count += 1
                if bit_count == 8:
                    rows.append(
                        {
                            "start": int(start),
                            "end": int(index),
                            "mosi": int(mosi_byte),
                            "miso": int(miso_byte) if miso is not None else None,
                        }
                    )
                    mosi_byte = 0
                    miso_byte = 0
                    bit_count = 0
            prev_clk = clk
        else:
            mosi_byte = 0
            miso_byte = 0
            bit_count = 0
            prev_clk = int(sck[index])
    return rows


def _bits_to_byte(bits):
    return sum((bit & 1) << index for index, bit in enumerate(bits))


def decode_onewire(dq, sample_rate):
    dq = np.asarray(dq, dtype=np.int8)
    if len(dq) < 2:
        return []

    us_per_sample = 1e6 / sample_rate
    falling = np.nonzero((dq[:-1] == 1) & (dq[1:] == 0))[0] + 1
    rising = np.nonzero((dq[:-1] == 0) & (dq[1:] == 1))[0] + 1
    events = []
    bits = []
    bit_start = None
    expect_presence = False

    for fall in falling:
        rising_after = rising[rising > fall]
        if len(rising_after) == 0:
            break
        rise = int(rising_after[0])
        low_us = (rise - fall) * us_per_sample
        if low_us > 400:
            if bits:
                events.append({"kind": "BYTE", "start": int(bit_start), "end": int(fall), "value": _bits_to_byte(bits)})
                bits = []
            events.append({"kind": "RESET", "start": int(fall), "end": rise, "value": None})
            expect_presence = True
        elif expect_presence:
            events.append({"kind": "PRESENCE", "start": int(fall), "end": rise, "value": None})
            expect_presence = False
        else:
            if not bits:
                bit_start = int(fall)
            bits.append(1 if low_us < 25 else 0)
            if len(bits) == 8:
                events.append({"kind": "BYTE", "start": int(bit_start), "end": rise, "value": _bits_to_byte(bits)})
                bits = []

    if bits:
        events.append({"kind": "BYTE", "start": int(bit_start), "end": int(falling[-1]), "value": _bits_to_byte(bits)})
    return events
