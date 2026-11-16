"""환경 변수로 바꿀 수 있는 설정 모음.

예) PowerShell:  $env:EEG_SOURCE = "brainflow"; $env:BRAINFLOW_BOARD_ID = "0"
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_list(name: str, default: str) -> list[str]:
    return [c.strip() for c in _env(name, default).split(",") if c.strip()]


@dataclass
class Timing:
    """③ 자극 시행 타이밍(초)과 ② 휴식 기준선 길이."""
    baseline_s: float = float(_env("BASELINE_SECONDS", "60"))
    fixation_s: float = float(_env("FIXATION_SECONDS", "3"))
    stimulus_s: float = float(_env("STIMULUS_SECONDS", "4"))
    recovery_s: float = float(_env("RECOVERY_SECONDS", "3"))


@dataclass
class Settings:
    # mock | brainflow | lsl
    source: str = _env("EEG_SOURCE", "mock")
    # 모델 특징에 쓰는 전두·중심 채널. 장비에 없는 채널은 자동으로 빠진다.
    feature_channels: list[str] = field(default_factory=lambda: _env_list(
        "FEATURE_CHANNELS", "F3,Fz,F4,C3,Cz,C4"))
    # 모의 EEG 채널 구성
    # 모의 EEG 채널 구성: EEG_Test DEAP 모델 기본 16채널(전두+중심)과 같은 이름
    mock_channels: list[str] = field(default_factory=lambda: _env_list(
        "MOCK_CHANNELS", "Fp1,AF3,F3,F7,FC5,FC1,C3,Fp2,AF4,Fz,F4,F8,FC6,FC2,Cz,C4"))
    mock_fs: float = float(_env("MOCK_FS", "250"))
    mock_seed: int = int(_env("MOCK_SEED", "7"))
    # BrainFlow: board_id는 BrainFlow 문서의 BoardIds 값 (-1 = BrainFlow 합성 보드, 0 = OpenBCI Cyton 등)
    brainflow_board_id: int = int(_env("BRAINFLOW_BOARD_ID", "-1"))
    brainflow_serial_port: str = _env("BRAINFLOW_SERIAL_PORT", "")
    # 장비 채널 이름이 보드 정보에 없을 때 쓰는 이름(쉼표 구분, 장비 채널 순서대로)
    device_channel_names: list[str] = field(default_factory=lambda: _env_list("DEVICE_CHANNELS", ""))
    # LSL
    lsl_stream_type: str = _env("LSL_STREAM_TYPE", "EEG")
    lsl_stream_name: str = _env("LSL_STREAM_NAME", "")
    # 장비 출력 단위를 uV로 맞추는 배율 (V 출력이면 1000000)
    device_scale_to_uv: float = float(_env("DEVICE_SCALE_TO_UV", "1"))

    timing: Timing = field(default_factory=Timing)
    data_dir: Path = Path(_env("DATA_DIR", str(ROOT / "data" / "sessions")))
    stimuli_dir: Path = ROOT / "stimuli"
    frontend_dir: Path = ROOT / "frontend"
    # 팀 저장소의 brainficial 패키지 위치. 있으면 그 전처리·밴드파워 코드를 재사용한다.
    brainficial_path: Path = Path(_env("BRAINFICIAL_PATH", str(ROOT.parent / "EEG_Test")))
    # DEAP 사전학습 모델(EEG_Test의 deap_ml train 결과). 비우면 자리표시 모델만 사용
    deap_model_path: Path = Path(_env("DEAP_MODEL_PATH", str(
        ROOT.parent / "EEG_Test" / "outputs" / "real" / "deap_ml" / "default16_first4" / "model.joblib")))
    # 시행 순서 무작위화 seed (비우면 세션마다 무작위)
    order_seed: str = _env("ORDER_SEED", "")


settings = Settings()
