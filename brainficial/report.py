"""Static, portable report with explicit provenance and downloadable CSVs."""
import html
import json
from pathlib import Path
import os
import tempfile
# Keep plotting caches writable on locked-down classroom computers.
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "brainficial-mpl"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.signal import welch


def write_report(out, recording, events, features, quality, metrics, predictions, synthetic):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    label = "SYNTHETIC / NOT EMPIRICAL" if synthetic else "REAL INPUT / EXPLORATORY"
    metrics["data_source"] = label
    for name, df in [("features", features), ("quality", quality), ("predictions", predictions)]:
        df.to_csv(out/f"{name}.csv", index=False)
    (out/"metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False, "font.size": 11})
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), constrained_layout=True)
    e = events.iloc[0]
    mask = (recording.time >= e.baseline_start_s) & (recording.time < e.offset_s)
    axes[0, 0].plot(recording.time[mask], recording.samples[mask, 0], lw=.6, color="#5266e8")
    axes[0, 0].axvspan(e.onset_s, e.offset_s, color="#46bca4", alpha=.18, label="Stimulus on → off")
    axes[0, 0].set(title="First trial • baseline and stimulus", xlabel="Event clock (s)", ylabel="Amplitude (uV)")
    axes[0, 0].legend(fontsize=9)
    for name, a, b in [("Baseline", e.baseline_start_s, e.onset_s), ("Stimulus", e.onset_s, e.offset_s)]:
        selection = (recording.time >= a) & (recording.time < b)
        f, p = welch(recording.samples[selection, 0], fs=recording.fs, nperseg=int(2*recording.fs))
        axes[0, 1].semilogy(f, p, label=name)
    axes[0, 1].set(xlim=(1, 40), title="First channel • raw Welch PSD", xlabel="Frequency (Hz)", ylabel="uV²/Hz")
    axes[0, 1].legend()
    if not features.empty:
        col = next(c for c in features if c.startswith("feature_") and "beta" in c)
        axes[1, 0].scatter(features.rating, features[col], c="#5266e8", alpha=.6)
        axes[1, 0].set(title="Observed rating vs EEG change", xlabel="Self-reported liking (1–5)", ylabel=col.replace("feature_", ""), xticks=[1, 2, 3, 4, 5])
    if metrics["status"] == "ok":
        axes[1, 1].bar(["EEG model", "Majority baseline"], [metrics["balanced_accuracy"], metrics["dummy_balanced_accuracy"]], color=["#5266e8", "#b9bfce"])
        axes[1, 1].axhline(.5, color="#999", ls="--")
    else:
        axes[1, 1].text(.1, .5, "Insufficient data\nNo performance claim", transform=axes[1, 1].transAxes)
    axes[1, 1].set(title="Held-out stimuli • 3-fold evaluation", ylim=(0, 1.08), ylabel="Balanced accuracy")
    fig.suptitle(f"BrainFicial | {label}", fontsize=18, fontweight="bold")
    fig.savefig(out/"dashboard.png", dpi=150)
    plt.close(fig)
    score = f'{metrics["balanced_accuracy"]:.3f}' if metrics["status"] == "ok" else "평가 보류"
    warning = "합성 EEG와 합성 평점입니다. 관계를 넣은 조건과 넣지 않은 대조 조건 모두 구현 검증용이며 실제 취향 예측 근거가 아닙니다." if synthetic else "실제 입력의 탐색적 분석입니다. 관심·각성·움직임·자극 속성의 영향을 배제하지 못하므로 취향 판독으로 해석할 수 없습니다."
    conclusion = "분석 프로그램의 동작을 확인했습니다. 사람의 취향 예측 능력은 아직 확인하지 않았습니다." if synthetic else "탐색 결과입니다. 이 점수만으로 선호를 측정했다고 결론 내릴 수 없습니다."
    check = metrics.get("permutation", {"status": "not_run", "reason": "Not requested"})
    if check["status"] == "ok":
        explanation = (f'자극별 평균 특징으로 별도 평가한 점수는 {check["observed_balanced_accuracy"]:.3f}입니다. '
                       f'선호 라벨을 자극 단위로 {check["n_permutations"]}번 섞어 다시 학습한 비교에서 '
                       f'p값은 {check["p_value"]:.3f}입니다. '
                       '이는 위 시행별 점수와 다른 추가 검증입니다. 자극 라벨을 교환해도 된다는 가정이 필요하며, '
                       '작은 p값도 밝기·주의 등 다른 원인을 배제하거나 실제 취향 판독을 입증하지 않습니다.')
        fig, ax = plt.subplots(figsize=(8, 4), constrained_layout=True)
        ax.hist(check["null_scores"], bins=12, range=(0, 1), color="#b9bfce", edgecolor="white")
        ax.axvline(check["observed_balanced_accuracy"], color="#5266e8", lw=2, label="Observed stimulus-level score")
        ax.set(xlim=(0, 1.02), xlabel="Balanced accuracy", ylabel="Permutation count", title=f"{label} | Shuffled-label diagnostic")
        ax.legend(fontsize=9)
        fig.savefig(out/"permutation.png", dpi=150)
        plt.close(fig)
        extra_image = '<img src="permutation.png" alt="자극 단위로 평점 라벨을 섞은 점수 분포와 관측 점수">'
    else:
        explanation = '추가 검증을 실행하지 않았습니다. 정확도에 임의의 합격선을 정하지 않습니다. 사유: ' + html.escape(check["reason"])
        extra_image = ""
    document = f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>뇌피셜 · BrainFicial 연구 데모</title><style>body{{font:16px/1.7 system-ui,sans-serif;background:#f1f4fa;color:#19243c;margin:0}}main{{max-width:1100px;margin:auto;padding:48px 24px}}header{{background:#15213e;color:white;padding:32px;border-radius:20px}}h1{{font-size:42px;margin:0}}.tag{{color:#9fe8db}}.cards{{display:flex;gap:18px;flex-wrap:wrap;margin:24px 0}}.card{{background:white;padding:20px;border-radius:14px;flex:1}}b{{font-size:26px}}img{{width:100%;border-radius:16px}}.warn{{background:#fff0c8;padding:20px;border-radius:12px}}a{{color:#435bd5}}pre{{white-space:pre-wrap;background:white;padding:20px;border-radius:12px}}</style>
<main><header><div class="tag">PERSONAL PREFERENCE RESEARCH · {label}</div><h1>뇌피셜 / BrainFicial</h1><p>자극에 대한 반응을 측정하고, 본인의 선호 평점과 관계가 있는지 검증합니다.</p></header>
<p class="warn">{warning}</p><section class="cards"><div class="card">기록한 시행<br><b>{len(events)}</b></div><div class="card">품질 통과<br><b>{len(features)}</b></div><div class="card">분리 평가 점수<br><b>{score}</b></div></section>
<h2>지금 말할 수 있는 결론</h2><p>{conclusion}</p><p>93%처럼 높은 점수도 자동 합격 기준이 아닙니다. 잡음·자극 조건 통제와 다른 날짜의 검증이 필요합니다.</p>
<h2>실험 → 신호 → 비교 → 검증</h2><p>기준선 → 자극 시작 → 자극 종료 → 1–5점 자기보고 → EEG 품질 검사 → 대역별 PSD 변화 → 자극 ID를 분리한 평가</p>
<img src="dashboard.png" alt="합성 여부가 표시된 EEG 파형, PSD, 평점 비교, 분리 검증 그래프">
<h2>우연한 점수와 비교하기</h2><p>{explanation}</p>{extra_image}
<h2>해석의 경계</h2><p>같은 자극의 반복은 같은 평가 그룹에 묶었습니다. 3점은 이진 분류에서 제외하고, 표준화는 학습 데이터에만 맞춥니다. 한 사람·한 세션·한 자극 종류만 분석합니다. 이 결과는 새 사람이나 새 날짜의 성능을 보장하지 않습니다.</p>
<p>ERP 옵션은 300–500 ms 평균 진폭일 뿐 P300 검출이나 선호도 고유 지표가 아닙니다. 실험용 화면의 소프트웨어 시각은 실제 화면/오디오 지연을 보정하지 않습니다.</p>
<h2>결과 파일</h2><p><a href="features.csv">특징 CSV</a> · <a href="quality.csv">품질 CSV</a> · <a href="predictions.csv">검증 예측 CSV</a> · <a href="metrics.json">평가 상세 JSON</a> · <a href="provenance.json">입력/설정 기록</a></p>
<details><summary>평가 상세와 분할 목록</summary><pre>{html.escape(json.dumps(metrics, ensure_ascii=False, indent=2))}</pre></details></main></html>'''
    (out/"report.html").write_text(document, encoding="utf-8")
