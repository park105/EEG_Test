# EEG 선호도 측정 웹앱

## 목요일 실측

Windows에서 이 폴더의 `start_lab.cmd`를 실행하세요. 첫 실행은 Python 3.12와 패키지 설치용 인터넷이 필요합니다. 배선 설정은 `http://127.0.0.1:8766/static/wiring.html`에서 열립니다.

1. 지텍 소프트웨어에서 EEG의 LSL 송출을 시작하고 웹앱에서 장비를 검색합니다. 장비 문서의 실제 입력 번호를 O1, Oz, O2, Pz에 연결해 입력 단위를 맞춥니다. REF·GND는 장비 문서에 따라 연결합니다.
2. 실장비 파일럿(사진 4장)을 선택하고 가명 ID와 참여 동의를 입력합니다. 기본 설정은 사전 설문을 이미 받은 상태이며, 참가자는 사진마다 회복 구간이 끝난 뒤 Liking 1–9점을 입력합니다. 현장 평정을 생략하려면 두 번째 체크를 해제하세요. 진행자용 사진 자료 화면에서는 본 측정에 쓰는 사진 32장과 ID를 점검할 수 있습니다.
3. 장비 연결 후 파형과 채널 품질을 확인합니다. 카메라 사용에 동의한 경우 내장 캠을 켜고 얼굴·귀·양쪽 어깨가 보이게 맞춥니다. 진행자 모니터는 같은 브라우저의 보조 화면에 두세요.
4. 휴식 기준선 후 각 사진마다 고정점 3초, 사진 4초, 회복 3초를 기록합니다. 파일럿 종료 후 모든 사진의 예측·프레임 수와 세션 폴더의 EEG·마커 파일을 확인한 뒤 별도 ID로 본 측정을 진행합니다.
5. 결과 화면에서 기존 서면 Liking 점수를 **사진별 또는 범주별**로 입력합니다. 5점/9점 척도를 지정하고 저장하면 기존 EEG 예측과 비교한 MAE·RMSE·±1점 이내 비율이 표시됩니다. 범주 설문은 해당 범주 사진들의 평균 예측과 비교합니다. 시작 화면의 ‘저장된 측정 결과’에서 다시 열 수 있습니다.

사진별 원자료는 `data/sessions/<세션>/`에 저장됩니다. `eeg.csv`와 `markers.csv`는 EEG 시간축, `capture_*.json`은 사진 ID와 브라우저 표시 구간 기준 시각·움직임 수치입니다. 원본 카메라 영상과 오디오는 저장하지 않습니다. `features.csv`, `results.json`, `paper_photo.json`, `paper_category.json`에서 분석값과 설문 비교값을 확인할 수 있습니다.

### 카메라 지표와 모델 해석

현장 Liking은 시행별 `response_번호.json`에 저장합니다. 4채널 모델은 EEG와 사진 시각으로 예측해 `results.json`에 기록합니다. 결과 화면에서만 저장된 예측과 현장 응답을 사진 ID로 연결하여 오차를 계산합니다. 사전 설문 비교와 현장 응답 비교는 각각 표시합니다.

연구 브랜치의 [check_emg.py](https://github.com/park105/EEG_Test/blob/34914d7602c84ba2a7ed6021ca459cedc13f9315/ablation/check_emg.py)는 DEAP의 광대근·승모근 **전극 EMG**와 EEG 감마 대역을 개인 내에서 비교합니다. 실측판은 해당 Python 분석의 Welch 30–45 Hz 대역파워와 참가자별 Spearman 상관을 사진 길이에 맞게 적용합니다. 내장 캠의 광대근 관련 지표는 좌우 입꼬리 웃음 점수 평균, 승모근 관련 지표는 귀 대비 양 어깨의 높이를 어깨 너비로 나눈 값입니다. 모두 움직임의 간접 지표로, 전기적 근활성도와 단위가 다릅니다. 기준선과 사진에서 모두 검출된 경우만 변화량을 산출하며 유효한 사진 세 쌍 이상과 지표 변동이 있어야 상관을 표시합니다.

카메라용 [Face Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker)와 [Pose Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker)는 앱에 포함되어 브라우저에서 실행됩니다. 몸을 돌리거나 고개를 움직여도 지표가 달라질 수 있습니다.

EEG Liking은 O1·Oz·O2·Pz의 고정점 대비 theta·alpha·beta 변화로 계산합니다. 기존 평가 파일에서 29명·1,160시행의 참가자별 MAE 평균은 새 영상 1.834점(개인 중앙값 1.738점), 새 참가자와 새 영상 1.841점(집단 중앙값 1.749점)입니다. 사진 실측에서의 성능은 별도 평가 대상입니다.

사진을 볼 때의 EEG로 선호를 추정하는 웹앱입니다. 시작 화면에서 두 가지 방식 중 하나를 고릅니다.

- **장비로 측정**: 평소 취향 설문 → 장비 연결·신호 확인·1분 휴식 기준선 → 이미지 시청 중 EEG 측정 → 측정 후 추론 → 결과
- **데이터 파일로 추론**: 평소 취향 설문(선택) → 이미 기록한 EEG 파일과 이벤트 파일 올리기 → 추론 → 결과
Python 3.10 이상을 권장합니다(`py --version`으로 확인, 3.9도 동작). EEG 장비가 없어도 **모의(합성) EEG**로 처음부터 끝까지 돌려 볼 수 있습니다.

> 결과는 항상 **"EEG 기반 추정"** 으로 표시합니다. 한 사람·한 세션의 탐색적 결과이며 "진짜 취향"을 판정하지 않습니다.

## 바로 실행 (Windows PowerShell)

`EEG_WebApp` 폴더에서:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000
```

브라우저에서 <http://localhost:8000> 을 엽니다. 시연·개발 중에는 <http://localhost:8000/?quick=1> 로 열면 기준선 10초, 시행 4개로 줄어듭니다.

**DEAP 모델을 쓰려면 Python 3.12 가상환경을 권장합니다.** EEG_Test에서 학습한 `model.joblib`은 학습 때와 같은 scikit-learn 버전(현재 1.9.1, Python 3.10 이상 필요)에서만 열립니다. Python 3.9 환경에서도 웹앱은 돌아가지만, 그때는 DEAP 모델 대신 자리표시 모델을 씁니다(결과 화면에 사유가 표시됨).

```powershell
py -3.12 -m venv .venv
```

macOS/Linux는 `python3 -m venv .venv`, `.venv/bin/python -m pip install -r requirements.txt`, `.venv/bin/python -m uvicorn backend.main:app --port 8000` 입니다.

테스트:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 화면 흐름

| 단계 | 화면 | 하는 일 | 저장 |
|---|---|---|---|
| 시작 | 참가자 ID·동의 | 가명 ID 입력 | `session.json` |
| ① | 평소 취향 설문 | 카테고리(자연·도시·동물·음식)와 색감(따뜻한·차가운) 선호 1–9, 현재 피로도. **실제 자극은 미리 보여주지 않음** | `survey.json` |
| ② | 장비 연결·신호 확인 | 채널별 품질(양호/보통/불량), 실시간 파형, 1분 휴식 기준선(화면 중앙 + 응시) | `eeg.csv`, `markers.csv` |
| ③ | 자극 측정 | 시행마다 고정점 3초 → 이미지 4초 → 빈 화면 3초 → 좋아요 1–9 / 본 적 있음. 순서는 세션마다 무작위 | `markers.csv`, `ratings.csv` |
| ④ | 추론 | 측정이 끝난 뒤 한 번에 계산 (실시간 아님) | `features.csv` |
| ⑤ | 결과 | 자극별 선호 확률·신뢰도, 설문과 **일치 / 어긋남 / 판단 보류** | `results.json` |

장비 연결 관문 (장비 모드)
- "연결됨"은 버튼을 눌렀다는 뜻이 아니라 **최근 2초 안에 실제 샘플이 들어왔다**는 뜻입니다. 연결을 눌러도 5초 안에 데이터가 한 샘플도 안 오면 연결 실패로 처리하고 사유를 보여 줍니다.
- 연결되기 전에는 기준선 측정 버튼이 잠겨 있고, 서버도 기록 시작과 기준선·시행 시작 마커를 거절합니다(HTTP 409).
- 기준선 측정 중 2초 넘게 끊기면 그 기준선은 버리고 연결 화면으로 돌아갑니다. 사진 측정 중 끊기면 그 시행은 평가 없이 멈추고(`trial_aborted` 마커), "다시 연결"에 성공해야 같은 사진부터 이어집니다. 끊긴 채로는 "측정 끝내기"만 할 수 있습니다.
- 다시 연결하면 같은 `eeg.csv`에 이어 기록하고 `device_reconnected` 마커를 남깁니다. 끊긴 구간은 무결성 점검에 누락으로 잡힙니다.
- 모의 EEG(`EEG_SOURCE=mock`, 기본값)는 장비 없이도 항상 연결됩니다. 끊김 동작은 측정 중에 `POST /api/device/simulate-drop`으로 확인할 수 있습니다(모의 전용).

사용 편의 기능
- 평정은 키보드로도 됩니다: 숫자 `1`–`9`, `Y`/`N`, `Enter`.
- 측정 중 `Esc`를 누르면 지금 사진과 평가를 마친 뒤 일시정지합니다. 사진이 12장 이상이면 절반에서 쉬는 시간이 자동으로 나옵니다. 일시정지 화면에서 측정을 일찍 끝내고 지금까지의 결과를 볼 수도 있습니다.
- 측정 중에 브라우저를 새로고침하거나 닫아도, 서버가 켜져 있으면 시작 화면에 "이어서 하기"가 나옵니다. 평가까지 끝난 사진은 건너뛰고, EEG 기록은 같은 파일에 이어서 저장됩니다.
- 결과 화면에서 CSV·JSON 내려받기와 인쇄(PDF 저장)를 할 수 있습니다. 운영체제가 다크 모드면 화면도 어둡게 바뀝니다. 다만 자극 화면 배경은 실험 조건을 맞추려고 항상 같은 회색입니다.

## 데이터 파일로 추론 (업로드 모드)

장비 없이, 다른 곳에서 기록한 EEG를 올려 같은 추론과 결과 화면을 씁니다. 올린 파일은 장비 세션과 똑같은 폴더 구조(`eeg.csv` µV, `markers.csv`, `ratings.csv`)로 바뀌어 저장되므로, 특징 계산·DEAP 모델 적용·`events.csv` 내보내기·무결성 점검이 그대로 적용됩니다. 세션 폴더 이름은 `<날짜-시각>_<ID>_upload`이고, 원본은 `raw_eeg.csv`, `raw_events.csv`로 남습니다.

**EEG 파일** (CSV·TSV·세미콜론 구분 자동 인식, UTF-8 또는 CP949)

| 열 | 내용 |
|---|---|
| 시각 열 | `timestamp_s`, `timestamp`, `time`, `t` 등. 초 또는 ms 자동 인식. 없으면 화면에서 샘플링 레이트를 입력하면 0초부터 만듭니다. |
| 채널 열 | 나머지 숫자 열(`sample`, `trigger`, `marker` 같은 열은 제외). 단위는 µV·mV·V 중 선택(값 크기로 추정해 미리 골라 줌). |

특징은 `FEATURE_CHANNELS`(기본 F3·Fz·F4·C3·Cz·C4)를 쓰고, 하나도 없으면 기록된 모든 채널을 씁니다. F3/F4가 없으면 전두 알파 비대칭 특징은 빠집니다.

**이벤트 파일**은 둘 중 하나입니다.

1. 시행 1개 = 1행 (`brainficial.deap_ml apply`의 events 형식과 같음)

   | 열 | 필수 | 없을 때 |
   |---|---|---|
   | `stimulus_id` | 필수 | |
   | `onset_s` | 필수 | |
   | `offset_s` | | `onset_s + 4초` (또는 `duration_s`로 계산) |
   | `baseline_start_s` | | `onset_s − 3초` (자극 직전 고정점 구간) |
   | `rating` | | 1–9점. 1–5점이면 자동 인식해 `2×점수−1`로 환산(6 이상 선호, 4 이하 비선호 기준 유지). 없으면 본인 평정 비교·개인 보정 모델 불가 |
   | `seen_before` | | 0/1, true/false, y/n |

   시각은 EEG 시각 열과 같은 시계·같은 단위여야 합니다. 이벤트가 "기록 시작부터 몇 초" 기준이면 EEG 첫 시각만큼 자동으로 옮깁니다. `stimulus_id`가 `stimuli/manifest.json`의 id와 같으면 결과에 사진과 카테고리가 함께 나오고, 다르면 ID만 표시하고 카테고리 비교는 생략합니다.

2. 이 웹앱이 저장한 세션 폴더의 `markers.csv` (+ 선택 `ratings.csv`): 예전 측정을 다시 계산할 때

설문을 건너뛰면 결과 화면은 EEG 추정을 **본인 평정**과 비교합니다(평정과 일치 / 어긋남 / 판단 보류). 화면의 "예시 데이터로 채우기" 또는 <http://localhost:8000/api/demo/eeg.csv>, <http://localhost:8000/api/demo/events.csv> 로 형식 예시(모의 합성 EEG)를 받을 수 있습니다. `python -m backend.demo`로 `data/demo/`에 만들어도 됩니다.

API로 직접 쓸 때:

```text
POST /api/uploads                     {"participant_id": "P001"} → session_id
PUT  /api/uploads/{id}/files/eeg      파일 본문 그대로 (eeg | events | ratings) → 형식 미리보기
POST /api/sessions/{id}/survey        (선택) 설문 응답
POST /api/uploads/{id}/run            {"fs": null, "unit": "uV", "rating_scale": "auto"} → results.json과 같은 결과
```

## 구조

```text
EEG 기기 ─(BrainFlow 또는 LSL, 또는 모의 소스)→ Python 수집 스레드 ─→ FastAPI 서버 ─(WebSocket)→ 웹 화면
                                                    │                     ▲
                                                    └→ eeg.csv            └ 화면이 보낸 시점 마커를 서버가
                                                                            EEG와 같은 시계로 찍어 markers.csv에 저장
```

```text
EEG_WebApp/
├─ backend/
│  ├─ main.py          FastAPI: REST(설문·평정·추론) + WebSocket(/ws: 실시간 신호·품질, 시점 마커)
│  ├─ config.py        환경 변수 설정(소스 종류, 채널, 타이밍)
│  ├─ session.py       세션 폴더 저장(EEG는 기록 중 계속 디스크에 추가 → 중단돼도 남음)
│  ├─ quality.py       ② 채널별 신호 품질 판정
│  ├─ features.py      전두·중심 채널 밴드파워 특징 (EEG_Test의 brainficial 재사용)
│  ├─ model.py         모델 인터페이스와 자리표시 모델
│  ├─ inference.py     ④ 오프라인 추론, 설문·평정과 비교
│  ├─ export.py        측정 종료 시 모델 입력 형식(events.csv) 저장, 데이터 무결성 점검
│  ├─ deap_model.py    EEG_Test DEAP 사전학습 모델 연결
│  ├─ upload.py        업로드 모드: 파일 형식 인식·검증·변환
│  ├─ demo.py          업로드 모드 예시 파일(모의 EEG) 생성
│  └─ eeg/
│     ├─ base.py       EEGSource 인터페이스, 수집 스레드, 링 버퍼
│     ├─ mock.py       모의(합성) EEG
│     ├─ brainflow_source.py
│     └─ lsl_source.py
├─ frontend/           index.html, app.js, style.css (빌드 도구 없음)
├─ stimuli/
│  ├─ manifest.json    자극 목록 (id, src, category, tone)
│  ├─ survey.json      ① 설문 문항 (maps_to로 자극 category/tone과 연결)
│  ├─ images/          예시 사진 32장 (CREDITS.md에 출처)
│  └─ placeholder/     이전 자리표시 SVG 12장
├─ tools/             fetch_stimuli.py · build_stimuli.py (자극 만들기), make_placeholder_stimuli.py
├─ tests/test_webapp.py
└─ data/sessions/      측정 결과 (git에 올리지 않음)
```

### 시간 동기화 (가장 중요)

모든 EEG 소스는 `now()`를 갖고, 이 시계가 샘플 timestamp와 같은 시계입니다(모의: `time.monotonic`, BrainFlow: `time.time`, LSL: `pylsl.local_clock`). 화면은 고정점·이미지를 실제로 그린 직후(두 프레임 대기) WebSocket으로 마커를 보내고, **서버가 `now()`로 시각을 찍습니다.** 브라우저의 `performance.now()`도 `client_ts_ms`로 함께 남겨 지연을 점검할 수 있습니다.

한계: 소프트웨어 시각이라 수 ms~수십 ms 오차가 있습니다. 밴드파워(4초 구간) 분석에는 충분하지만, ERP처럼 ms 정확도가 필요하면 광센서나 장비 하드웨어 트리거로 검증해야 합니다.

## 저장 데이터 구조 (모델 입력 형식)

웹앱은 기기 종류와 상관없이 아래 형식으로 저장합니다. 이 형식은 EEG_Test의 `python -m brainficial.deap_ml apply` 입력과 그대로 맞습니다. 세션마다 `data/sessions/<날짜-시각_참가자ID>/` 폴더가 생깁니다.

**eeg.csv**: 한 행이 한 샘플입니다. 시각은 마커와 같은 시계를 쓰고, 단위는 µV입니다.

```csv
timestamp_s,Fp1,AF3,F3,...,Cz,C4
12034.512000,3.214,-1.022,0.871,...
12034.516000,2.998,-0.871,1.102,...
```

**events.csv**: 한 행이 한 시행입니다. 측정이 끝나면 만들어집니다.

| 열 | 뜻 |
|---|---|
| `trial_id` | T000, T001 … (제시 순서) |
| `stimulus_id` | manifest의 자극 id |
| `baseline_start_s` | 고정점(+) 시작 = 시행 기준선 3초의 시작 |
| `onset_s` / `offset_s` | 이미지가 뜬 시각 / 사라진 시각 (4초) |
| `rating` | 좋아요 1–9 (DEAP liking과 같은 척도) |
| `seen_before` | 본 적 있음 1 / 처음 봄 0 |
| `rating_time_s` | 평정을 낸 시각 |

`kind`, `participant_id` 열은 일부러 넣지 않았습니다. 그 열이 다 있으면 brainficial이 실습용 1–5점 형식으로 검사하기 때문입니다. 1–9점은 `--rating-threshold 6 --low-max 4`로 6점 이상 선호, 4점 이하 비선호, 5점 제외로 평가합니다.

**integrity.json**: 샘플 누락률, 시각 간격 흔들림, 마커 지연 흔들림, 그리고 모델에 넣을 파일과 명령어. 장비 시각이 흔들리지만 누락이 없으면 시각을 균일하게 다시 매긴 `eeg_model.csv`를 만들고, 누락이 있으면 모델 적용을 막고 이유를 남깁니다.

그 밖에 `session.json`(참가자, 기기 정보: 채널·fs, 자극 순서), `survey.json`, `markers.csv`(모든 화면 이벤트), `ratings.csv`, `features.csv`, `results.json`, `model_apply/`(DEAP 모델 적용 결과)가 있습니다.

같은 데이터를 EEG_Test에서 직접 돌리려면:

```powershell
cd ..\EEG_Test
.\.venv\Scripts\python.exe -m brainficial.deap_ml apply --eeg <세션폴더>\eeg.csv --events <세션폴더>\events.csv --fs 250 --unit uV --model outputs\real\deap_ml\default16_first4\model.joblib --out outputs\real\lab_apply --rating-threshold 6 --low-max 4
```

**기기가 정해지면 확인할 것:** 모델이 쓰는 채널 이름(기본 16채널 Fp1 AF3 F3 F7 FC5 FC1 C3 Fp2 AF4 Fz F4 F8 FC6 FC2 Cz C4)이 `eeg.csv` 열 이름에 그대로 있어야 합니다. 기기에 없는 채널이 있으면 EEG_Test에서 `--channels`로 그 기기 채널만 써서 다시 학습합니다. 채널 이름이 다르게 나오는 기기는 `DEVICE_CHANNELS`로 이름을 붙여 줍니다.

## 실제 장비 연결

모의 소스 대신 쓰려면 서버를 켜기 전에 환경 변수를 설정합니다.

**BrainFlow** (OpenBCI Cyton/Ganglion, Muse, BrainBit 등):

```powershell
.\.venv\Scripts\python.exe -m pip install brainflow
$env:EEG_SOURCE = "brainflow"
$env:BRAINFLOW_BOARD_ID = "0"            # 0 = OpenBCI Cyton. -1은 BrainFlow 합성 보드(설치 확인용)
$env:BRAINFLOW_SERIAL_PORT = "COM3"
$env:DEVICE_CHANNELS = "Fp1,Fp2,C3,C4,P7,P8,O1,O2"   # 보드가 채널 이름을 모를 때, 실제 전극 위치 순서대로
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000
```

**LSL** (제조사 앱이 LSL로 내보내는 경우):

```powershell
.\.venv\Scripts\python.exe -m pip install pylsl
$env:EEG_SOURCE = "lsl"
$env:LSL_STREAM_TYPE = "EEG"             # 또는 $env:LSL_STREAM_NAME = "스트림 이름"
```

장비가 V 단위로 내보내면 `$env:DEVICE_SCALE_TO_UV = "1000000"`. 장비에 F3/F4/C3/C4 등이 없으면 `$env:FEATURE_CHANNELS = "Fp1,Fp2,C3,C4"`처럼 특징 채널을 바꿉니다(전두 비대칭 특징은 F3/F4가 있어야 계산됩니다).

| 환경 변수 | 기본값 | 의미 |
|---|---|---|
| `EEG_SOURCE` | `mock` | `mock` / `brainflow` / `lsl` |
| `FEATURE_CHANNELS` | `F3,Fz,F4,C3,Cz,C4` | 모델 특징에 쓰는 전두·중심 채널 |
| `BASELINE_SECONDS` | `60` | ② 휴식 기준선 |
| `FIXATION_SECONDS` / `STIMULUS_SECONDS` / `RECOVERY_SECONDS` | `3` / `4` / `3` | ③ 시행 타이밍 (분석에는 고정점·자극 각각 2초 이상 필요) |
| `ORDER_SEED` | (빈 값=무작위) | 자극 순서 재현용 seed |
| `BRAINFICIAL_PATH` | `../EEG_Test` | 팀 저장소의 brainficial 위치 |
| `DATA_DIR` | `data/sessions` | 세션 저장 위치 |
| `DEAP_MODEL_PATH` | `../EEG_Test/outputs/real/deap_ml/default16_first4/model.joblib` | DEAP 사전학습 모델 |
| `MOCK_CHANNELS` | DEAP 기본 16채널 이름 | 모의 EEG 채널 |

## 모델 (자리표시)

**특징** (`backend/features.py`): 시행마다 고정점 3초를 기준선으로, 자극 4초 구간의 전두·중심 채널 theta(4–8)·alpha(8–13)·beta(13–30 Hz) 파워 변화(dB)와 전두/중심 알파 비대칭(ln F4α − ln F3α) 변화를 계산합니다. 같은 `proai` 폴더에 `EEG_Test`가 있으면 그 안의 `brainficial` 전처리(1–40 Hz 필터, 진폭·평탄 검사)와 Welch 밴드파워를 그대로 가져다 씁니다. 없으면 같은 규칙의 내장 구현을 씁니다. 결과 화면 하단에 어느 쪽을 썼는지 표시됩니다.

**모델** (`backend/model.py`), 모두 `PreferenceModel`(`fit`, `predict_proba`) 인터페이스:

- 1단계 분류 (현재)
  - `PersonalLogistic`: ③의 본인 평정(6 이상 좋아함, 4 이하 싫어함, 5 제외)으로 개인 보정. **각 자극의 확률은 그 자극의 평정을 뺀 나머지로 학습한 모델로만 계산**(교차검증)해서 정답이 새지 않게 했습니다. 좋아함·싫어함이 각각 3개 이상일 때 사용.
  - `FrontalAsymmetryBaseline`: 평정이 부족할 때 쓰는 학습 없는 규칙(전두 알파 비대칭 → 확률).
  - `PretrainedModel`: DEAP 등으로 미리 학습한 sklearn 모델(joblib)을 끼우는 자리.
- `PretrainedModel` 자리에는 실제로 EEG_Test의 DEAP 앙상블이 연결되어 있습니다(`backend/deap_model.py`). `DEAP_MODEL_PATH`(기본 `..\EEG_Test\outputs\real\deap_ml\default16_first4\model.joblib`)에 파일이 있으면 측정이 끝날 때 그 모델을 먼저 쓰고, 없거나 실패하면 아래 자리표시 모델로 넘어갑니다.
- 2단계 회귀 (예정): `PreferenceRegressor.predict_rating`으로 1–9 평점 자체를 예측.

**신뢰도** = |확률 − 0.5| × 2. 0.15 미만이면 EEG 판단을 "불확실"로 두고 설문 비교에서 "판단 보류"로 셉니다.
**설문 기대 선호** = 그 자극의 category·tone에 연결된 설문 문항 점수 평균(1–9). 6 이상 선호, 4 이하 비선호.

## 자극 바꾸기

기본 자극은 위키미디어 공용(Wikimedia Commons)의 자유 라이선스 예시 사진 32장입니다(자연·도시·동물·음식 각 8장). 공용 커뮤니티가 품질 검토한 사진('Quality images')에서만 골랐고, 사람이 크게 나온 사진·흑백 사진·정치적 장면은 뺐습니다. 작가와 라이선스(CC0, CC BY, CC BY-SA)는 `stimuli/CREDITS.md`에 있고 결과 화면 아래 링크로도 볼 수 있습니다. 발표 자료 등에 쓸 때도 출처를 표기하세요.

모든 사진은 4:3으로 자르고 1024×768로 맞췄고, 밝기(휘도 평균·대비)를 같게 조정했습니다. `tone`(따뜻한/차가운 색감)은 평균 색(R−B)으로 자동 분류했습니다(따뜻한 20장, 차가운 12장).

다시 만들거나 다른 사진으로 바꾸려면:

1. `python tools/fetch_stimuli.py` : 카테고리별 후보 14장을 `stimuli/candidates/`에 내려받습니다(표준 라이브러리만 사용, 인터넷 필요). 검색어는 파일 위쪽 `QUERIES`에서 바꿉니다.
2. 후보를 직접 보고 고른 뒤 `pip install pillow` 후 `python tools/build_stimuli.py --pick nature_c02 city_c01 ...` : 고른 사진으로 `stimuli/images/`, `manifest.json`, `CREDITS.md`를 다시 만듭니다.
3. 직접 찍거나 구한 사진을 쓸 때는 사용 동의·라이선스를 확인하고 `manifest.json`의 `category`/`tone`을 설문 문항(`stimuli/survey.json`의 `maps_to`)과 맞춥니다.
4. 이전 자리표시 그림 12장은 `stimuli/placeholder/`에 남겨 두었습니다.

시행 32개면 기준선 1분을 포함해 약 9~10분이 걸립니다. `?quick=1`로 열면 4개만 진행합니다.

**영상 확장(예정):** manifest의 `type: "video"`를 받을 자리는 만들어 두었습니다. 영상은 길이가 제각각이라 구간 설계(고정 길이로 자르기, 구간별 평균 등)를 먼저 정한 뒤 `frontend/app.js`의 `runTrials`와 `inference.build_trials`를 확장하면 됩니다.

## 모의 EEG에 대해

`backend/eeg/mock.py`는 배경 잡음, 알파·세타·베타 리듬, 50 Hz 전원 잡음, 가끔 눈 깜박임을 흉내 냅니다. 결과 화면이 비어 보이지 않도록 '가상 참가자'가 자연·동물을 좋아하고 도시를 싫어한다고 정해 두고, 자극 중 전두 알파 비대칭을 바꿉니다. 이는 **동작 확인용 장치이며 실제 뇌 반응을 주장하지 않습니다.** 모의 결과 화면에는 항상 "모의(합성) EEG" 경고가 붙습니다.

## 개인정보

EEG·설문·평정은 이 PC의 `data/sessions/`에만 저장되고 외부로 보내지 않습니다. 가명 ID를 쓰고, 보관·삭제 기간을 참가자에게 안내하세요. `data/`는 `.gitignore`에 들어 있습니다.
