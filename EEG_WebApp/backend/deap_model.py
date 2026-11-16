"""EEG_Test의 DEAP 사전학습 모델(`brainficial.deap_ml`)을 웹앱 결과에 연결하는 어댑터.

모델 파일(model.joblib)을 찾으면 측정 종료 시 apply_model을 그대로 호출하고,
없거나 실패하면 None을 돌려줘 웹앱이 기존 자리표시 모델로 넘어가게 한다.
주의: model.joblib은 학습할 때와 같은 scikit-learn 버전에서만 안전하게 열린다.
"""
from __future__ import annotations

from pathlib import Path

from .config import settings
from . import features  # noqa: F401  (brainficial 경로를 sys.path에 올려 둔다)


def model_path() -> Path | None:
    p = settings.deap_model_path
    return p if p and p.is_file() else None


def apply(session_dir: Path, model_input: dict) -> tuple[dict | None, str]:
    """반환: ({trial_id: 확률}, 메타데이터 포함 dict) 또는 (None, 사유)."""
    path = model_path()
    if path is None:
        return None, f"DEAP 모델 파일이 없습니다 ({settings.deap_model_path})."
    if not model_input:
        return None, "EEG 무결성 점검을 통과하지 못해 DEAP 모델을 적용하지 않았습니다."
    try:
        from brainficial.deap_ml import apply_model
    except Exception as exc:
        return None, f"brainficial.deap_ml을 불러오지 못했습니다: {type(exc).__name__}: {exc}"
    try:
        df, result = apply_model(session_dir / model_input["eeg"], session_dir / model_input["events"],
                                 model_input["fs"], model_input["unit"], path, session_dir / "model_apply",
                                 rating_threshold=6, low_max=4)
    except Exception as exc:
        return None, f"DEAP 모델 적용 실패: {type(exc).__name__}: {exc}"
    proba = {str(r["trial_id"]): float(r["p_ensemble"]) for r in df.to_dict("records")
             if r.get("quality") == "ok" and r.get("p_ensemble") == r.get("p_ensemble")}
    return {"proba": proba, "result": result, "path": str(path)}, "ok"
