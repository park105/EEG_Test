"""Descriptive within-person EEG/EMG covariation, independent of model fitting."""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from run import OUT, ROOT, PANELS
from features import CHANNELS, FS, power, read_subject


def run(source):
    with np.load(ROOT/"results/features.npz") as data:
        eeg=data["x"][:,:,:,0,3]
        subjects,videos=data["subject"],data["video"]
    rows=[]
    for person in range(1,33):
        mat=read_subject(source,person,["data"])["data"]
        signal=mat[:,34:36,3*FS:]
        assert signal.shape==(40,2,60*FS) and np.isfinite(signal).all()
        mask=subjects==person
        np.testing.assert_array_equal(videos[mask],np.arange(1,41))
        for t,window in enumerate(["0-20","20-40","40-60"]):
            emg=np.stack([power(trial[:,t*20*FS:(t+1)*20*FS])[:,3] for trial in signal])
            for panel,channels in PANELS.items():
                avg=eeg[mask][:,[CHANNELS.index(c) for c in channels],t].mean(axis=1)
                for i,muscle in enumerate(["zygomaticus","trapezius"]):
                    rho=spearmanr(avg,emg[:,i]).statistic
                    rows.append((person,panel,window,muscle,rho))
        del mat,signal
    frame=pd.DataFrame(rows,columns=["participant","panel","window","muscle","rho"])
    frame.to_csv(OUT/"emg_participants.csv",index=False)
    frame.groupby(["panel","window","muscle"]).rho.agg(n="count",median="median",
        q25=lambda s:s.quantile(.25),q75=lambda s:s.quantile(.75),positive=lambda s:(s>0).sum()).to_csv(OUT/"emg_summary.csv")


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--data",type=Path,default=ROOT.parent/"DEAP_DATA_SET")
    run(p.parse_args().data)
