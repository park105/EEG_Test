"""FastAPI 서버: REST(설문·평정·추론) + WebSocket(실시간 신호·품질, 시점 마커).

실행:  python -m uvicorn backend.main:app --port 8000   →  http://localhost:8000
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import threading
from contextlib import asynccontextmanager
from typing import Optional

import numpy as np
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import inference, upload
from .demo import make_demo
from .config import settings
from .eeg import create_source
from .eeg.base import Acquisition
from .quality import channel_quality
from .session import Session


def load_json(name: str):
    return json.loads((settings.stimuli_dir / name).read_text(encoding="utf-8"))


STIMULI: list[dict] = load_json("manifest.json")["stimuli"]
SURVEY: list[dict] = load_json("survey.json")["items"]


class State:
    acquisition: Optional[Acquisition] = None
    session: Optional[Session] = None
    lock = threading.Lock()


state = State()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    if state.session:
        state.session.stop_recording()
    if state.acquisition:
        state.acquisition.stop()


app = FastAPI(title="EEG 선호도 측정", lifespan=lifespan)


CONNECT_TIMEOUT_S = 5.0   # 연결 후 이 시간 안에 첫 샘플이 안 들어오면 연결 실패로 본다
GATED_MARKERS = {"baseline_start", "fixation_onset"}  # 데이터가 안 들어오는 동안에는 시작할 수 없는 구간


def source_info() -> dict:
    """connected = 장비 객체만 만든 것이 아니라 실제 샘플이 최근까지 들어오고 있다."""
    acq = state.acquisition
    if not acq:
        return {"kind": settings.source, "connected": False, "streaming": False}
    ok = acq.streaming()
    return {**acq.source.info(), "connected": ok, "streaming": ok,
            "error": acq.error or (None if ok else "장비에서 데이터가 들어오지 않아요.")}


def require_streaming() -> None:
    if not state.acquisition or not state.acquisition.streaming():
        raise HTTPException(409, "장비가 연결되지 않았거나 데이터가 들어오지 않아요. 연결을 확인한 뒤 다시 시도하세요.")


def open_acquisition() -> Acquisition:
    """소스를 열고 첫 샘플이 실제로 들어올 때까지 기다린다. 안 들어오면 닫고 실패로 돌려준다."""
    try:
        source = create_source(settings)
        if hasattr(source, "set_stimuli"):
            source.set_stimuli(STIMULI)
        acq = Acquisition(source)
        acq.start()
    except Exception as exc:
        raise HTTPException(503, f"장비 연결 실패: {type(exc).__name__}: {exc}")
    if not acq.wait_for_data(CONNECT_TIMEOUT_S):
        reason = acq.error or f"{CONNECT_TIMEOUT_S:g}초 동안 데이터가 한 샘플도 들어오지 않았어요."
        acq.stop()
        raise HTTPException(503, f"장비 연결 실패: {reason} 전원·블루투스/동글·포트 설정을 확인하세요.")
    return acq


def require_session(session_id: str) -> Session:
    if not state.session or state.session.id != session_id:
        raise HTTPException(404, "활성 세션이 아닙니다. 처음부터 다시 시작하세요.")
    return state.session


def stamp() -> float:
    """EEG 샘플과 같은 시계의 현재 시각."""
    if not state.acquisition:
        raise HTTPException(409, "장비가 연결되지 않았습니다.")
    return state.acquisition.source.now()


# ---------------- 설정 ----------------
@app.get("/api/config")
def get_config():
    t = settings.timing
    return {"timing": {"baseline_s": t.baseline_s, "fixation_s": t.fixation_s,
                       "stimulus_s": t.stimulus_s, "recovery_s": t.recovery_s},
            "survey": SURVEY, "n_stimuli": len(STIMULI), "device": source_info()}


# ---------------- ② 장비 ----------------
@app.post("/api/device/connect")
def connect_device():
    with state.lock:
        if state.acquisition and state.acquisition.streaming():
            return source_info()
        return _reopen()


def _reopen() -> dict:
    """(다시) 연결. 기록 중이던 세션이 있으면 새 연결에 이어 붙인다. state.lock 안에서 부른다."""
    old, session = state.acquisition, state.session
    if old:
        if session:
            old.remove_sink(session.write_samples)
        old.stop()
        state.acquisition = None
    acq = open_acquisition()
    state.acquisition = acq
    if session and session.recording:
        acq.add_sink(session.write_samples)
        session.add_marker(acq.source.now(), "device_reconnected")
    return source_info()


@app.post("/api/device/reconnect")
def reconnect_device():
    with state.lock:
        return _reopen()


@app.post("/api/device/simulate-drop")
def simulate_drop():
    """개발용(모의 EEG 전용): 장비가 끊긴 상황을 만들어 화면이 막히는지 확인한다."""
    acq = state.acquisition
    if not acq or not hasattr(acq.source, "dropped"):
        raise HTTPException(404, "모의 EEG로 연결돼 있을 때만 쓸 수 있습니다.")
    acq.source.dropped = True
    return {"dropped": True}


@app.post("/api/device/disconnect")
def disconnect_device():
    with state.lock:
        if state.session and state.session.recording:
            raise HTTPException(409, "기록 중에는 연결을 끊을 수 없습니다.")
        if state.acquisition:
            state.acquisition.stop()
            state.acquisition = None
    return source_info()


@app.get("/api/device")
def device_status():
    return source_info()


# ---------------- 세션 ----------------
class NewSession(BaseModel):
    participant_id: str = Field(min_length=1, max_length=64)


@app.post("/api/sessions")
def create_session(body: NewSession):
    if state.session and state.session.recording:
        state.session.stop_recording()
    info = source_info()
    t = settings.timing
    session = Session.create(settings.data_dir, body.participant_id, STIMULI, info,
                             {"baseline_s": t.baseline_s, "fixation_s": t.fixation_s,
                              "stimulus_s": t.stimulus_s, "recovery_s": t.recovery_s},
                             settings.order_seed)
    state.session = session
    by_id = {s["id"]: s for s in STIMULI}
    return {"session_id": session.id,
            "trials": [{"trial_index": i, "stimulus_id": sid, "type": by_id[sid].get("type", "image"),
                        "src": by_id[sid]["src"]} for i, sid in enumerate(session.meta["order"])]}


@app.post("/api/sessions/{session_id}/survey")
def save_survey(session_id: str, answers: dict):
    valid = {i["id"] for i in SURVEY}
    clean = {k: int(v) for k, v in answers.items() if k in valid and 1 <= int(v) <= 9}
    if state.session and state.session.id == session_id:
        session = state.session
    else:
        session = Session.load(upload_dir(session_id))  # 업로드 모드 세션은 장비와 상관없이 디스크에서 연다
    session.save_survey(clean)
    return {"saved": len(clean)}


@app.post("/api/sessions/{session_id}/recording/start")
def start_recording(session_id: str):
    session = require_session(session_id)
    require_streaming()
    src = state.acquisition.source
    session.meta["source"] = src.info()
    fresh = not session.recording
    session.start_recording(src.channels)
    state.acquisition.add_sink(session.write_samples)
    if fresh:
        session.add_marker(src.now(), "recording_start")
    return {"recording": True}


@app.get("/api/sessions/{session_id}/progress")
def session_progress(session_id: str):
    """새로고침 뒤 이어하기용: 이미 평정까지 끝난 시행과 기준선 완료 여부."""
    if not state.session or state.session.id != session_id:
        return {"active": False}
    import csv as _csv
    s = state.session
    with (s.dir / "ratings.csv").open(encoding="utf-8") as f:
        done = sorted({int(r["trial_index"]) for r in _csv.DictReader(f)})
    with (s.dir / "markers.csv").open(encoding="utf-8") as f:
        names = {r["name"] for r in _csv.DictReader(f)}
    return {"active": True, "recording": s.recording, "status": s.meta.get("status"),
            "survey_done": (s.dir / "survey.json").exists(),
            "baseline_done": "baseline_end" in names, "completed_trials": done,
            "device": source_info()}


class Marker(BaseModel):
    name: str
    trial_index: Optional[int] = None
    stimulus_id: Optional[str] = None
    client_ts_ms: Optional[float] = None


def record_marker(session: Session, m: Marker) -> float:
    if m.name in GATED_MARKERS:
        require_streaming()
    ts = stamp()
    session.add_marker(ts, m.name, m.trial_index, m.stimulus_id, m.client_ts_ms)
    state.acquisition.source.on_marker(m.model_dump())
    return ts


@app.post("/api/sessions/{session_id}/markers")
def post_marker(session_id: str, m: Marker):
    """WebSocket이 끊겼을 때의 예비 경로. 평소에는 WebSocket으로 보낸다."""
    return {"server_ts": record_marker(require_session(session_id), m)}


class Rating(BaseModel):
    trial_index: int
    stimulus_id: str
    liking: int = Field(ge=1, le=9)
    seen_before: bool


@app.post("/api/sessions/{session_id}/ratings")
def post_rating(session_id: str, r: Rating):
    # 평정은 장비가 끊긴 순간에도 잃지 않는다(시각만 비워 둔다)
    ts = state.acquisition.source.now() if state.acquisition else float("nan")
    require_session(session_id).add_rating(r.trial_index, r.stimulus_id, r.liking, r.seen_before, ts)
    return {"ok": True}


# ---------------- ④ 추론 / ⑤ 결과 ----------------
@app.post("/api/sessions/{session_id}/finish")
async def finish(session_id: str):
    session = require_session(session_id)
    if state.acquisition:  # 장비가 끊긴 채로 끝내도 지금까지의 기록으로 결과를 낸다
        session.add_marker(state.acquisition.source.now(), "recording_end")
        state.acquisition.remove_sink(session.write_samples)
    session.stop_recording()
    session.meta["status"] = "finished"
    session.save_meta()
    try:
        result = await asyncio.to_thread(inference.run, session.dir, STIMULI, SURVEY, settings.feature_channels)
    except Exception as exc:
        raise HTTPException(500, f"추론 실패: {exc}")
    return result


@app.get("/api/sessions/{session_id}/results")
def get_results(session_id: str):
    if not session_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(400, "잘못된 세션 ID")
    path = settings.data_dir / session_id / "results.json"
    if not path.is_file():
        raise HTTPException(404, "결과가 없습니다.")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------- 파일 업로드 모드 ----------------
UPLOAD_KINDS = {"eeg", "events", "ratings"}
MAX_UPLOAD_BYTES = 1 << 30  # 1 GB


def upload_dir(session_id: str):
    if not re.fullmatch(r"\d{8}-\d{6}_[A-Za-z0-9_-]+", session_id):
        raise HTTPException(400, "잘못된 세션 ID")
    d = settings.data_dir / session_id
    meta = d / "session.json"
    if not meta.is_file() or json.loads(meta.read_text(encoding="utf-8")).get("mode") != "upload":
        raise HTTPException(404, "업로드 세션이 없습니다. 처음부터 다시 시작하세요.")
    return d


def preview(d, kind: str, path=None) -> dict:
    path = path or d / f"raw_{kind}.csv"
    if kind == "eeg":
        return upload.inspect_eeg(path, settings.feature_channels)
    if kind == "events":
        return upload.inspect_events(path, {s["id"] for s in STIMULI})
    df = upload.read_table(path)
    return {"rows": int(len(df)), "columns": list(df.columns), "warnings": []}


def set_file_meta(d, **files) -> None:
    session = Session.load(d)
    session.meta.setdefault("files", {}).update(files)
    if "eeg" in files:
        session.meta["demo"] = False  # 직접 올린 EEG면 합성 데이터 표시를 뗀다
    session.save_meta()


@app.post("/api/uploads")
def create_upload(body: NewSession):
    t = settings.timing
    session = Session.create_upload(settings.data_dir, body.participant_id,
                                    {"fixation_s": t.fixation_s, "stimulus_s": t.stimulus_s})
    return {"session_id": session.id}


@app.put("/api/uploads/{session_id}/files/{kind}")
async def put_upload_file(session_id: str, kind: str, request: Request, name: str = ""):
    """파일 본문을 그대로 받는다(멀티파트 불필요). 받은 즉시 형식을 읽어 미리보기를 돌려준다."""
    if kind not in UPLOAD_KINDS:
        raise HTTPException(400, "kind는 eeg / events / ratings 중 하나")
    d = upload_dir(session_id)
    path, size = d / f"raw_{kind}.part", 0  # 형식 검사를 통과해야 기존 파일을 바꾼다
    with path.open("wb") as f:
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                f.close(); path.unlink(missing_ok=True)
                raise HTTPException(413, "파일이 너무 커요(최대 1 GB).")
            f.write(chunk)
    try:
        info = await asyncio.to_thread(preview, d, kind, path)
    except upload.UploadError as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(422, str(exc))
    path.replace(d / f"raw_{kind}.csv")
    set_file_meta(d, **{kind: name[:200] or f"{kind}.csv"})
    return {"kind": kind, "name": name, "bytes": size, **info}


@app.post("/api/uploads/{session_id}/demo")
async def use_demo(session_id: str):
    """예시(모의) 파일 한 벌을 이 업로드 세션에 넣는다."""
    d = upload_dir(session_id)
    demo = await asyncio.to_thread(make_demo)
    for kind in ("eeg", "events"):
        shutil.copyfile(demo / f"{kind}.csv", d / f"raw_{kind}.csv")
    (d / "raw_ratings.csv").unlink(missing_ok=True)
    session = Session.load(d)
    session.meta["demo"] = True
    session.meta["files"] = {"eeg": "예시 eeg.csv", "events": "예시 events.csv"}
    session.save_meta()
    return {k: {"kind": k, "name": session.meta["files"][k], **await asyncio.to_thread(preview, d, k)}
            for k in ("eeg", "events")}


class UploadOptions(BaseModel):
    fs: Optional[float] = Field(default=None, gt=0, le=100000)
    unit: str = "uV"
    rating_scale: str = "auto"  # auto | 1-9 | 1-5


@app.post("/api/uploads/{session_id}/run")
async def run_upload(session_id: str, opts: UploadOptions):
    d = upload_dir(session_id)
    t = settings.timing
    try:
        prep = await asyncio.to_thread(upload.prepare, d, fs=opts.fs, unit=opts.unit, rating_scale=opts.rating_scale,
                                       feature_channels=settings.feature_channels,
                                       fixation_s=t.fixation_s, stimulus_s=t.stimulus_s)
        result = await asyncio.to_thread(inference.run, d, STIMULI, SURVEY, settings.feature_channels)
    except upload.UploadError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"추론 실패: {exc}")
    session = Session.load(d)
    session.meta["status"] = "finished"
    session.save_meta()
    return {**result, "upload": prep}


@app.get("/api/demo/{name}")
def demo_file(name: str):
    if name not in {"eeg.csv", "events.csv"}:
        raise HTTPException(404, "없는 파일")
    return FileResponse(make_demo() / name, filename=f"example_{name}", media_type="text/csv")


# ---------------- WebSocket ----------------
@app.websocket("/ws")
async def ws(websocket: WebSocket):
    """서버 → 화면: 실시간 파형(4 Hz)·채널 품질(1 Hz). 화면 → 서버: 시점 마커."""
    await websocket.accept()
    send_lock = asyncio.Lock()

    async def send(payload):
        async with send_lock:
            await websocket.send_json(payload)

    async def sender():
        tick = 0
        while True:
            acq = state.acquisition
            if acq and acq.buffer is not None:
                src = acq.source
                t, x = acq.buffer.last(int(4 * src.fs))
                if len(t):
                    step = max(1, int(src.fs // 50))  # 화면용 약 50 Hz로 줄임
                    disp = x[::step] - np.median(x, axis=0)
                    await send({"type": "signal", "channels": src.channels, "streaming": acq.streaming(),
                                               "fs": src.fs / step, "data": np.round(disp.T, 1).tolist()})
                if tick % 4 == 0:
                    t2, x2 = acq.buffer.last(int(2 * src.fs))
                    live = acq.streaming()
                    await send({"type": "quality", "streaming": live,
                                "error": acq.error or (None if live else "장비에서 데이터가 들어오지 않아요."),
                                "channels": channel_quality(x2, src.fs, src.channels)})
            elif tick % 4 == 0:
                await send({"type": "quality", "streaming": False, "error": None, "channels": []})
            tick += 1
            await asyncio.sleep(0.25)

    task = asyncio.create_task(sender())
    try:
        while True:
            msg = await websocket.receive_json()
            if msg.get("type") == "marker" and state.session and state.acquisition:
                m = Marker(**{k: msg.get(k) for k in ("name", "trial_index", "stimulus_id", "client_ts_ms")})
                try:
                    ts = record_marker(state.session, m)
                except HTTPException as exc:  # 데이터가 안 들어오는 동안의 시작 마커는 받지 않는다
                    await send({"type": "marker_rejected", "name": m.name,
                                "trial_index": m.trial_index, "reason": exc.detail})
                    continue
                await send({"type": "marker_ack", "name": m.name,
                                           "trial_index": m.trial_index, "server_ts": ts})
    except WebSocketDisconnect:
        pass
    finally:
        task.cancel()


# ---------------- 정적 파일 ----------------
app.mount("/stimuli", StaticFiles(directory=settings.stimuli_dir), name="stimuli")
app.mount("/static", StaticFiles(directory=settings.frontend_dir), name="static")


@app.get("/")
def index():
    return FileResponse(settings.frontend_dir / "index.html")
