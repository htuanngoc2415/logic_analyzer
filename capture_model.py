from dataclasses import dataclass, field
from datetime import datetime

import numpy as np


@dataclass
class Capture:
    sample_rate: int
    num_samples: int
    channels: int
    raw_samples: np.ndarray
    trigger_type: int = 0
    trigger_channel: int = 0
    pattern_mask: int = 0
    pattern_value: int = 0
    triggered: bool = False
    capture_time: datetime = field(default_factory=datetime.now)
    measurements: dict = field(default_factory=dict)
    decoded_uart: list = field(default_factory=list)
    decoded_i2c: list = field(default_factory=list)
    decoded_spi: list = field(default_factory=list)
    decoded_onewire: list = field(default_factory=list)

    def channel_bits(self, channel: int) -> np.ndarray:
        if channel < 0 or channel >= self.channels:
            raise ValueError(f"Channel {channel} is outside capture range")
        return ((self.raw_samples >> channel) & 1).astype(np.int8)

    @property
    def duration(self) -> float:
        if self.sample_rate <= 0:
            return 0.0
        return self.num_samples / self.sample_rate
