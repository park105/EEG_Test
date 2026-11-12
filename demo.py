import argparse
from pathlib import Path

import joblib
import numpy as np

from features import CHANNELS, DEFAULT_DATA, features, read_subject


def replay(bundle_path, root):
    bundle = joblib.load(bundle_path)
    subject, video = bundle["subject"], bundle["video"]
    mat = read_subject(root, subject, ["data"])
    x = features(mat["data"][video-1, :32])
    columns = [CHANNELS.index(c) for c in bundle["channels"]]
    pred = bundle["model"].predict(x[columns].reshape(1, -1))[0]
    np.testing.assert_allclose(pred, bundle["prediction"], rtol=0, atol=1e-9)
    print(f"{bundle['target']} s{subject:02} video={video} prediction={pred:.8f} verified")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, default=Path("results/demo_Valence.joblib"))
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    args = parser.parse_args()
    replay(args.bundle, args.data)
