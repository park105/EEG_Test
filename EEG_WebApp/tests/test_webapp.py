"""python -m unittest discover -s tests -v"""
import os
os.environ.setdefault("EEG_SOURCE", "mock")  # 테스트는 모의 EEG로 돈다(앱 기본값은 장비 미선택 none)
import json
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from backend import inference
from backend.config import settings
from backend.eeg.mock import MockEEGSource
from backend.quality import channel_quality
from backend.session import Session

# 실제 PC에 학습된 DEAP 모델이 있어도 기본 테스트는 자리표시 모델 경로를 검사한다
settings.deap_model_path = Path(tempfile.gettempdir()) / "no_such_model.joblib"

STIMULI = json.loads((settings.stimuli_dir / "manifest.json").read_text(encoding="utf-8"))["stimuli"]
SURVEY = json.loads((settings.stimuli_dir / "survey.json").read_text(encoding="utf-8"))["items"]


def simulate_session(root: Path, survey: dict) -> Session:
    """모의 EEG로 한 세션을 실시간 대기 없이 빠르게 만든다."""
    src = MockEEGSource(settings.mock_channels, 250, seed=1)
    src.set_stimuli(STIMULI)
    s = Session.create(root, "TEST", STIMULI, src.info(), {}, seed="3")
    s.save_survey(survey)
    s.start_recording(src.channels)
    t = 0.0

    def run(seconds):
        nonlocal t
        ts = t + np.arange(int(seconds * src.fs)) / src.fs
        s.write_samples(ts, src._generate(ts))
        t = ts[-1] + 1 / src.fs

    def mark(name, i=None, sid=None):
        m = {"name": name, "trial_index": i, "stimulus_id": sid}
        s.add_marker(t, name, i, sid)
        src.on_marker(m)

    mark("baseline_start"); run(10); mark("baseline_end")
    by_id = {x["id"]: x for x in STIMULI}
    for i, sid in enumerate(s.meta["order"]):
        mark("fixation_onset", i, sid); run(3)
        mark("stimulus_onset", i, sid); run(4)
        mark("stimulus_offset", i, sid); run(3)
        cat = by_id[sid]["category"]
        liking = {"nature": 8, "animal": 7, "food": 4, "city": 2}[cat]
        s.add_rating(i, sid, liking, False, t)
    s.stop_recording()
    return s


class WebAppTests(unittest.TestCase):
    def test_offline_inference_end_to_end(self):
        survey = {"cat_nature": 9, "cat_city": 2, "cat_animal": 5, "cat_food": 8,
                  "tone_warm": 6, "tone_cool": 6, "state_sleepy": 3}
        with tempfile.TemporaryDirectory() as d:
            s = simulate_session(Path(d), survey)
            r = inference.run(s.dir, STIMULI, SURVEY, settings.feature_channels)
            self.assertEqual(r["n_trials"], len(STIMULI))
            self.assertEqual(r["label"], "EEG 기반 추정")
            self.assertTrue(r["synthetic"])
            self.assertEqual(r["model"]["name"], "personal_logistic")
            self.assertEqual(sum(r["agreement_counts"].values()), len(STIMULI))
            self.assertEqual(r["resting"]["status"], "ok")
            for it in r["items"]:
                if it["quality"] == "ok":
                    self.assertTrue(0 <= it["eeg_like_probability"] <= 1)
            self.assertTrue((s.dir / "results.json").is_file())
            print("\nfeature backend:", r["model"]["feature_backend"],
                  "| quality:", r["quality_counts"], "| agreement:", r["agreement_counts"],
                  "| acc:", r["model"].get("balanced_accuracy_vs_rating"))

    def test_baseline_model_when_too_few_labels(self):
        with tempfile.TemporaryDirectory() as d:
            s = simulate_session(Path(d), {})
            ratings = pd.read_csv(s.dir / "ratings.csv")
            ratings["liking"] = 5  # 전부 중립 → 개인 보정 불가
            ratings.to_csv(s.dir / "ratings.csv", index=False)
            r = inference.run(s.dir, STIMULI, SURVEY, settings.feature_channels)
            self.assertEqual(r["model"]["name"], "frontal_asymmetry_baseline")
            self.assertEqual(r["agreement_counts"]["undecided"], len(STIMULI))  # 설문 없음

    def test_quality_flags(self):
        fs, n = 250, 500
        x = np.random.default_rng(0).normal(0, 5, (n, 3))
        x[:, 1] = 0.0                      # 평탄
        x[:, 2] += 300 * (np.arange(n) == 10)  # 큰 스파이크
        q = {c["channel"]: c["status"] for c in channel_quality(x, fs, ["A", "B", "C"])}
        self.assertEqual(q, {"A": "good", "B": "bad", "C": "bad"})


class ApiSmokeTest(unittest.TestCase):
    def test_flow_over_http(self):
        from fastapi.testclient import TestClient
        from backend import main
        with tempfile.TemporaryDirectory() as d, TestClient(main.app) as c:
            settings.data_dir = Path(d)
            self.assertEqual(c.get("/").status_code, 200)
            cfg = c.get("/api/config").json()
            self.assertEqual(len(cfg["survey"]), len(SURVEY))
            dev = c.post("/api/device/connect").json()
            self.assertTrue(dev["connected"] and dev["synthetic"])
            sess = c.post("/api/sessions", json={"participant_id": "P001"}).json()
            sid = sess["session_id"]
            self.assertEqual(len(sess["trials"]), len(STIMULI))
            c.post(f"/api/sessions/{sid}/survey", json={i["id"]: 5 for i in SURVEY})
            c.post(f"/api/sessions/{sid}/recording/start")
            with c.websocket_connect("/ws") as ws:
                tr = sess["trials"][0]
                ws.send_json({"type": "marker", "name": "fixation_onset", "trial_index": 0, "stimulus_id": tr["stimulus_id"]})
                kinds = set()
                for _ in range(10):
                    msg = ws.receive_json()
                    kinds.add(msg["type"])
                    if {"marker_ack", "signal"} <= kinds:
                        break
                self.assertIn("marker_ack", kinds)
            time.sleep(0.3)
            for name in ["stimulus_onset", "stimulus_offset"]:
                c.post(f"/api/sessions/{sid}/markers", json={"name": name, "trial_index": 0, "stimulus_id": tr["stimulus_id"]})
                time.sleep(0.3)
            c.post(f"/api/sessions/{sid}/ratings", json={"trial_index": 0, "stimulus_id": tr["stimulus_id"], "liking": 7, "seen_before": False})
            res = c.post(f"/api/sessions/{sid}/finish")
            self.assertEqual(res.status_code, 200, res.text)
            body = res.json()
            self.assertEqual(body["n_trials"], 1)
            self.assertEqual(body["items"][0]["quality"], "short_window")  # 0.3초 창은 분석 제외
            self.assertEqual(c.get(f"/api/sessions/{sid}/results").status_code, 200)
            c.post("/api/device/disconnect")


if __name__ == "__main__":
    unittest.main()


class ExportAndDeapTests(unittest.TestCase):
    def test_events_export_format(self):
        from backend.export import EVENT_COLUMNS, export_session
        with tempfile.TemporaryDirectory() as d:
            s = simulate_session(Path(d), {})
            info = export_session(s.dir, 250, settings.mock_channels)
            ev = pd.read_csv(s.dir / "events.csv")
            self.assertEqual(list(ev.columns), EVENT_COLUMNS)
            self.assertNotIn("kind", ev.columns)  # brainficial의 1–5점 검증을 피하기 위해 일부러 뺌
            self.assertEqual(len(ev), len(STIMULI))
            self.assertTrue(((ev.onset_s - ev.baseline_start_s).round(3) == 3).all())
            self.assertTrue(((ev.offset_s - ev.onset_s).round(3) == 4).all())
            self.assertTrue(info["eeg"]["uniform_for_loader"])
            self.assertEqual(info["model_input"]["eeg"], "eeg.csv")

    def test_jittered_timestamps_are_regularized(self):
        from backend.export import export_session
        with tempfile.TemporaryDirectory() as d:
            s = simulate_session(Path(d), {})
            eeg = pd.read_csv(s.dir / "eeg.csv")
            eeg["timestamp_s"] += np.random.default_rng(0).uniform(-0.001, 0.001, len(eeg))
            eeg.to_csv(s.dir / "eeg.csv", index=False)
            info = export_session(s.dir, 250, settings.mock_channels)
            self.assertEqual(info["model_input"]["eeg"], "eeg_model.csv")
            self.assertLess(info["eeg"]["regularized"]["max_shift_ms"], 5)

    def test_deap_model_used_when_available(self):
        try:
            from brainficial import deap_ml
        except Exception:
            self.skipTest("EEG_Test의 brainficial.deap_ml이 없음")
        import joblib
        from sklearn.linear_model import LogisticRegression
        channels = deap_ml.DEFAULT_CHANNELS
        names = deap_ml.feature_names(channels)
        rng = np.random.default_rng(0)
        X, y = rng.normal(size=(60, len(names))), np.repeat([0, 1], 30)
        bundle = {"models": {"logreg": LogisticRegression().fit(X, y)},
                  "metadata": {"channels": channels, "window": "first4", "stim_seconds": 4.0,
                               "feature_names": names, "fs": 128}}
        with tempfile.TemporaryDirectory() as d:
            joblib.dump(bundle, Path(d) / "model.joblib")
            old = settings.deap_model_path
            settings.deap_model_path = Path(d) / "model.joblib"
            try:
                s = simulate_session(Path(d), {"cat_nature": 9, "cat_city": 1})
                r = inference.run(s.dir, STIMULI, SURVEY, settings.feature_channels)
            finally:
                settings.deap_model_path = old
            self.assertEqual(r["model"]["name"], "deap_ensemble", r["model"].get("deap_skipped"))
            self.assertEqual(r["model"]["model_channels"], channels)
            probs = [it["eeg_like_probability"] for it in r["items"] if it["eeg_like_probability"] is not None]
            self.assertEqual(len(probs), len(STIMULI))
            self.assertTrue((s.dir / "model_apply" / "predictions.csv").is_file())

    def test_upload_mode_files_to_results(self):
        """파일 모드: 다른 형식(ms 시각, V 단위, 기록 시작 기준 이벤트, 1–5점)도 같은 결과 형식으로."""
        from fastapi.testclient import TestClient
        from backend import demo
        from backend.main import app
        with tempfile.TemporaryDirectory() as d:
            old_data, old_demo = settings.data_dir, demo.DEMO_DIR
            settings.data_dir = Path(d) / "sessions"
            settings.data_dir.mkdir()
            try:
                c = TestClient(app)
                demo_dir = demo.make_demo(Path(d) / "demo")
                eeg = pd.read_csv(demo_dir / "eeg.csv")
                ev = pd.read_csv(demo_dir / "events.csv")
                eeg["timestamp_s"] = (eeg["timestamp_s"] + 1.7e9) * 1000
                eeg = eeg.rename(columns={"timestamp_s": "time"})
                eeg.iloc[:, 1:] *= 1e-6
                ev = ev[["stimulus_id", "onset_s", "rating"]].rename(columns={"rating": "liking"})
                ev["liking"] = ((ev["liking"] + 1) / 2).round()
                sid = c.post("/api/uploads", json={"participant_id": "UP"}).json()["session_id"]
                r = c.put(f"/api/uploads/{sid}/files/eeg?name=e.csv", content=eeg.to_csv(index=False, sep=";").encode())
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.json()["time_unit"], "ms")
                self.assertEqual(r.json()["unit_guess"], "V")
                r = c.put(f"/api/uploads/{sid}/files/events", content=ev.to_csv(index=False).encode())
                self.assertEqual(r.json()["scale_guess"], "1-5")
                bad = c.put(f"/api/uploads/{sid}/files/events", content=b"a,b\n1,2\n")
                self.assertEqual(bad.status_code, 422)  # 잘못된 파일은 기존 파일을 지우지 않는다
                res = c.post(f"/api/uploads/{sid}/run", json={"unit": "V"})
                self.assertEqual(res.status_code, 200, res.text)
                j = res.json()
                self.assertEqual(j["mode"], "upload")
                self.assertEqual(j["n_usable"], len(ev))
                self.assertFalse(j["has_survey"])
                self.assertEqual(j["model"]["name"], "personal_logistic")
                self.assertGreater(j["rating_agreement_counts"]["agree"], j["rating_agreement_counts"]["disagree"])
                self.assertTrue((settings.data_dir / sid / "events.csv").is_file())  # 모델 입력 형식도 같이 만든다
            finally:
                settings.data_dir, demo.DEMO_DIR = old_data, old_demo

    def test_no_device_chosen_means_no_signal(self):
        """장비를 고르지 않았으면 모의 신호로 대신 연결하지 않는다."""
        from fastapi.testclient import TestClient
        from backend import main
        old = settings.source
        try:
            settings.source = "none"
            c = TestClient(main.app)
            r = c.post("/api/device/connect")
            self.assertEqual(r.status_code, 503)
            self.assertIn("장비가 선택되지 않았어요", r.json()["detail"])
            self.assertFalse(c.get("/api/device").json()["connected"])
            c.post("/api/lab/rehearsal")                       # 연습을 직접 고르면 모의 EEG
            dev = c.post("/api/device/connect").json()
            self.assertTrue(dev["connected"] and dev["synthetic"])
            c.post("/api/device/disconnect")
        finally:
            settings.source = old

    def test_device_gate_blocks_without_data(self):
        """연결 버튼만으로는 넘어가지 않는다: 실제 샘플이 들어와야 연결로 치고, 끊기면 시작 마커를 거절한다."""
        from fastapi.testclient import TestClient
        from backend import main
        from backend.eeg.base import EEGSource

        class Silent(EEGSource):  # 열리기는 하지만 데이터가 한 샘플도 안 오는 장비
            kind = "silent"

            def __init__(self):
                super().__init__()
                self.channels, self.fs = ["F3", "F4"], 250.0

            def start(self): pass
            def stop(self): pass
            def now(self): return time.monotonic()
            def read(self): return np.zeros(0), np.zeros((0, 2))

        with tempfile.TemporaryDirectory() as d:
            old = (settings.data_dir, main.create_source, main.CONNECT_TIMEOUT_S)
            settings.data_dir = Path(d)
            c = TestClient(main.app)
            try:
                main.CONNECT_TIMEOUT_S = 0.4
                main.create_source = lambda s: Silent()
                r = c.post("/api/device/connect")
                self.assertEqual(r.status_code, 503, r.text)
                self.assertFalse(c.get("/api/device").json()["connected"])
                sid = c.post("/api/sessions", json={"participant_id": "G"}).json()["session_id"]
                self.assertEqual(c.post(f"/api/sessions/{sid}/recording/start").status_code, 409)

                main.create_source = old[1]
                self.assertTrue(c.post("/api/device/connect").json()["streaming"])
                self.assertEqual(c.post(f"/api/sessions/{sid}/recording/start").status_code, 200)
                self.assertEqual(c.post("/api/device/simulate-drop").status_code, 200)
                time.sleep(2.3)  # 2초 넘게 샘플이 없으면 끊긴 것으로 본다
                self.assertFalse(c.get("/api/device").json()["connected"])
                gated = c.post(f"/api/sessions/{sid}/markers", json={"name": "fixation_onset", "trial_index": 0})
                self.assertEqual(gated.status_code, 409)
                self.assertTrue(c.post("/api/device/reconnect").json()["streaming"])
                ok = c.post(f"/api/sessions/{sid}/markers", json={"name": "fixation_onset", "trial_index": 0})
                self.assertEqual(ok.status_code, 200)
                def rows():
                    return (Path(d) / sid / "eeg.csv").read_text(encoding="utf-8").count("\n")
                n1 = rows()
                time.sleep(0.3)
                self.assertGreater(rows(), n1)  # 다시 연결 뒤 기록이 이어진다
            finally:
                if main.state.session:
                    main.state.session.stop_recording()
                if main.state.acquisition:
                    main.state.acquisition.stop()
                main.state.acquisition = main.state.session = None
                settings.data_dir, main.create_source, main.CONNECT_TIMEOUT_S = old
