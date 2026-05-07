import numpy as np

class UARTDecoder:
    def __init__(self, samples_per_bit, data_bits=8):
        self.samples_per_bit = samples_per_bit
        self.data_bits = data_bits

    def decode(self, data):
        """
        data: 1D numpy array of 0s and 1s
        Returns a list of dicts: {'start': idx, 'end': idx, 'char': str}
        """
        results = []
        n = len(data)
        i = 0
        while i < n - int(self.samples_per_bit * 10):
            # Find falling edge (idle is 1, start bit is 0)
            if data[i] == 1 and data[i+1] == 0:
                start_bit_idx = i + 1
                # sample in the middle of start bit
                mid_start = start_bit_idx + self.samples_per_bit / 2.0
                
                if int(mid_start) < n and data[int(mid_start)] == 0:
                    # Valid start bit
                    byte_val = 0
                    curr_idx = mid_start
                    
                    # Read data bits
                    valid = True
                    for b in range(self.data_bits):
                        curr_idx += self.samples_per_bit
                        if int(curr_idx) >= n:
                            valid = False
                            break
                        bit = data[int(curr_idx)]
                        byte_val |= (bit << b)
                        
                    if valid:
                        # Stop bit
                        curr_idx += self.samples_per_bit
                        if int(curr_idx) < n:
                            char_str = chr(byte_val) if 32 <= byte_val <= 126 else f"\\x{byte_val:02X}"
                            results.append({
                                'start': start_bit_idx,
                                'end': int(curr_idx),
                                'char': char_str
                            })
                            i = int(curr_idx)
                            continue
            i += 1
        return results

class SPIDecoder:
    def __init__(self, cpol=0, cpha=0):
        self.cpol = cpol
        self.cpha = cpha

    def decode(self, sck, mosi, miso, cs):
        """
        sck, mosi, miso, cs: 1D numpy arrays of same length
        Returns a list of dicts: {'start': idx, 'end': idx, 'mosi': str, 'miso': str}
        """
        results = []
        n = len(sck)
        i = 1
        
        mosi_byte = 0
        miso_byte = 0
        bit_count = 0
        start_idx = 0
        
        while i < n:
            if cs is not None and cs[i] == 1:
                bit_count = 0
                i += 1
                continue
                
            # Look for rising edge (if cpol=0, cpha=0)
            if sck[i-1] == 0 and sck[i] == 1:
                if bit_count == 0:
                    start_idx = i
                    
                mosi_bit = mosi[i] if mosi is not None else 0
                miso_bit = miso[i] if miso is not None else 0
                
                # MSB first
                mosi_byte = (mosi_byte << 1) | mosi_bit
                miso_byte = (miso_byte << 1) | miso_bit
                
                bit_count += 1
                if bit_count == 8:
                    results.append({
                        'start': start_idx,
                        'end': i,
                        'mosi': f"{mosi_byte:02X}",
                        'miso': f"{miso_byte:02X}"
                    })
                    bit_count = 0
                    mosi_byte = 0
                    miso_byte = 0
            i += 1
        return results
