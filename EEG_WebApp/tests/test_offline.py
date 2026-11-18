import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from fastapi import HTTPException
from backend import offline
from backend.config import settings


class OfflineTest(unittest.TestCase):
    def test_two_clock_alignment_and_separate_responses(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(settings, "data_dir", Path(tmp)):
            meta = offline.create(offline.Start(participant="TEST", quick=True))
            sid = meta["session_id"]
            def event(name, t, idx=None):
                return {"name":name, "elapsed_s":t, "epoch_ms":1700000000000+t*1000, "trial_index":idx}
            record = offline.Record(events=[event("recording_start",0),event("baseline_start",0),event("baseline_end",10)])
            offline.save_record(sid,0,record)
            offline.save_record(sid,0,record)  # Safe retry.
            for i,photo in enumerate(meta["trials"]):
                t=10+i*10
                offline.save_record(sid,i+1,offline.Record(events=[
                    event("fixation_onset",t,i),event("stimulus_onset",t+3,i),
                    event("stimulus_offset",t+7,i),event("rating_shown",t+10,i)],
                    capture={"stimulus_id":photo["id"],"camera_enabled":False,"samples":[],"live_liking":i+2}))
            offline.save_record(sid,5,offline.Record(events=[event("recording_end",50)]))
            d=offline.directory(sid)
            t=np.arange(0,70,1/256)
            rng=np.random.default_rng(3)
            frame=pd.DataFrame(rng.normal(0,10,(len(t),4)),columns=["A","B","C","D"])
            frame.insert(0,"clock",t)
            frame.to_csv(d/"external_test.csv",index=False)
            args=offline.Align(file_id="test",fs=256,channels=dict(zip(["O1","Oz","O2","Pz"],["A","B","C","D"])),
                               time_column="clock",web_anchor_s=0,eeg_anchor_s=5,
                               web_anchor2_s=50,eeg_anchor2_s=55.05,method="synthetic two anchors")
            result=offline.analyze(sid,args)
            out=Path(tmp)/result["session_id"]
            markers=pd.read_csv(out/"markers.csv")
            self.assertAlmostEqual(markers.loc[markers.name=="stimulus_onset","server_ts"].iloc[0],18.013)
            self.assertEqual(len(offline.read(out/"results.json")["items"]),4)
            self.assertTrue(pd.read_csv(out/"ratings.csv").empty)
            self.assertEqual(offline.read(out/"response_0.json")["liking"],2)
            self.assertEqual(offline.read(d/"offline.json")["status"],"finished")
            with self.assertRaises(ValueError):
                offline.analyze(sid,args.model_copy(update={"eeg_anchor_s":100,"eeg_anchor2_s":150}))
            with self.assertRaises(HTTPException):
                offline.save_record(sid,0,offline.Record(events=[event("recording_start",1)]))

