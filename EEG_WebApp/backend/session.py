"""세션 저장: 한 참가자의 한 번 측정 = data/sessions/<session_id>/ 폴더 하나.

  session.json  참가자·소스·자극 순서·타이밍
  survey.json   ① 설문 응답
  eeg.csv       timestamp_s + 채널(uV). 기록 중 계속 추가 저장(중단돼도 남음)
  markers.csv   server_ts(EEG와 같은 시계), name, trial_index, stimulus_id, client_ts_ms
  ratings.csv   ③ 시행별 좋아요 1–9, 본 적 있음
  features.csv / results.json   ④ 추론 결과
"""
from __future__ import annotations

import csv
import json
import random
import re
import threading
from datetime import datetime
from pathlib import Path

import numpy as np

MARKER_FIELDS = ["server_ts", "name", "trial_index", "stimulus_id", "client_ts_ms"]
RATING_FIELDS = ["trial_index", "stimulus_id", "liking", "seen_before", "server_ts"]


class Session:
    def __init__(self, directory: Path, meta: dict) -> None:
        self.dir = directory
        self.meta = meta
        self.id = meta["session_id"]
        self._lock = threading.Lock()
        self._eeg_file = None
        self._eeg_writer = None
        self.recording = False

    # ---------- 생성/불러오기 ----------
    @classmethod
    def create(cls, root: Path, participant_id: str, stimuli: list[dict], source_info: dict,
               timing: dict, seed: str = "") -> "Session":
        pid = re.sub(r"[^A-Za-z0-9_-]", "", participant_id)[:32] or "P"
        sid = f"{datetime.now():%Y%m%d-%H%M%S}_{pid}"
        directory = Path(root) / sid
        directory.mkdir(parents=True, exist_ok=False)
        order_seed = int(seed) if seed else random.SystemRandom().randrange(1 << 30)
        order = [s["id"] for s in stimuli]
        random.Random(order_seed).shuffle(order)
        meta = {"session_id": sid, "participant_id": pid, "created": datetime.now().isoformat(timespec="seconds"),
                "source": source_info, "timing": timing, "order_seed": order_seed, "order": order,
                "status": "created"}
        session = cls(directory, meta)
        session.save_meta()
        for name, fields in [("markers.csv", MARKER_FIELDS), ("ratings.csv", RATING_FIELDS)]:
            with (directory / name).open("w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(fields)
        return session

    @classmethod
    def create_upload(cls, root: Path, participant_id: str, timing: dict) -> "Session":
        """파일 업로드 모드: 장비·자극 순서 없이 폴더와 session.json만 만든다(파일은 upload.py가 채움)."""
        pid = re.sub(r"[^A-Za-z0-9_-]", "", participant_id)[:32] or "P"
        sid = f"{datetime.now():%Y%m%d-%H%M%S}_{pid}_upload"
        directory = Path(root) / sid
        directory.mkdir(parents=True, exist_ok=False)
        meta = {"session_id": sid, "participant_id": pid, "created": datetime.now().isoformat(timespec="seconds"),
                "mode": "upload", "source": {"kind": "upload"}, "timing": timing, "files": {}, "status": "created"}
        session = cls(directory, meta)
        session.save_meta()
        return session

    @classmethod
    def load(cls, directory: Path) -> "Session":
        meta = json.loads((Path(directory) / "session.json").read_text(encoding="utf-8"))
        return cls(Path(directory), meta)

    def save_meta(self) -> None:
        (self.dir / "session.json").write_text(json.dumps(self.meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- ① 설문 ----------
    def save_survey(self, answers: dict) -> None:
        (self.dir / "survey.json").write_text(json.dumps(answers, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- EEG 기록 ----------
    def start_recording(self, channels: list[str]) -> None:
        with self._lock:
            if self.recording:
                return
            path = self.dir / "eeg.csv"
            resume = path.exists() and path.stat().st_size > 0  # 이어하기: 기존 기록을 지우지 않고 뒤에 붙인다
            self._eeg_file = path.open("a" if resume else "w", newline="", encoding="utf-8")
            self._eeg_writer = csv.writer(self._eeg_file)
            if not resume:
                self._eeg_writer.writerow(["timestamp_s", *channels])
            self.recording = True
            self.meta["status"] = "recording"
            self.save_meta()

    def record_health(self, info: dict) -> None:
        """Persist faults across transient recovery and reconnects."""
        with self._lock:
            previous = self.meta.get("recording_health", {})
            health = dict(previous)
            health["timing_fault"] = bool(previous.get("timing_fault") or info.get("acquisition_error") or info.get("transport_timing_ok") is False)
            health["max_clock_lag_ms"] = max(previous.get("max_clock_lag_ms", 0), abs(info.get("max_clock_lag_ms", 0)))
            if info.get("acquisition_error"):
                health["last_error"] = info["acquisition_error"]
            if info.get("synthetic"):
                self.meta["source"]["synthetic"] = True
            if health != previous:
                self.meta["recording_health"] = health
                self.save_meta()

    def write_samples(self, t: np.ndarray, x: np.ndarray) -> None:
        with self._lock:
            if not self.recording:
                return
            self._eeg_writer.writerows(
                [[f"{ti:.6f}", *(f"{v:.3f}" for v in row)] for ti, row in zip(t, x)])
            self._eeg_file.flush()

    def stop_recording(self) -> None:
        with self._lock:
            if self._eeg_file:
                self._eeg_file.close()
            self._eeg_file = self._eeg_writer = None
            self.recording = False

    # ---------- 마커/평정 ----------
    def add_marker(self, server_ts: float, name: str, trial_index=None, stimulus_id=None, client_ts_ms=None) -> None:
        with self._lock, (self.dir / "markers.csv").open("a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([f"{server_ts:.6f}", name,
                                    "" if trial_index is None else trial_index,
                                    stimulus_id or "", "" if client_ts_ms is None else client_ts_ms])

    def add_rating(self, trial_index: int, stimulus_id: str, liking: int, seen_before: bool, server_ts: float) -> None:
        with self._lock, (self.dir / "ratings.csv").open("a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([trial_index, stimulus_id, liking, int(seen_before), f"{server_ts:.6f}"])
