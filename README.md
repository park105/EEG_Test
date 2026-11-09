# 뇌피셜 / BrainFicial

2차 멘토평가 보고서에 맞춘 [DEAP 실험 결과와 재실행 방법](REPORT_ALIGNMENT_KO.md): 자극 반응, 선호 연관성, 전극 위치별 차이, 새로운 영상 예측을 분리해 평가했습니다.

**DEAP 실측 분석 추가:** 개인별 음악영상 선호 평점 예측을 재실행하려면 [DEAP.md](DEAP.md)를 보세요. 아래 기존 `demo` 결과는 합성이고, `deap` 명령은 별도의 실측 분석입니다.

**EEG로 개인의 선호 평점과 관련된 신호가 있는지 탐색하는 모듈형 연구 프로젝트.**
하드웨어 없이 합성 EEG 생성 → 전처리 → 특징 추출 → 자기보고 비교 → 자극 분리 평가 → 보고서까지 실행됩니다.
동봉한 결과는 전부 **합성 데이터(SYNTHETIC)**이며 실제 실험 성과가 아닙니다.

## 바로 시연하기

Python 3.10 이상(검증 환경 3.12), 인터넷은 최초 패키지 설치에만 필요합니다.
ZIP을 풀고 `BrainFicial` 폴더에서 실행합니다. Windows에서는 `python` 대신 `py`를 사용할 수 있습니다.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m brainficial demo --out outputs/demo
Start-Process outputs/demo/report.html
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

macOS/Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m brainficial demo --out outputs/demo
.venv/bin/python -m unittest discover -s tests -v
```

**설치가 급하면 `outputs/demo/report.html`을 먼저 여세요.** 동봉된 CSV와 그림으로 전체 흐름을 설명할 수 있습니다. 이는 이미 실행해 만든 합성 데모 결과이며, 실행을 다시 하지 않아도 열립니다. `requirements-tested.txt`는 실제 검증에 사용한 버전 목록입니다.

```sh
python -m brainficial demo --kind music --erp --out outputs/music
python -m brainficial demo --null --out outputs/null
```

`--null`은 모든 자극에 공통 반응은 있지만 평점에 따른 신호 차이는 넣지 않는 대조 조건입니다. 한 번의 우연한 점수를 통계적 유의성으로 해석하지 않습니다. `--kind`는 합성 실험 메타데이터만 바꾸며 실제 인물·음악 신경반응을 시뮬레이션했다고 주장하지 않습니다.

## 수업에서 설명할 논리

1. 색상 EEG 연구에서 선호 평점과 뇌파 반응의 관계를 탐색한 선례가 있다.
2. 따라서 특정 사람에게 자극을 보여주고, 자극 전 기준선과 자극 중 EEG를 비교한다.
3. 자극이 끝난 다음 본인이 1–5점으로 평가한다. EEG 반응 자체를 정답으로 쓰지 않는다.
4. 대역별 파워의 기준선 대비 변화가 자기보고와 관련되는지 탐색한다.
5. 본 적 없는 자극에서도 평점을 구분하는지 확인하기 위해 자극 ID별로 학습·평가를 분리한다.
6. 결과가 좋아도 자극의 색·밝기·음량·친숙함·주의·각성·움직임과 선호를 구분하는 후속 실험이 필요하다.

**발표 문장:** “뇌피셜은 뇌파만 보고 취향을 단정하는 서비스가 아니라, 개인의 자극 반응과 자기보고 선호의 관계를 검증하는 연구 파이프라인입니다. 오늘은 합성 데이터로 전체 동작을 시연하고, 장비 형식이 정해지면 같은 인터페이스에 실제 CSV를 연결합니다.”

## 구조와 책임

| 구성 | 책임 | 위치 |
|---|---|---|
| EEGLoader | 채널·단위·샘플 간격 확인, uV 정규화 | `brainficial/loader.py` |
| AnalEEG | 진폭/평탄 신호 검사, 1–40 Hz 필터 | `brainficial/signal.py` |
| GetFeature | Welch PSD, theta/alpha/beta 파워 | `brainficial/signal.py` |
| CompSig | 기준선/자극 파워 및 dB 변화, 선택적 ERP 창 | `brainficial/signal.py` |
| CompLike | 자기보고 라벨, 자극별 3-fold 검증 | `brainficial/model.py` |
| EventLogger | 시행 CSV, 중단 시에도 남는 marker JSONL | `brainficial/experiment.py` |
| ExperimentTemplate | 색상/인물/음악, 고정 ID, 반복/순서 | `brainficial/experiment.py` |
| ExperimentRunner | 제시기/시계 분리, 실측 onset/offset | `brainficial/experiment.py` |
| validator/reporter | 잘못된 입력 거부, 결과·그림·HTML | `validation.py`, `report.py` |
| DeviceAdapter | 제조사 CSV/SDK → 공통 형식 경계 | `brainficial/adapters.py` |

```text
ExperimentTemplate → ExperimentRunner → EventLogger → events.csv
DeviceAdapter → EEGLoader → AnalEEG → GetFeature → CompSig
events.csv + CompSig → CompLike → CSV / JSON / PNG / HTML
```

프로젝트 루트에서 실행하므로 설치 없이 import됩니다. 다른 프로젝트에서는 `python -m pip install -e .`로 패키지로 사용할 수 있습니다. 장비 SDK와 화면 제시기를 교체해도 신호/모델 모듈은 바꾸지 않습니다.

## 실제 CSV 연결

EEG CSV 한 행 = 한 샘플. `timestamp_s`는 **이벤트와 동일한 시계의 초**, 채널은 명시한 단위입니다.

```csv
timestamp_s,F3,F4
0.000000,2.1,-1.3
0.0078125,2.4,-1.1
0.015625,1.8,-0.9
```

이 짧은 표는 형식 설명용입니다. 실제 분석에는 완전한 기준선과 자극 구간이 필요합니다.

```csv
participant_id,session_id,trial_id,stimulus_id,kind,baseline_start_s,onset_s,offset_s,rating_time_s,rating
P001,S001,T000,color_00,color,1,4,8,8.5,4
```

```sh
python -m brainficial analyze --eeg data/eeg.csv --events data/events.csv --fs 128 --channels F3 F4 --unit uV --source real --out outputs/real
```

합성 CSV를 재분석할 때에는 반드시 `--source synthetic`으로 표시하세요. 자동으로 실제/합성을 판별할 수는 없습니다.

제조사 형식 변환 예:

```python
from brainficial.adapters import CSVDeviceAdapter
CSVDeviceAdapter(
    "vendor.csv", time_column="time_ms", channel_map={"CH1": "F3", "CH2": "F4"},
    time_scale=0.001, time_offset_s=-12.4, voltage_scale_to_uv=1e6,
).export("aligned_eeg.csv")
```

위 오프셋은 **설명용 값**입니다. 실제 동기화 마커에서 측정해야 합니다. 첫 행을 무조건 0초로 맞추면 안 됩니다. 장시간 기록의 시계 드리프트는 여러 동기화 마커로 교정해야 하며 이 버전은 자동 교정하지 않습니다. `CSVDeviceAdapter`는 변환만 하고 `EEGLoader`에서 균일 샘플링을 검증합니다. 누락 샘플을 몰래 보간하지 않습니다.

장비 연결 전 확인할 것: 모델/SDK, 샘플링 주파수, 전극 위치/참조 전극, 실제 단위·스케일, timestamp 의미, 마커 지원, 접촉 품질과 누락 샘플, 노치/내장 필터. F3/F4는 데모 채널명일 뿐 모든 장비에 존재한다고 가정하지 않습니다.

## 실험 템플릿과 화면 실행

`templates/`에 색상·인물·음악 설정이 있습니다. 새 템플릿 세트는 `python -m brainficial templates --out my_templates`로 생성합니다.

```sh
python -m brainficial run --template templates/color.json --events outputs/live/events.csv --participant P001 --session S001
```

회색 화면/십자 기준선 3초 → 자극 4초 → 회색 화면 → 1–5점 입력을 12자극 × 2회 진행합니다. 자극 순서는 seed에 따라 반복 블록별 무작위화합니다. 평점 입력은 EEG 특징 구간에서 제외됩니다. 이벤트 파일은 덮어쓰지 않으므로 다시 실행할 때 경로/세션을 바꾸세요. 취소 시 완료 시행과 부분 마커가 남습니다.

이 화면은 **실험 리허설용**입니다. EEG를 수집하지 않습니다. tkinter 설치가 필요하며 macOS/Linux에서는 별도 OS 패키지가 필요할 수 있습니다. 인물은 사용 동의를 받은 PNG/GIF를 템플릿 상대 경로에 넣으세요. 이미지 크기와 밝기를 사전에 통일하세요. 음악은 Windows `winsound`의 WAV 재생 예시이며, 다른 OS/정밀 실험에서는 Presenter를 교체하세요. 오디오 길이는 자극 시간 이상이어야 하고 음량을 통일해야 합니다. 인물/음악 파일은 동봉하지 않았습니다.

onset/offset은 화면 갱신/재생 호출 **직후 소프트웨어 시각**입니다. 광센서·루프백·하드웨어 트리거 검증 전에는 밀리초 정확도 또는 ERP 실험 적합성을 주장할 수 없습니다. `Presenter`와 `clock` 주입 경계는 정밀 실험 도구 연결을 위한 것입니다.

## 분석 규칙과 한계

- 한 사람·한 세션·한 종류씩 분석. 기준선/자극 각각 2초 이상, 순서와 EEG 범위 검증. `baseline ≤ t < onset`, `onset ≤ t < offset`의 반개구간 사용.
- 원 신호 절대 진폭 150 uV 초과, peak-to-peak 300 uV 초과 또는 채널 표준편차 0.05 uV 미만이면 해당 시행 제외. 이 임계값은 데모 초기값이며 전문적인 artifact 제거를 대신하지 않습니다. 눈깜박임/근전도 ICA 제거는 미구현입니다.
- 4차 Butterworth 1–40 Hz zero-phase 필터를 기준선/자극별로 독립 적용. 다른 시행으로 필터가 번지는 누수를 막지만 구간 경계 효과가 있습니다. 실제 연구에서는 패딩/epoch 설계를 장비와 함께 재검토해야 합니다.
- Welch 2초 창, theta [4,8), alpha [8,13), beta [13,30) Hz. 대역 파워는 PSD 합 × 주파수 간격(uV²), 변화는 `10 log10((stimulus+epsilon)/(baseline+epsilon))` dB.
- `--erp`: 마지막 기준선 200 ms 평균을 빼고 onset 후 300–500 ms의 **원 신호 평균 진폭**을 계산. 별도 ERP 전처리·동기화 검증·평균 파형 검토가 없는 탐색용 특징이며 P300 검출기가 아닙니다.
- 평점 1–2 낮음, 4–5 높음; 3 중립은 특징 CSV에 남기고 이진 평가에서 제외. 평점과 ID·타이밍은 모델 입력에 포함하지 않습니다.
- 각 라벨이 최소 3개 자극 ID에 걸쳐 있어야 합니다. 3-fold StratifiedGroupKFold로 같은 자극은 항상 한 fold. fold에서 한 클래스라도 빠지면 성능을 출력하지 않고 보류합니다.
- 고정 LogisticRegression + 학습 fold 안에서만 StandardScaler. 다수 클래스 기준 모델과 balanced accuracy를 비교하며, 평가 fold로 하이퍼파라미터를 고르지 않습니다.
- 반복 시행은 독립 표본이 아닙니다. 기본 점수는 시행 가중 기술통계입니다. 선택적으로 자극별 평균 특징의 별도 순열 진단을 제공합니다(아래 참조). 신뢰구간·세션 외부 검증은 아직 없습니다.
- 자극을 분리해도 저수준 자극 속성 및 순서/피로 혼입은 남습니다. 선호의 인과적 지표, 숨은 취향, 이상형 판정, 집단 일반화로 해석하지 않습니다.
- 실험 참여와 개인정보 수집은 동의를 받고, ID를 가명화하고 데이터 보관/삭제 범위를 정하세요. 얼굴·EEG·평점은 외부로 자동 업로드하지 않습니다.

## 결과 파일

| 파일 | 내용 |
|---|---|
| `input/eeg.csv`, `input/events.csv` | 데모 합성 EEG·이벤트·평점 |
| `features.csv` | 통과 시행의 기준선/자극 파워, 변화량, 선택적 ERP |
| `quality.csv` | 모든 시행의 통과/제외 사유 |
| `predictions.csv` | out-of-fold 예측, 실제 이진 라벨, dummy, fold |
| `metrics.json` | 점수, 입력 특징, 학습/평가 자극 목록 |
| `provenance.json`, `generator.json` | 입력 SHA-256, 설정·버전·합성 생성 조건 |
| `dashboard.png`, `report.html` | 발표용 그림과 한국어 보고서 |

분석 출력 경로를 재사용하면 결과가 갱신됩니다. 실제 연구는 세션마다 새 출력 폴더를 사용하세요. 분류 조건이 부족하면 예측 CSV는 비어 있고 JSON/보고서에 보류 사유가 남습니다.

근거의 범위와 스크랩 해석은 [RESEARCH_NOTES.md](RESEARCH_NOTES.md), 3분 발표 순서는 [CLASSROOM_DEMO.md](CLASSROOM_DEMO.md)를 참고하세요.

## 추가 검증: 점수에 임의의 합격선을 두지 않기

```sh
python -m brainficial demo --permutations 199 --out outputs/demo
python -m brainficial demo --null --permutations 199 --out outputs/null
```

`brainficial/inference.py`는 **자극별 EEG 특징 평균**으로 별도의 3-fold GroupKFold 평가를 합니다. 분할은 라벨과 무관하게 고정하고, 자극 단위 이진 라벨을 섞을 때마다 표준화와 모델을 다시 학습합니다. 순열에서 학습 클래스가 하나가 되면 해당 클래스만 예측하며, 불리한 순열을 버리지 않습니다. 관측 점수 이상인 순열 수를 b, 반복 수를 B라 할 때 p=(b+1)/(B+1)입니다.

이는 기존 시행별 StratifiedGroupKFold 점수와 **다른 통계량**이며 보고서에도 따로 표시합니다. 199회일 때 최소 보고 p값은 0.005이며 정밀한 확정 검정이 아닙니다. 작은 p값은 선호 고유 신호, 인과관계, 새로운 날짜의 성능을 보장하지 않습니다. 결과를 보고 특징/분할을 반복 선택하면 이 p값도 확증 근거가 될 수 없습니다.

현재 구현은 보수적으로 제한합니다: 자극마다 보존된 반복 수가 같고, 같은 자극의 모든 평점이 동일한 이진 라벨에 속하며, 중립 평점이 없어야 합니다. 실제 자료에서는 시간/블록/자극 종류 등으로 라벨 교환이 제한될 수 있으므로 교환 가능성을 검토한 뒤에만 `analyze --permutations 199 --assume-exchangeable`을 사용하세요. 가정이 확인되지 않거나 조건이 맞지 않으면 실행을 보류하고 사유를 보고합니다. 자동으로 평점을 합치거나 중립을 제거해 검정 조건을 맞추지 않습니다.

쉬운 진행 요약: [NEXT_STEPS_KO.md](NEXT_STEPS_KO.md).
