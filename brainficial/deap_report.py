"""Readable result generated from the measured scores, never a canned verdict."""
def write_report(summary, out):
    lines = ["# BrainFicial · DEAP 개인별 영상 선호 분석", "",
             f"실측 자료: 참가자 파일 {len(summary['files'])}개, 영상 시행 {summary['trials']}개. 품질 상태: {summary['quality']}.",
             "조건: 동일인·동일 세션, 학습에 쓰지 않은 영상의 liking(1–9점) 예측. 색 전환이나 두 색 직접 선택 실험은 아닙니다.", "",
             "| EEG 입력 | 평가 인원 | 평균 절대 오차(점) ↓ | 기준 오차(점) ↓ | 기준보다 나은 사람 | 두 영상 순서 일치율 |",
             "|---|---:|---:|---:|---:|---:|"]
    for mode, m in summary["methods"].items():
        name = {"change":"직전 3초 대비 60초 시청 파워 변화", "stimulus":"60초 시청 파워만"}[mode]
        lines.append(f"| {name} | {m['participants']} | {m['mae']:.3f} | {m['reference']:.3f} | {m['better']} | {m['pair_concordance']:.1%} |")
    lines += ["", "기준 모델은 학습 영상에 매긴 본인 평점의 중앙값만 답합니다. 모든 평균은 참가자에게 같은 가중치를 줍니다.",
              "순서 일치율은 같은 평가 묶음 안의 두 영상을 비교합니다. 실제 동일 평점은 제외하고 예측 동점은 절반으로 셉니다. 이 쌍들은 독립 표본이 아닙니다.",
              "두 방식 모두 같은 영상 분할과 F3·F4 특징 여섯 개를 썼습니다. 다른 날 또는 다른 자극 종류에 대한 검증은 없습니다.",
              "개인별 오차: participants.csv · 영상별 평가 예측: predictions.csv · 입력 특징 및 품질 상태: features.csv."]
    (out/"report.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
