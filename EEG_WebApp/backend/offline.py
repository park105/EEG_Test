"""Device-free presentation records and explicit two-clock EEG alignment."""
import asyncio
import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, FiniteFloat
from typing import Literal

from .config import settings
from .session import Session
from . import field_analysis, inference, upload

router = APIRouter(prefix="/api/offline")
lock = threading.Lock()


def directory(sid):
    if not sid.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(400, "잘못된 기록 ID")
    path = settings.data_dir / sid
    if not (path / "offline.json").exists():
        raise HTTPException(404, "독립 측정 기록이 없습니다.")
    return path


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


class Start(BaseModel):
    participant: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    stimuli: Literal["portraits", "original"] = "portraits"
    quick: bool = False


@router.post("")
def create(body: Start):
    filename = "portraits.json" if body.stimuli == "portraits" else "manifest.json"
    photos = read(settings.stimuli_dir / filename)["stimuli"]
    timing = {"baseline_s": 10 if body.quick else 60, "fixation_s": 3, "stimulus_s": 4, "recovery_s": 3}
    s = Session.create(settings.data_dir, body.participant,
                       photos, {"kind": "external_pending", "synthetic": False}, timing)
    by_id = {p["id"]: p for p in photos}
    order = s.meta["order"][:4] if body.quick else s.meta["order"]
    meta = {"session_id": s.id, "participant": body.participant, "timing": timing,
            "trials": [by_id[k] for k in order], "status": "created",
            "created_utc": datetime.now(timezone.utc).isoformat()}
    field_analysis.write_json(s.dir / "offline.json", meta)
    return meta


@router.get("")
def sessions():
    return sorted([p.parent.name for p in settings.data_dir.glob("*/offline.json")], reverse=True)


@router.get("/{sid}")
def detail(sid: str):
    d = directory(sid)
    meta = read(d / "offline.json")
    meta["records"] = [read(p) for p in sorted(d.glob("offline_record_*.json"))]
    return meta


class Event(BaseModel):
    name: Literal["recording_start", "baseline_start", "baseline_end", "fixation_onset",
                  "stimulus_onset", "stimulus_offset", "rating_shown", "pause_start",
                  "pause_end", "sync", "recording_end"]
    elapsed_s: FiniteFloat = Field(ge=0)
    epoch_ms: FiniteFloat = Field(gt=0)
    trial_index: int | None = Field(default=None, ge=0)


class Record(BaseModel):
    events: list[Event] = Field(min_length=1, max_length=2000)
    capture: field_analysis.TrialCapture | None = None


@router.put("/{sid}/records/{number}")
def save_record(sid: str, number: int, body: Record):
    d = directory(sid)
    if not 0 <= number <= 100:
        raise HTTPException(422, "기록 번호 오류")
    with lock:
        meta = read(d / "offline.json")
        payload = body.model_dump()
        path = d / f"offline_record_{number:03d}.json"
        if path.exists():
            if read(path) == payload:
                return {"saved": True}
            raise HTTPException(409, "이미 저장된 기록과 다릅니다.")
        if meta["status"] == "finished":
            raise HTTPException(409, "종료된 기록입니다.")
        if body.capture:
            idx = number - 1
            if not 0 <= idx < len(meta["trials"]) or body.capture.stimulus_id != meta["trials"][idx]["id"]:
                raise HTTPException(422, "사진 ID와 시행 번호를 확인하세요.")
            if body.capture.live_liking is None:
                raise HTTPException(422, "현장 점수가 필요합니다.")
            phases = [e for e in body.events if e.name in {"fixation_onset","stimulus_onset","stimulus_offset","rating_shown"}]
            if [e.name for e in phases] != ["fixation_onset","stimulus_onset","stimulus_offset","rating_shown"] or any(e.trial_index != idx for e in phases):
                raise HTTPException(422, "사진의 고정점·등장·종료·평정 마커가 필요합니다.")
        prior = [read(p) for p in sorted(d.glob("offline_record_*.json"))]
        events = [e for r in prior for e in r["events"]] + payload["events"]
        times = [e["elapsed_s"] for e in events]
        if any(b < a for a, b in zip(times, times[1:])):
            raise HTTPException(422, "마커 시각 순서 오류")
        field_analysis.write_json(path, payload)
        meta["status"] = "finished" if body.events[-1].name == "recording_end" else "recording"
        field_analysis.write_json(d / "offline.json", meta)
    return {"saved": True}


@router.get("/{sid}/download")
def download(sid: str):
    d = directory(sid)
    from fastapi.responses import JSONResponse
    return JSONResponse(detail(sid), headers={"Content-Disposition": f'attachment; filename="{sid}_record.json"'})


@router.post("/{sid}/finish-partial")
def finish_partial(sid: str):
    d = directory(sid)
    with lock:
        meta = read(d / "offline.json")
        meta["status"] = "finished"
        meta["ended_early"] = True
        field_analysis.write_json(d / "offline.json", meta)
    return {"saved": True}


class Align(BaseModel):
    file_id: str
    fs: FiniteFloat = Field(gt=90, le=10000)
    unit: Literal["uV", "mV", "V"] = "uV"
    channels: dict[str, str]
    time_column: str = ""
    time_unit: Literal["s", "ms"] = "s"
    web_anchor_s: FiniteFloat = Field(ge=0)
    eeg_anchor_s: FiniteFloat
    web_anchor2_s: FiniteFloat | None = None
    eeg_anchor2_s: FiniteFloat | None = None
    method: str = Field(min_length=3, max_length=500)


@router.put("/{sid}/eeg")
async def receive_eeg(sid: str, request: Request):
    d = directory(sid)
    key = uuid.uuid4().hex
    path = d / ("external_"+key+".csv")
    size = 0
    try:
        with path.open("wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > 512*1024*1024:
                    raise HTTPException(413, "최대 512 MB입니다.")
                f.write(chunk)
        frame = await asyncio.to_thread(upload.read_table, path)
        return {"file_id": key, "columns": list(frame.columns), "rows": len(frame)}
    except Exception:
        path.unlink(missing_ok=True)
        raise


def analyze(sid, body):
    d = directory(sid)
    if not body.file_id.isalnum():
        raise ValueError("파일 ID 오류")
    raw = d / ("external_"+body.file_id+".csv")
    frame = upload.read_table(raw)
    if set(body.channels) != {"O1", "Oz", "O2", "Pz"} or len(set(body.channels.values())) != 4:
        raise ValueError("서로 다른 입력 열을 O1·Oz·O2·Pz에 배정하세요.")
    values = frame[list(body.channels.values())].to_numpy(float)
    if not np.isfinite(values).all():
        raise ValueError("EEG에 빈값 또는 비유한 값이 있습니다.")
    times = frame[body.time_column].to_numpy(float) if body.time_column else np.arange(len(frame))/body.fs
    if body.time_column and body.time_unit == "ms":
        times /= 1000
    if not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        raise ValueError("EEG 시각은 유한하고 증가해야 합니다.")
    both = (body.web_anchor2_s is not None, body.eeg_anchor2_s is not None)
    if both[0] != both[1]:
        raise ValueError("두 번째 기준점의 두 시각을 모두 입력하세요.")
    scale = 1.0
    if both[0]:
        if body.web_anchor2_s <= body.web_anchor_s or body.eeg_anchor2_s <= body.eeg_anchor_s:
            raise ValueError("두 번째 기준점은 첫 번째보다 뒤여야 합니다.")
        scale = (body.eeg_anchor2_s-body.eeg_anchor_s)/(body.web_anchor2_s-body.web_anchor_s)
    records = detail(sid)["records"]
    meta = read(d / "offline.json")
    if meta["status"] != "finished":
        raise ValueError("사진 기록을 종료한 뒤 분석하세요.")
    events = [e for r in records for e in r["events"]]
    if not events:
        raise ValueError("마커가 없습니다.")
    mapping = lambda t: body.eeg_anchor_s + scale*(t-body.web_anchor_s)
    trial_events = [e for e in events if e["name"] in {"fixation_onset","stimulus_onset","stimulus_offset"}]
    if not trial_events or min(mapping(e["elapsed_s"]) for e in trial_events) < times[0] or max(mapping(e["elapsed_s"]) for e in trial_events) > times[-1]+1/body.fs:
        raise ValueError("정렬된 사진 구간이 EEG 기록 범위를 벗어납니다. 기준점과 시간 단위를 확인하세요.")
    target = settings.data_dir / (sid+"_aligned_"+uuid.uuid4().hex[:8])
    target.mkdir()
    try:
        s = Session(target, {"session_id": target.name, "participant_id": meta["participant"],
                             "source": {"kind":"external_csv", "channels":list(body.channels), "fs":body.fs, "synthetic":False},
                             "timing":meta["timing"], "status":"finished", "mode":"device"})
        s.save_meta()
        eeg = pd.DataFrame(values*{"uV":1,"mV":1000,"V":1e6}[body.unit], columns=list(body.channels))
        eeg.insert(0, "timestamp_s", times)
        eeg.to_csv(target/"eeg.csv", index=False)
        markers = [{"server_ts":mapping(e["elapsed_s"]), "name":e["name"], "trial_index":e["trial_index"],
                    "stimulus_id":meta["trials"][e["trial_index"]]["id"] if e["trial_index"] is not None else "",
                    "client_ts_ms":e["elapsed_s"]*1000} for e in events]
        pd.DataFrame(markers).to_csv(target/"markers.csv", index=False)
        pd.DataFrame(columns=["trial_index","stimulus_id","liking","seen_before","server_ts"]).to_csv(target/"ratings.csv",index=False)
        for r in records:
            if r["capture"]:
                capture = r["capture"].copy()
                idx = next(i for i,p in enumerate(meta["trials"]) if p["id"] == capture["stimulus_id"])
                liking = capture.pop("live_liking")
                field_analysis.write_json(target/f"capture_{idx}.json",capture)
                field_analysis.write_json(target/f"response_{idx}.json",{"stimulus_id":capture["stimulus_id"],"liking":liking})
        field_analysis.write_json(target/"alignment.json", {**body.model_dump(), "scale":scale, "source_session":sid,
                                   "raw_sha256":hashlib.sha256(raw.read_bytes()).hexdigest(),
                                   "uncertainty":"User supplied anchors; residual timing uncertainty is not measured."})
        inference.run(target,meta["trials"],[],list(body.channels))
        return {"session_id":target.name, "scale":scale}
    except Exception:
        # Keep partial derived data for diagnosis; source files are immutable.
        (target/"results.json").unlink(missing_ok=True)
        raise


@router.post("/{sid}/align")
async def align(sid: str, body: Align):
    try:
        return await asyncio.to_thread(analyze, sid, body)
    except (ValueError, KeyError, OSError, upload.UploadError) as exc:
        raise HTTPException(422, str(exc))

