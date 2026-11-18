"""research/m1-deap 방식 Liking 모델을 실험실 조건(O1·Oz·O2·Pz, 기준선 3초 + 사진 4초)으로 학습·평가·저장.

    python tools/train_m1_liking.py --data ..\\EEG_Test\\dataset\\data_preprocessed_matlab

1) DEAP 32명 × 영상 40개에서 특징을 뽑는다(backend/m1_liking.py와 같은 함수).
2) research/m1-deap train.py와 같은 두 가지로 평가한다.
     within_person   같은 사람의 처음 보는 영상: 사람마다 영상 5분할(외부) × 3분할(내부)
     new_participant 처음 보는 사람: 참가자 4분할(외부) × 3분할(내부)
   비교 기준은 학습 쪽 평점의 중앙값(같은 사람이면 그 사람의 중앙값)이다.
3) 1,280시행 전체로 최종 모델을 학습해 backend/m1_liking.json에 저장한다.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
from scipy.io import loadmat
from sklearn.feature_selection import SelectKBest, f_regression
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GridSearchCV, GroupKFold, KFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import m1_liking as M  # noqa: E402

DEAP_CHANNELS = ("Fp1 AF3 F3 F7 FC5 FC1 C3 T7 CP5 CP1 P3 P7 PO3 O1 Oz Pz "
                 "Fp2 AF4 Fz F4 F8 FC6 FC2 Cz C4 T8 CP6 CP2 P4 P8 PO4 O2").split()
FS = 128
SEED = 42
K_BEST = 16
MIN_WITHIN = 10   # 같은 사람 평가(영상 5분할)에 넣으려면 그 사람의 시행이 이만큼은 있어야 한다
ALPHAS = [10, 100]
SOURCE = "park105 research/m1-deap 34914d7 (features.py, train.py)"


def extract(data_dir: Path) -> pd.DataFrame:
    idx = [DEAP_CHANNELS.index(c) for c in M.CHANNELS]
    nb, ns = int(M.BASELINE_S * FS), int(M.STIMULUS_S * FS)
    rows = []
    for subject in range(1, 33):
        mat = loadmat(data_dir / f"s{subject:02}.mat", variable_names=["data", "labels"])
        if mat["data"].shape != (40, 40, 8064):
            raise ValueError(f"s{subject:02}.mat 크기가 DEAP 전처리 형식이 아닙니다: {mat['data'].shape}")
        for v in range(40):
            sig = mat["data"][v, idx, :].T                       # [8064, 4] µV, 앞 3초 기준선
            filt = M.bandpass(sig - sig.mean(axis=0), FS)        # 실측과 똑같이 전체 시행을 먼저 거름
            vec = M.features(filt[:nb], filt[nb:nb + ns], FS, filtered=True, artifact_uv=None)
            rows.append({"participant": subject, "video": v + 1, "liking": float(mat["labels"][v, 3]),
                         "peak_uv": M.peak_uv(filt[:nb + ns]), "ok": vec is not None,
                         **dict(zip(M.COLUMNS, vec if vec is not None else [np.nan] * len(M.COLUMNS)))})
        print(f"s{subject:02} 완료", flush=True)
    return pd.DataFrame(rows)


def pipeline():
    return make_pipeline(StandardScaler(), SelectKBest(f_regression, k=K_BEST), Ridge())


def search(x, y, splits):
    return GridSearchCV(pipeline(), {"ridge__alpha": ALPHAS}, cv=splits,
                        scoring="neg_mean_absolute_error", error_score="raise").fit(x, y)


def outer_folds(subject, regime):
    if regime == "new_participant":
        yield from GroupKFold(4).split(subject, groups=subject)
    else:
        for person in np.unique(subject):
            rows = np.flatnonzero(subject == person)
            if len(rows) < MIN_WITHIN:
                continue
            for a, b in KFold(5, shuffle=True, random_state=SEED).split(rows):
                yield rows[a], rows[b]


def evaluate(x, y, subject, video, regime):
    out = []
    for fold, (train, test) in enumerate(outer_folds(subject, regime)):
        if regime == "new_participant":
            assert not np.intersect1d(subject[train], subject[test]).size
            inner = list(GroupKFold(3).split(train, groups=subject[train]))
        else:
            assert not np.intersect1d(video[train], video[test]).size
            inner = list(KFold(3, shuffle=True, random_state=SEED).split(train))
        fit = search(x[train], y[train], inner)
        pred = fit.predict(x[test])
        med = np.median(y[train])
        for i, p in zip(test, pred):
            out.append((regime, fold, int(subject[i]), int(video[i]), float(y[i]), float(p), float(med),
                        fit.best_params_["ridge__alpha"]))
    return out


def summarize(pred: pd.DataFrame) -> dict:
    res = {}
    for regime, g in pred.groupby("regime"):
        clipped = g.prediction.clip(1, 9)
        per = g.assign(e_model=(clipped - g.truth).abs(), e_med=(g.median_pred - g.truth).abs()).groupby("participant")
        res[regime] = {
            "n": int(len(g)),
            "mae": round(float(mean_absolute_error(g.truth, clipped)), 3),
            "mae_median_baseline": round(float(mean_absolute_error(g.truth, g.median_pred)), 3),
            "r2": round(float(r2_score(g.truth, clipped)), 3),
            "participant_mae_mean": round(float(per.e_model.mean().mean()), 3),
            "participant_mae_median_baseline": round(float(per.e_med.mean().mean()), 3),
            "participants_better_than_median": int((per.e_model.mean() < per.e_med.mean()).sum()),
            "participants": int(g.participant.nunique()),
        }
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True, help="s01.mat–s32.mat가 있는 폴더")
    ap.add_argument("--out", type=Path, default=ROOT / "evaluation" / "m1_liking")
    ap.add_argument("--model", type=Path, default=M.MODEL)
    ap.add_argument("--artifact-uv", type=float, default=None,
                    help="이 진폭(µV, 4–45 Hz 필터 뒤)을 넘는 DEAP 시행을 학습에서 뺀다. 기본은 빼지 않음(원본 m1-deap과 같음)")
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    cache = args.out / "features.csv"
    frame = pd.read_csv(cache) if cache.exists() else None
    if frame is None or "peak_uv" not in frame:   # 진폭 열이 없는 예전 캐시는 다시 뽑는다
        frame = extract(args.data)
    frame.to_csv(cache, index=False)
    keep = frame.ok.astype(bool)
    if args.artifact_uv is not None:
        keep &= frame.peak_uv <= args.artifact_uv
    ok = frame[keep].reset_index(drop=True)
    over = {u: int((frame.peak_uv > u).sum()) for u in (100, 150, 200, 300, 500)}
    print(f"학습 시행 {len(ok)}/{len(frame)} (진폭 기준 {args.artifact_uv or '없음'}) · 진폭 초과 시행 수 {over}")
    x, y = ok[M.COLUMNS].to_numpy(float), ok.liking.to_numpy(float)
    subject, video = ok.participant.to_numpy(), ok.video.to_numpy()

    records = []
    for regime in ("within_person", "new_participant"):
        records += evaluate(x, y, subject, video, regime)
    pred = pd.DataFrame(records, columns=["regime", "fold", "participant", "video", "truth", "prediction",
                                          "median_pred", "alpha"])
    pred.to_csv(args.out / "predictions.csv", index=False)
    evaluation = summarize(pred)

    final = search(x, y, list(GroupKFold(4).split(x, groups=subject)))
    scaler, select, ridge = (final.best_estimator_.named_steps[k] for k in ("standardscaler", "selectkbest", "ridge"))
    selected = np.flatnonzero(select.get_support()).tolist()
    model = {
        "features": M.COLUMNS, "channels": M.CHANNELS, "bands": M.BANDS,
        "window": {"baseline_s": M.BASELINE_S, "stimulus_s": M.STIMULUS_S, "bandpass_hz": [4, 45]},
        "scaler_mean": scaler.mean_.tolist(), "scaler_scale": scaler.scale_.tolist(),
        "selected": selected, "selected_features": [M.COLUMNS[i] for i in selected],
        "coef": ridge.coef_.tolist(), "intercept": float(ridge.intercept_),
        "alpha": final.best_params_["ridge__alpha"], "k_best": K_BEST,
        "target": "DEAP Liking 1-9", "training_trials": int(len(y)), "participants": int(len(np.unique(subject))),
        "training_artifact_uv": args.artifact_uv, "inference_artifact_uv": M.ARTIFACT_UV,
        "within_person_min_trials": MIN_WITHIN,
        "source": SOURCE, "sklearn_version": sklearn.__version__,
        "evaluation": evaluation,
    }
    # 저장한 숫자만으로 sklearn 파이프라인과 같은 값이 나오는지 확인
    check = np.array([M.predict(v, model) for v in x[:50]])
    np.testing.assert_allclose(check, np.clip(final.predict(x[:50]), 1, 9), atol=1e-8)
    args.model.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out / "metrics.json").write_text(json.dumps(evaluation, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evaluation, ensure_ascii=False, indent=2))
    print(f"최종 alpha {model['alpha']} · 선택 특징 {len(selected)}개 · 저장 {args.model} · {time.time() - t0:.0f}초")


if __name__ == "__main__":
    main()
