# BrainFicial · EEG로 예측하는 시청 후 자기평정

같은 사람이 처음 보는 영상의 평점을 예측하는 문제와, 학습에 참여한 적이 없는 사람의 평점을 예측하는 문제를 각각 평가한다. DEAP의 음악 영상에는 소리도 포함되므로 관찰된 관계를 시각 자극만의 효과로 해석하기는 어렵다. 연구 설계의 원 출처는 [DEAP 논문](https://doi.org/10.1109/T-AFFC.2011.15)이다.

## PC에서 재실행

PowerShell에서 이 README가 있는 폴더로 이동한다. Python 3.12 환경에서 아래 명령을 실행한다. 데이터 폴더에는 `data_preprocessed_matlab/s01.mat`부터 `s32.mat`까지 있어야 한다. 현재 PC의 데이터 위치를 기본값으로 설정했다. 다른 위치에서는 특징 추출과 데모에 `--data "데이터 폴더"`를 전달한다.

```powershell
py -3.12 -m venv .venv
$python = ".\.venv\Scripts\python.exe"
& $python -m pip install -r requirements.txt
$data = "..\..\생체데이터 분석과 실무\DEAP_DATA_SET"
& $python features.py --data $data --ratings "$data\participant_ratings.csv"
& $python train.py --familiarity
& $python demo.py --data $data --bundle results/demo_Valence.joblib
```

표준 4개 라벨만 학습하려면 `train.py`에서 `--familiarity`를 생략한다. CSV가 없어도 `features.py`에서 `--ratings`를 생략하면 MATLAB의 4개 라벨을 사용할 수 있다. 위 데모는 이미 생성된 결과 파일이 있으면 추출·학습 없이 단독 실행할 수 있다.

이 PC에서 검증한 환경은 아래와 같다. BrainFicial 폴더에서 실행하면 기존 패키지로 데모를 재생할 수 있다. `--data`는 압축 해제된 데이터 폴더와 MATLAB ZIP을 모두 지원한다.

```powershell
$env:PYTHONPATH = (Resolve-Path '..\..\생체데이터 분석과 실무\.venv\Lib\site-packages').Path
$python = 'C:\Program Files\WindowsApps\OpenAI.CodexPrimaryRuntime.v26-1111-570-0_26.1111.570.0_x64__3k8sg7r9htsxt\dependencies\python\python.exe'
& $python demo.py --data "$HOME\Downloads\data_preprocessed_matlab.zip"
& $python verify.py --data "$HOME\Downloads\data_preprocessed_matlab.zip"
```

## 데이터와 특징

- 참가자 32명 × 영상 40개. MATLAB 행 번호를 1부터 센 값이 영상의 Experiment_id다. CSV는 제시 순서로 정렬되어 있어 참가자와 Experiment_id로 결합하고 표준 평점 네 열을 MATLAB과 대조한다.
- Valence, Arousal, Dominance, Liking은 각각 1–9점 독립 회귀다. Familiarity는 1–5점 별도 회귀이며 s02·s15·s23의 120개 결측은 이 평가에서만 제외한다.
- 128 Hz 데이터의 첫 32개 EEG 채널을 사용한다. 처음 3초는 기준선, 다음 60초는 20초씩 세 구간이다. 각 구간에서 2초 Hann 창, 50% 중첩 Welch PSD를 계산하고 [4,8), [8,13), [13,30), [30,45) Hz의 파워를 적분한다. 자극 파워(dB)와 자극−기준선(dB)을 함께 쓴다. 한 시행의 시간 구간은 항상 하나의 입력 행에 속한다.
- 32채널은 768개 특징, F3·F4·C3·C4는 96개 특징이다. 기존 BrainFicial의 영상 키 대조와 전두·중앙 4채널 패널을 참고했다. 과거 산출물은 실행에 필요하지 않다. 모델 입력은 EEG 파워 특징으로 구성한다.

## 평가와 파일 읽기

- **개인 내 미관측 영상**은 개인별 모델을 학습한다. 40편 중 32편 학습·8편 평가의 외부 5분할, 내부 영상 3분할이다.
- **미관측 참가자**는 참가자 단위 외부 4분할과 내부 3분할이다. 평가 참가자의 모든 시행을 함께 보류한다. 다른 참가자가 동일 영상을 본 기록은 학습에 포함될 수 있다.
- 중앙값은 외부 학습 평점에서 계산한다. Ridge와 RBF-SVR는 내부 학습 자료에서 표준화하고 단변량 F 점수로 16개 특징을 선택한다. 내부 검증 MAE로 Ridge 강도 10·100 또는 SVR C 0.3·3 중 하나를 고르고 외부 학습 자료에 재적합한다. 예측은 절단하지 않는다. 개인 내 셔플 시드는 42, 그룹 분할은 결정적이다.
- `results/predictions.csv`는 외부 평가 시행별 실제값·예측·폴드·선택 설정을 담는다. `metrics.csv`는 해당 조건의 전체 보류 예측으로 계산한 MAE와 R², `participant_metrics.csv`는 참가자별 MAE와 R²다. 전체 R²에는 개인 평균의 차이도 반영된다. 개인별 평점이 일정하면 그 사람의 R²는 공란이다. Familiarity의 MAE는 평정 척도가 다른 점을 고려해 읽는다.
- `results/demo_*.joblib`은 참가자 외부 평가 첫 폴드의 4채널 Ridge와 보류 시행 식별자를 담는다. 데모는 MATLAB의 EEG만 다시 읽고 저장한 예측과 1e-9 이내로 일치하는지 확인한다.

## 실제 4채널로 옮길 때

이번 비교는 DEAP의 동일한 32채널 전처리 기록에서 전극 네 개를 고른 오프라인 평가다. 실제 장치에서 전극 위치, 참조 전극, 단위, 필터, 샘플링률과 자극 시작 시각을 기록하고 동일한 위치의 채널 및 시간 구간을 대응시켜야 한다. 배치가 다르면 대응 가능한 패널로 다시 평가한다. 장치 전이는 새 장치의 EEG·자기평정 쌍을 확보해 새 참가자 평가와 개인 보정 후 평가를 각각 수행해야 검증할 수 있다.

## 결과 비교와 시행 조회

[결과표](results/comparison.md)는 모든 평가 조건의 MAE·R²와 개인 중앙값 또는 학습 참가자 중앙값 대비 개선 인원을 담는다. [시행별 예측 화면](results/trial_viewer.html)은 파일을 브라우저에서 열어 사용한다. 참가자와 영상 ID, 평가 방식, 채널, 모델을 선택하면 다섯 라벨의 실제값·외부 보류 예측·절대오차가 함께 바뀐다. Familiarity가 없는 시행에는 결측을 표시한다.

학습 결과를 갱신한 뒤에는 아래 명령으로 검증하고 결과표와 조회 화면을 다시 만든다.

```powershell
& $python verify.py --data "$HOME\Downloads\data_preprocessed_matlab.zip"
& $python report_results.py
& $python build_viewer.py
```
