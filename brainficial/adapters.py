"""Vendor boundary: convert units and clock alignment before EEGLoader."""
from pathlib import Path
from typing import Protocol
import pandas as pd


class DeviceAdapter(Protocol):
    def export(self, destination: Path) -> Path:
        """Produce uniform timestamp_s (event clock) plus named uV channels."""
        ...


class CSVDeviceAdapter:
    def __init__(self, source, time_column, channel_map, time_scale=1.,
                 time_offset_s=0., voltage_scale_to_uv=1.):
        self.source = source
        self.time_column, self.channel_map = time_column, channel_map
        self.time_scale, self.time_offset_s = time_scale, time_offset_s
        self.voltage_scale_to_uv = voltage_scale_to_uv

    def export(self, destination):
        """event_time = vendor_time*time_scale + offset; caller measures mapping."""
        source = pd.read_csv(self.source)
        result = pd.DataFrame({"timestamp_s": source[self.time_column]*self.time_scale+self.time_offset_s})
        if len(set(self.channel_map.values())) != len(self.channel_map) or "timestamp_s" in self.channel_map.values():
            raise ValueError("Unique channel output names required")
        for vendor_name, name in self.channel_map.items():
            result[name] = source[vendor_name]*self.voltage_scale_to_uv
        result.to_csv(destination, index=False)
        return Path(destination)
