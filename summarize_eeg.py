"""Summarize paired participant errors and standardized Ridge weights."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from interpret_eeg import OUT, PANELS, TIMES, BANDS, ROOT, CHANNELS
from scipy.stats import rankdata

TARGETS = ["Valence","Arousal","Dominance","Liking","Familiarity"]
REGIMES = {"within_person":"개인 내 미관측 영상", "new_participant":"미관측 참가자"}


def paired(person):
    wide = person.query("mode == 'joint'").pivot(index=["regime","target","participant"], columns="panel", values="MAE")
    wide["central_vs_frontal"] = wide.Frontal - wide.Central
    wide["central_added"] = wide.Frontal - wide.Combined
    wide.to_csv(OUT / "participant_differences.csv")
    rows = []
    for (regime,target), group in wide.groupby(level=["regime","target"]):
        for contrast in ["central_vs_frontal","central_added"]:
            d = group[contrast].to_numpy()
            samples = np.random.default_rng(42).choice(d,(10000,len(d))).mean(axis=1)
            lo, hi = np.quantile(samples,[0.025,0.975])
            rows.append((regime,target,contrast,len(d),sum(d>0),d.mean(),np.median(d),lo,hi))
    result = pd.DataFrame(rows,columns=["regime","target","contrast","n","improved","mean","median","lo","hi"])
    result.to_csv(OUT / "central_effect.csv",index=False)
    return result


def describe_weights():
    w = pd.read_csv(OUT / "fold_weights.csv")
    w["magnitude"] = w.coef.abs()
    w["share"] = 100*w.magnitude/w.groupby(["target","panel","participant","fold"]).magnitude.transform("sum")
    # A feature absent from an outer fit has zero weight; 32 people x 5 folds.
    groups = ["target","panel","channel","band","time","power"]
    people = w.groupby(groups+["participant"]).agg(signed=("coef","sum"),folds=("fold","size"),share=("share","sum")).reset_index()
    people["positive"] = (people.signed > 0) & (people.folds >= 3)
    people["negative"] = (people.signed < 0) & (people.folds >= 3)
    totals = people.groupby(groups).agg(share=("share","sum"), positive=("positive","sum"),
                                         negative=("negative","sum"),selected_folds=("folds","sum")).reset_index()
    totals["share"] /= 160
    totals.to_csv(OUT / "feature_summary.csv",index=False)
    return totals


def central_associations():
    # Descriptive only: pre-specified pair average, separately for each trial and feature.
    rows = []
    with np.load(ROOT/"results/features.npz") as data:
        raw = data["x"][:,[CHANNELS.index("C3"),CHANNELS.index("C4")]].mean(axis=1)
        subjects, y = data["subject"], data["y"]
        for s in np.unique(subjects):
            ix = subjects == s
            ranks = rankdata(raw[ix].reshape(ix.sum(),-1),axis=0)
            ranks -= ranks.mean(axis=0)
            for target in ["Valence","Dominance"]:
                rating = rankdata(y[ix,list(data["targets"]).index(target)])
                rating -= rating.mean()
                denom = np.linalg.norm(ranks,axis=0)*np.linalg.norm(rating)
                corr = np.divide(rating @ ranks,denom,out=np.full(denom.shape,np.nan),where=denom>0)
                for (i,j,k),r in np.ndenumerate(corr.reshape(3,2,4)):
                    rows.append((s,target,TIMES[i],["absolute","change"][j],BANDS[k],r))
    frame = pd.DataFrame(rows,columns=["participant","target","time","power","band","rho"])
    frame.to_csv(OUT/"participant_associations.csv",index=False)
    groups=frame.groupby(["target","time","power","band"]).rho
    summary=groups.agg(n="count",median="median",positive=lambda x:(x>0).sum(),
                       negative=lambda x:(x<0).sum(),q25=lambda x:x.quantile(.25),q75=lambda x:x.quantile(.75)).reset_index()
    summary.to_csv(OUT/"central_associations.csv",index=False)
    return summary


def plots(totals):
    plt.rcParams.update({"font.size":9,"axes.spines.top":False,"axes.spines.right":False})
    palette = ["#226c72","#bc6a30"]
    full = totals.query("panel == 'Full'")
    fig, axes = plt.subplots(3,1,figsize=(12,9),layout="constrained",height_ratios=[1.7,1,1])
    for ax, col, order in zip(axes,["channel","band","time"],[CHANNELS,BANDS,TIMES]):
        agg = full.pivot_table(index=col,columns="target",values="share",aggfunc="sum").reindex(order)
        agg[["Valence","Dominance"]].plot.bar(ax=ax,color=palette,rot=45 if col=="channel" else 0)
        ax.set_ylabel("Weight share (%)")
        ax.set_xlabel({"channel":"EEG channel","band":"Frequency band","time":"Time after stimulus onset (s)"}[col])
    fig.suptitle("32-channel Ridge | personal models across 32 participants")
    fig.savefig(OUT / "feature_weights.png",dpi=160); plt.close(fig)

    fig, axes = plt.subplots(2,2,figsize=(10,7),layout="constrained")
    matrices = []
    for target in ["Valence","Dominance"]:
        for panel in ["Central","Combined"]:
            tab = totals[(totals.target==target)&(totals.panel==panel)&totals.channel.isin(["C3","C4"])]
            matrices.append(tab.pivot_table(index="band",columns="time",values="share",aggfunc="sum")
                            .reindex(index=BANDS,columns=TIMES).fillna(0))
    for ax,table,title in zip(axes.flat,matrices,["Valence | Central","Valence | Combined","Dominance | Central","Dominance | Combined"]):
        im=ax.imshow(table,vmin=0,vmax=max(t.to_numpy().max() for t in matrices),cmap="Blues",aspect="auto")
        ax.set(title=title,xticks=range(3),xticklabels=TIMES,yticks=range(4),yticklabels=BANDS,xlabel="Time (s)")
        for r,c in np.ndindex(table.shape):
            val=table.iloc[r,c]
            ax.text(c,r,f"{val:.1f}",ha="center",va="center",color="white" if im.norm(val)>.62 else "black")
    fig.colorbar(im,ax=axes,label="Share of all model weights (%)")
    fig.suptitle("C3 + C4 | band and stimulus interval")
    fig.savefig(OUT / "central_band_time.png",dpi=160); plt.close(fig)

    d = pd.read_csv(OUT / "participant_differences.csv")
    fig, axes = plt.subplots(2,1,figsize=(11,5),layout="constrained")
    lim = d.central_added.abs().max()
    for ax,regime in zip(axes,REGIMES):
        tab = d[d.regime==regime].pivot(index="target",columns="participant",values="central_added").reindex(TARGETS)
        im=ax.imshow(tab,vmin=-lim,vmax=lim,cmap="RdBu",aspect="auto")
        ax.set(title=regime.replace("_"," "),xticks=range(32),xticklabels=range(1,33),yticks=range(5),yticklabels=TARGETS,xlabel="Participant")
    fig.colorbar(im,ax=axes,label="Frontal MAE minus combined MAE")
    fig.suptitle("Adding Central channels | blue = lower error; blank = missing")
    fig.savefig(OUT / "individual_effects.png",dpi=160); plt.close(fig)


def report(metrics, effects, totals, associations):
    lines = ["# DEAP의 Central 채널과 개인차", "",
             "기존 검증에서 사용한 실제 EEG 특징으로 Ridge를 학습했다. 동일한 시행과 폴드에서 전극 구성과 파워 표현만 바꿨다. "
             "Frontal은 F3/F4, Central은 C3/C4, 결합은 이 네 전극이다. 표준 라벨은 32명×40편, Familiarity는 s02·s15·s23을 제외한 29명×40편이다.", ""]
    baseline = pd.read_csv(ROOT/"results/metrics.csv").query("model == 'Median' and montage == '4ch'").set_index(["regime","target"])
    m = metrics.set_index(["regime","target","panel","mode"])
    e = effects.set_index(["regime","target","contrast"])
    for regime,title in REGIMES.items():
        tab = effects[(effects.regime==regime)&(effects.contrast=="central_added")]
        best = tab.loc[tab["mean"].idxmax()]
        improvements = ", ".join(tab.loc[tab["mean"]>0,"target"])
        lines += [f"**{title}.** Central 추가 후 평균 MAE가 감소한 라벨은 {improvements}였다. "
                  f"가장 큰 감소는 {best.target}의 {best['mean']:.3f}점이었고 {int(best.improved)}/{int(best.n)}명에서 개선됐다. "
                  f"해당 감소량의 참가자 재표집 구간은 [{best.lo:+.3f}, {best.hi:+.3f}]였다.", ""]
    lines += ["두 평가 모두 추가 효과의 95% 구간 전체가 양수인 라벨은 없었다. 새 참가자 Arousal은 오히려 오차가 커졌으며, "
              "개인 내 Dominance도 평균은 개선됐지만 개선 인원은 13/32명이었다. 작은 평균 이득을 공통된 생리 반응으로 해석하기 어렵다.", ""]
    def score(row):
        return f"{row.MAE:.3f} / {row.R2:.3f}"
    for regime, title in REGIMES.items():
        lines += ["## "+title,"","각 칸은 전체 보류 예측의 MAE / R²다. 아래 효과는 같은 참가자의 MAE를 짝지어 비교했다.","",
                  "|라벨|중앙값|Frontal|Central|결합|32채널|","|---|---:|---:|---:|---:|---:|"]
        for t in TARGETS:
            cells = [t,score(baseline.loc[(regime,t)])]+[score(m.loc[(regime,t,p,"joint")]) for p in PANELS]
            lines.append("|"+"|".join(cells)+"|")
        lines += ["","양수는 Central 단독 또는 Central 추가 후의 오차 감소다. 괄호는 개선 인원이다. 구간은 참가자 단위 10,000회 재표집한 평균 개선량의 95% 백분위 구간이다.","",
                  "|라벨|Frontal − Central MAE|Frontal − 결합 MAE|추가 효과 구간|","|---|---:|---:|---:|"]
        for t in TARGETS:
            a,b = [e.loc[(regime,t,k)] for k in ["central_vs_frontal","central_added"]]
            lines.append(f"|{t}|{a['mean']:+.3f} ({int(a.improved)}/{int(a.n)})|{b['mean']:+.3f} ({int(b.improved)}/{int(b.n)})|[{b.lo:+.3f}, {b.hi:+.3f}]|")
        lines += [""]
    lines += ["## 절대 파워와 기준선 변화량", "",
              "같은 2초 Welch 창에서 얻은 자극 구간 파워(dB)와 자극−3초 기준선(dB)을 각각 단독 입력하거나 함께 입력했다. 값은 MAE / R²다.","",
              "|평가|라벨|전극|절대 파워|기준선 변화량|두 표현 결합|","|---|---|---|---:|---:|---:|"]
    for regime,title in REGIMES.items():
        for t in ["Valence","Dominance"]:
            for p in PANELS:
                lines.append("|"+"|".join([title,t,p]+[score(m.loc[(regime,t,p,k)]) for k in ["absolute","change","joint"]])+"|")
    lines += ["","## 채널·대역·시간 구간과 개인차","",
              "개인별 외부 학습 폴드에서 선택된 16개 특징의 표준화 Ridge 계수를 사용했다. 각 폴드에서 절댓값 합을 100%로 두고, 미선택 특징에 0을 부여한 뒤 5개 폴드와 32명을 동일 가중 평균했다. 아래 비중은 모델이 사용한 가중치의 분포다. 방향 일치도는 같은 세부 특징이 5개 중 3개 이상 폴드에서 선택된 사람의 평균 계수 부호로 집계했다.",""]
    for t in ["Valence","Dominance"]:
        full=totals[(totals.target==t)&(totals.panel=="Full")]
        def top(col):
            s=full.groupby(col).share.sum().nlargest(2)
            return ", ".join(f"{k} {v:.1f}%" for k,v in s.items())
        lines += [f"- **{t}**. 32채널 모델에서 비중이 큰 채널은 {top('channel')}, 대역은 {top('band')}, 구간은 {top('time')}였다."]
        for panel in ["Central","Combined"]:
            sub=totals[(totals.target==t)&(totals.panel==panel)&totals.channel.isin(["C3","C4"])]
            bandtime=sub.groupby(["band","time"]).share.sum().idxmax()
            f=sub.loc[sub.share.idxmax()]
            lines += [f"  - {panel}에서 C3/C4의 합산 비중은 {sub.share.sum():.1f}%였다. 가장 큰 대역·시간 조합은 {bandtime[0]} {bandtime[1]}초였다. 개별 특징 중 {f.channel} {f.band} {f.time}초 {f.power}의 비중이 가장 컸고, 3개 이상 폴드에서 반복 선택된 사람 중 양의 계수 {f.positive}명, 음의 계수 {f.negative}명이었다."]
    lines += ["","### 실제 신호와 평정의 개인 내 연관성","",
              "C3/C4의 평균 dB 특징과 각 평정 사이의 Spearman ρ를 사람마다 40편에서 계산했다. 절대·변화 × 4대역 × 3구간의 24개 조합 중 참가자 ρ 중앙값의 절댓값이 가장 큰 예를 표시한다. 전체 조합은 central_associations.csv에 있다. 이 사후 기술통계는 예측 모델에 반영하지 않았다.",""]
    for target in ["Valence","Dominance"]:
        tab=associations[associations.target==target]
        a=tab.loc[tab["median"].abs().idxmax()]
        lines += [f"- {target}는 {a.band} {a.time}초 {a.power}에서 중앙값 ρ가 {a['median']:+.3f}였다. 개인별 중간 50% 범위는 [{a.q25:+.3f}, {a.q75:+.3f}]이고 양의 연관은 {a.positive}명, 음의 연관은 {a.negative}명이었다."]
    lines += ["","![채널·대역·시간](feature_weights.png)","","![Central 세부 비중](central_band_time.png)","","![개인별 추가 효과](individual_effects.png)","",
              "## 해석 범위와 재현","",
              "- 동일인의 미관측 영상은 개인별 외부 5분할, 미관측 참가자는 참가자 단위 외부 4분할이다. 내부 3분할에서도 같은 분리 단위를 유지했다. 각 내부 학습 폴드에서 표준화와 F 통계량 상위 16개 선택을 수행하고 Ridge α 10·100 중 검증 MAE로 선택했다. 위 특징 순위와 외부 결과를 재학습의 특징 선정에 사용하지 않았다.",
              "- 특정 참가자의 향상과 전체 평균의 향상은 서로 다른 결과다. 참가자 재표집 구간은 고정된 보류 예측의 기술적 불확실성으로, 새 학습 집단에서의 재훈련 변동이나 여러 라벨 비교에 대한 보정을 포함하지 않는다. 참가자 외 평가에서는 다른 참가자가 같은 영상을 본 기록이 학습에 들어간다.",
              "- 가중치와 예측 성능은 인과관계를 의미하지 않는다. 상관된 전극·시간 구간·파워 표현 사이에서 가중치가 나뉘거나 특징이 서로 대체될 수 있다. 비중은 뇌 활성량이나 신호 증가 방향을 나타내지 않는다. 전극 추가 비교에는 선택되는 16개 특징과 튜닝 결과의 변화도 포함된다.",
              "- 실제 4채널 장비의 전극 위치와 참조 방식은 DEAP F3/F4/C3/C4와 다를 수 있다. 음악 영상의 시각·청각 효과도 분리되지 않는다. 장비 간 전이나 시각 자극의 독립 효과는 이 결과로 검증되지 않았다.",
              "- BrainFicial 폴더에서 기존 분석용 Python으로 `interpret_eeg.py`, `summarize_eeg.py` 순서로 실행한다. metrics.csv와 participant_metrics.csv는 모든 조건의 MAE·R², participant_differences.csv는 개인별 대응 차이, fold_weights.csv는 선택된 학습 폴드별 계수다."]
    (OUT/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


if __name__ == "__main__":
    metrics = pd.read_csv(OUT/"metrics.csv")
    person = pd.read_csv(OUT/"participant_metrics.csv")
    effects = paired(person)
    totals = describe_weights()
    associations = central_associations()
    plots(totals)
    report(metrics,effects,totals,associations)
