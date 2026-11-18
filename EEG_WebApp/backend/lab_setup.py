"""Operator-selected LSL montage. Wire indices refer to the single selected outlet."""
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Wire(BaseModel):
    name: str = Field(max_length=64)
    kind: Literal["EEG", "skip"]
    unit: Literal["uV", "mV", "V"]


class Layout(BaseModel):
    uid: str = Field(min_length=1, max_length=256)
    wires: list[Wire] = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_names(self):
        names = set()
        for w in self.wires:
            if w.kind == "skip":
                continue
            w.name = w.name.strip()
            if not w.name or w.name.casefold() in names | {"timestamp_s"}:
                raise ValueError("기록 채널의 이름을 비어 있지 않게, 서로 다르게 지정하세요.")
            names.add(w.name.casefold())
        if not any(w.kind == "EEG" for w in self.wires):
            raise ValueError("EEG 채널을 하나 이상 지정하세요.")
        return self


def streams():
    """배선 화면 장비 목록: USB로 직접 연결된 g.USBamp + 송출 중인 LSL 스트림. 하나라도 찾으면 돌려준다."""
    found, errors = [], []
    for name, search in (("g.USBamp", _gusbamp), ("LSL", _lsl)):
        try:
            found += search()
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    if not found and len(errors) == 2:
        raise RuntimeError(" / ".join(errors))
    return found


def _gusbamp():
    from .eeg.gusbamp_source import devices
    return devices()


def _lsl():
    import pylsl
    results = []
    for info in pylsl.resolve_streams(wait_time=1):
        if not info.nominal_srate() or info.channel_format() == pylsl.cf_string:
            continue
        inlet = pylsl.StreamInlet(info, recover=False)
        try:
            full = inlet.info(timeout=2)
        except (RuntimeError, TimeoutError):
            continue
        node = full.desc().child("channels").child("channel")
        wires = []
        for _ in range(info.channel_count()):
            wires.append({key: node.child_value(key) or "" for key in ("label", "type", "unit")})
            node = node.next_sibling("channel")
        results.append(dict(uid=info.uid(), name=info.name(), host=info.hostname(),
                            fs=info.nominal_srate(), wires=wires))
    return results

