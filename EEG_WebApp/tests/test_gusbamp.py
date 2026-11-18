"""g.USBamp 직접 연결: 가짜 장비(GDS_FAKE=1)로 검색 → 배선 적용 → 수신·시각 → USB 분리까지.
그리고 g.Pype가 설치돼 있으면 실제 g.Pype 파이프라인(gp.GUSBamp 대신 gp.Generator)으로 수신 노드를 확인한다."""
import os
os.environ.setdefault("EEG_SOURCE", "mock")
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np


@mock.patch.dict(os.environ, {"GDS_FAKE": "1"})
class GUSBampTests(unittest.TestCase):
    def test_source_timestamps_follow_sample_count(self):
        from backend.eeg.gusbamp_source import GUSBampSource
        src = GUSBampSource("UB-FAKE.01", fs=512, channel_names=["O1", "Oz", "O2", "Pz"])
        src.start()
        builtin_fake = src.amp is not None
        try:
            time.sleep(0.8)
            t, x = src.read()
        finally:
            src.stop()
        self.assertEqual(x.shape[1], 4)
        self.assertGreater(len(t), 300)
        np.testing.assert_allclose(np.diff(t), 1 / 512, rtol=1e-9)     # 샘플 번호 ÷ fs
        self.assertLess(abs(src.now() - t[-1]), 0.5)                     # 마커와 같은 시계
        if builtin_fake:   # g.Pype 없는 가짜 장비: 앞쪽 입력(A1–A3)에 큰 알파
            self.assertGreater(np.std(x[:, 0]), np.std(x[:, 3]))

    def test_wiring_page_flow_and_unplug(self):
        from fastapi.testclient import TestClient
        from backend import main
        from backend.config import settings
        old = (settings.data_dir, settings.source)
        with tempfile.TemporaryDirectory() as d, TestClient(main.app) as c:
            settings.data_dir = Path(d)
            try:
                found = c.get("/api/lab/streams").json()
                amp = next(s for s in found if s["uid"].startswith("gusbamp:"))
                self.assertEqual((len(amp["wires"]), amp["wires"][0]["unit"], amp["fs"]), (16, "uV", 256))
                names = ["O1", "Oz", "O2", "Pz"] + [""] * 12
                wires = [{"name": n, "kind": "EEG" if n else "skip", "unit": "uV"} for n in names]
                dev = c.post("/api/lab/layout", json={"uid": amp["uid"], "wires": wires}).json()
                self.assertEqual((dev["kind"], dev["channels"], dev["fs"], dev["connected"]),
                                 ("gusbamp", ["O1", "Oz", "O2", "Pz"], 256.0, True))
                self.assertEqual(dev["input_layout"]["uid"], amp["uid"])
                # 다른 프로그램이 장비를 잡고 있으면 목록에 표시된다
                self.assertTrue(c.get("/api/lab/streams").json()[0]["in_use"])

                src = main.state.acquisition.source                        # USB 분리
                if src.amp is not None:      # g.Pype 없는 가짜 장비
                    src.amp.unplug_after_s = 0
                else:                        # g.Pype 경로: 파이프라인이 ERROR 상태가 된 것처럼
                    src._failure = lambda: "g.Pype 파이프라인 오류: 장비 응답 없음(USB 분리)"
                deadline = time.time() + 3
                while c.get("/api/device").json()["connected"] and time.time() < deadline:
                    time.sleep(0.1)
                state = c.get("/api/device").json()
                self.assertFalse(state["connected"])
                self.assertIn("USB", state["error"])
                again = c.post("/api/device/reconnect").json()                   # 다시 꽂고 재연결
                self.assertTrue(again["connected"])
            finally:
                c.post("/api/lab/rehearsal")
                settings.data_dir, settings.source = old


try:
    import gpype  # noqa: F401
    HAVE_GPYPE = True
except ImportError:
    HAVE_GPYPE = False


@unittest.skipUnless(HAVE_GPYPE, "g.Pype 미설치")
class GPypePathTests(unittest.TestCase):
    def test_pipeline_error_becomes_disconnect(self):
        """g.Pype가 실행 중 오류로 파이프라인을 ERROR로 바꾸면 read()가 끊김으로 알린다."""
        import gpype as gp
        from backend.eeg.gusbamp_source import GUSBampSource

        class Unplugged(gp.Generator):   # 몇 프레임 뒤 USB가 빠진 장비처럼 실패한다
            def step(self, data):
                self.n = getattr(self, "n", 0) + 1
                if self.n > 5:
                    raise RuntimeError("장비 응답 없음(USB 분리)")
                return super().step(data)

        def amp(**kwargs):
            return Unplugged(sampling_rate=kwargs["sampling_rate"], channel_count=len(kwargs["channel_selection"]),
                             frame_size=8, signal_amplitude=20)

        with mock.patch.dict(os.environ, {"GDS_FAKE": ""}), mock.patch.object(gp, "GUSBamp", amp):
            src = GUSBampSource("UB-2016.01.01", channel_names=["O1", "Oz", "O2", "Pz"])
            src.start()
            try:
                deadline, error = time.time() + 5, None
                while time.time() < deadline and error is None:
                    try:
                        src.read()
                    except ConnectionError as exc:
                        error = str(exc)
                    time.sleep(0.05)
            finally:
                src.stop()
        self.assertIsNotNone(error)
        self.assertIn("USB", error)

    def test_gpype_pipeline_feeds_webapp(self):
        """GDS_FAKE 없이 g.Pype 경로를 그대로 타되, 장비 노드만 g.Pype의 신호 발생기로 바꾼다."""
        import gpype as gp
        from backend.eeg.gusbamp_source import GUSBampSource
        opened = {}

        def fake_amp(**kwargs):
            opened.update(kwargs)
            return gp.Generator(sampling_rate=kwargs["sampling_rate"],
                                channel_count=len(kwargs["channel_selection"]), frame_size=8,
                                signal_frequency=10, signal_amplitude=20, noise_amplitude=2)

        with mock.patch.dict(os.environ, {"GDS_FAKE": ""}), mock.patch.object(gp, "GUSBamp", fake_amp):
            src = GUSBampSource("UB-2016.01.01", channel_names=["O1", "Oz", "O2", "Pz"])
            src.start()
            try:
                time.sleep(1.0)
                t, x = src.read()
            finally:
                src.stop()
        self.assertEqual(opened["serial"], "UB-2016.01.01")
        self.assertEqual(opened["channel_selection"], [0, 1, 2, 3])   # 배선한 입력만 수집
        self.assertEqual((opened["sampling_rate"], opened["common_reference"], opened["enable_trigger"]),
                         (256, [True] * 4, False))
        self.assertEqual(x.shape[1], 4)
        self.assertGreater(len(t), 150)
        np.testing.assert_allclose(np.diff(t), 1 / 256, rtol=1e-9)


if __name__ == "__main__":
    unittest.main()
