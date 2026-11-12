"""Participant-paired fixed-prediction bootstrap for MAE and pooled R² differences."""
import numpy as np
import pandas as pd

from run import OUT, WINDOWS, KEY


def summarize():
    df=pd.read_csv(OUT/"predictions.csv.gz")
    draws=np.random.default_rng(42).integers(0,32,(10000,32))
    metrics, people, contrasts, pairs = [], [], [], []
    for prefix,group in df.groupby(KEY[:3]):
        index=["participant","video"]
        truth=group.pivot(index=index,columns=["gamma","window"],values="truth")
        np.testing.assert_array_equal(truth.to_numpy(),np.broadcast_to(truth.iloc[:,0:1],truth.shape))
        predictions=group.pivot(index=index,columns=["gamma","window"],values="prediction")
        fold=group.pivot(index=index,columns=["gamma","window"],values="fold")
        assert fold.nunique(axis=1).eq(1).all() and truth.shape==(1280,10)
        subjects=truth.index.get_level_values(0).unique()
        assert truth.index.equals(pd.MultiIndex.from_product([range(1,33),range(1,41)],names=index))
        y=truth.iloc[:,0].to_numpy().reshape(32,40)
        sst=((y-y.mean())**2).sum()
        local_sst=((y-y.mean(axis=1,keepdims=True))**2).sum(axis=1)
        sampled_sst=(y**2).sum(axis=1)[draws].sum(axis=1)-y.sum(axis=1)[draws].sum(axis=1)**2/y.size
        med=group.drop_duplicates(index).set_index(index).reindex(truth.index)["median"].to_numpy().reshape(y.shape)
        median_mae=np.abs(med-y).mean(axis=1)
        median_sse=((med-y)**2).sum(axis=1)
        stats={}
        for model in predictions.columns:
            err=predictions[model].to_numpy().reshape(y.shape)-y
            mae=np.abs(err).mean(axis=1)
            sse=(err**2).sum(axis=1)
            stats[model]=(mae,sse)
            delta=median_mae-mae
            better=delta>0
            ci=np.quantile(delta[draws].mean(axis=1),[.025,.975])
            delta_sse=median_sse-sse
            ci_r2=np.quantile(delta_sse[draws].sum(axis=1)/sampled_sst,[.025,.975])
            metrics.append((*prefix,*model,mae.mean(),1-sse.sum()/sst,int(better.sum()),delta.mean(),
                            *ci,delta_sse.sum()/sst,*ci_r2))
            for i,s in enumerate(subjects):
                people.append((*prefix,*model,s,mae[i],1-sse[i]/local_sst[i] if local_sst[i]>0 else np.nan,better[i]))
        tests=[("gamma",("out",w),("in",w)) for w in WINDOWS]
        tests.extend(("time",(g,w),(g,"all")) for g in ("in","out") for w in WINDOWS if w!="all")
        for kind,base,candidate in tests:
            mae0,sse0=stats[base]
            mae1,sse1=stats[candidate]
            d=mae0-mae1
            delta_sse=sse0-sse1
            mae_ci=np.quantile(d[draws].mean(axis=1),[.025,.975])
            r2_ci=np.quantile(delta_sse[draws].sum(axis=1)/sampled_sst,[.025,.975])
            contrasts.append((*prefix,kind,*base,*candidate,d.mean(),*mae_ci,(d>0).sum(),(d<0).sum(),
                              delta_sse.sum()/sst,*r2_ci))
            for i,s in enumerate(subjects):
                pairs.append((*prefix,kind,*base,*candidate,s,d[i]))
    scores=pd.DataFrame(metrics,columns=KEY+["MAE","R2","better_than_training_median_n","MAE_gain_vs_median",
        "MAE_low_vs_median","MAE_high_vs_median","R2_gain_vs_median","R2_low_vs_median","R2_high_vs_median"])
    scores.to_csv(OUT/"metrics.csv",index=False)
    pd.DataFrame(people,columns=KEY+["participant","MAE","R2","better_than_training_median"]).to_csv(OUT/"participant_metrics.csv",index=False)
    names=KEY[:3]+["contrast","base_gamma","base_window","candidate_gamma","candidate_window"]
    table=pd.DataFrame(contrasts,columns=names+["MAE_gain","MAE_low","MAE_high","improved_n","worse_n","R2_gain","R2_low","R2_high"])
    pd.DataFrame(pairs,columns=names+["participant","MAE_gain"]).to_csv(OUT/"participant_differences.csv",index=False)
    table.to_csv(OUT/"paired_contrasts.csv",index=False)
    draw_effects(table)
    report(scores,table)
    print(len(metrics),"models;",len(table),"paired comparisons")


def draw_effects(table):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    panels=["Frontal","Central","Combined","Full"]
    fig,axes=plt.subplots(2,2,sharex=True,figsize=(10,6),layout="constrained")
    for i,regime in enumerate(["within_person","new_participant"]):
        for j,target in enumerate(["Valence","Dominance"]):
            ax=axes[i,j]
            subset=table[(table.regime==regime)&(table.target==target)]
            for mask,offset,label,color,marker in [
                ((subset.contrast=="gamma")&(subset.base_window=="all"),.12,"Add gamma","#16645c","o"),
                ((subset.base_gamma=="in")&(subset.base_window=="0-40"),-.12,"Add final 20 s","#a44823","s")]:
                r=subset[mask].set_index("panel").loc[panels]
                ax.errorbar(r.MAE_gain,np.arange(4)+offset,xerr=[r.MAE_gain-r.MAE_low,r.MAE_high-r.MAE_gain],
                            fmt=marker,color=color,capsize=3,label=label)
            ax.axvline(0,color="grey",linewidth=1)
            ax.set(yticks=range(4),yticklabels=panels,ylim=(3.6,-.6),title=f"{target} | {regime.replace('_',' ')}")
            if i==1:
                ax.set_xlabel("MAE reduction (rating points)")
    axes[0,0].legend(fontsize=8)
    fig.suptitle("Incremental performance | paired participant bootstrap, 95% intervals")
    fig.savefig(OUT/"effects.png",dpi=160)
    plt.close(fig)


def report(scores,table):
    lines=["# 감마와 영상 후반부의 예측 기여", "",
           "32명 × 영상 40편의 Valence·Dominance를 독립적으로 예측했다. 기존 EEG 특징과 Ridge 설정으로 각각의 입력 조건을 처음부터 재학습했다. "
           "감마는 30 이상 45 Hz 미만이다. 절대 파워와 기준선 대비 변화량 열을 함께 포함하거나 제거했다. 전체 시간 모델에는 세 구간의 특징이 각각 들어간다. "
           "후반의 추가 기여를 직접 측정하기 위해 0–40초 모델도 계산했다.","",
           "Frontal은 F3/F4, Central은 C3/C4, Combined는 이 네 채널, Full은 전체 32채널이다. 개인 내 평가는 참가자별 영상 외부 5분할, "
           "새 참가자는 참가자 단위 외부 4분할이다. 내부 3분할에서 표준화·F 점수 선택·Ridge α(10, 100) 튜닝을 수행했다. 특징 선택 수는 min(16, 입력 특징 수)다. "
           "각 모델의 외부 학습 폴드 전체에 선택된 설정을 재적합했다. 모든 조건의 평가 시행·폴드를 대조하고, 전체 구간·감마 포함 모델의 20,480개 보류 예측을 이전 실험과 1e-10 허용오차로 검증했다.","",
           "개선량은 기준 모델 MAE에서 비교 모델 MAE를 뺀 값이다. R² 개선량은 비교 모델 R²에서 기준 모델 R²를 뺀 값이다. "
           "참가자를 짝지어 10,000회 복원추출(시드 42)하고 95% 백분위 구간을 계산했다. R² 차이는 매 표본의 전체 보류 시행에서 다시 계산했다. "
           "구간은 이 영상과 고정된 교차검증 예측에 대한 기술적 구간이다. 새 영상 표집·모델 재훈련 변동과 다중 비교를 반영하지 않는다. "
           "선행 분석에서 같은 데이터의 가중치를 보고 세운 가설이므로 독립 표본 재현이 필요한 탐색 결과다.","",
           "![감마와 후반 구간의 추가 효과 및 참가자 단위 구간](effects.png)",""]
    lines += ["### 기존 계수 비중과 보류 예측 성능","",
              "개인 내 32채널 Valence에서는 감마 추가 시 MAE가 0.031점 감소했지만 대응 구간은 0을 포함했다. "
              "같은 조건에서 처음 40초에 마지막 20초를 추가하면 MAE가 0.045점 감소했고 구간은 0.011~0.081점이었다. "
              "32채널 Dominance에서 전체 구간 감마 추가 이득은 0.002점으로 작았다. 후반 단독은 전체보다 MAE가 0.030점 낮았지만 이 차이의 구간도 0을 포함했다.","",
              "개인 내 Valence에서 후반 추가 이득의 구간은 네 전극 구성 모두 양수였다. 새 참가자에서는 어느 구성에서도 같은 이득을 확인하기 어려웠고, "
              "Central 단독 Dominance에서는 후반 추가 후 오히려 0.019점 악화됐다. 계수가 집중된 대역·구간의 비중만으로 개인 밖의 예측 이득을 판단하기 어렵다.",""]
    for regime,title in [("within_person","개인 내 미관측 영상"),("new_participant","미관측 참가자")]:
        lines += ["## "+title,"","각 칸은 MAE / R² / 학습 중앙값보다 개인 MAE가 작은 인원(32명 중)이다.","",
                  "|라벨|채널|감마|전체|0–20초|20–40초|40–60초|0–40초|","|---|---|---|---:|---:|---:|---:|---:|"]
        for (t,p,g),d in scores[scores.regime==regime].groupby(["target","panel","gamma"]):
            by=d.set_index("window")
            cells=[]
            for w in WINDOWS:
                r=by.loc[w]
                cells.append(f"{r.MAE:.3f} / {r.R2:.3f} / {int(r.better_than_training_median_n)}")
            lines.append("|"+"|".join([t,p,"포함" if g=="in" else "제외",*cells])+"|")
        lines += ["","아래는 전체 구간에서 감마를 추가한 효과와 감마 포함 상태에서 마지막 20초를 추가한 효과다. "
                  "각 칸은 MAE 개선량 [95% 구간] 및 개선 인원이다.","",
                  "|라벨|채널|감마 추가|후반 추가|","|---|---|---:|---:|"]
        for (t,p),d in table[table.regime==regime].groupby(["target","panel"]):
            cells=[]
            for mask in [(d.contrast=="gamma")&(d.base_window=="all"),(d.base_gamma=="in")&(d.base_window=="0-40")]:
                r=d[mask].iloc[0]
                cells.append(f"{r.MAE_gain:+.3f} [{r.MAE_low:+.3f}, {r.MAE_high:+.3f}] · {r.improved_n}/32")
            lines.append("|"+"|".join([t,p,*cells])+"|")
        lines += [""]
    lines += ["## 근전도와 해석 범위","",
              "전처리 MATLAB 파일의 큰광대근·승모근 EMG(1부터 센 채널 35·36)에서도 EEG와 같은 2초 Welch 창으로 구간별 30–45 Hz 절대 파워를 계산했다. "
              "각 사람의 40개 영상 안에서 전극 구성별 평균 EEG 감마 dB와 근육별 EMG 감마 dB 사이의 Spearman 상관을 계산했다. EMG와 이 결과는 모델의 입력이나 특징 선택에 쓰이지 않았다. "
              "[DEAP의 센서 배치](https://www.sanderkoelstra.nl/media/documents/Thesis_final_RAL_Koelstra.pdf) · [DEAP 채널 번호](https://openreview.net/pdf/8a045a606abf89ad24e81dea7ff199c2cb5fe88a.pdf)",""]
    emg=pd.read_csv(OUT/"emg_summary.csv")
    for r in emg[(emg.panel=="Full")&(emg.window=="40-60")].itertuples():
        lines.append(f"- 32채널 후반 {r.muscle} 상관 중앙값 {r.median:+.3f}, 개인별 사분위 범위 [{r.q25:+.3f}, {r.q75:+.3f}], 양의 상관 {r.positive}/{r.n}명.")
    lines += ["","EEG와 EMG가 같은 자극에 함께 반응하거나 근육 전위가 두피 전극에 섞일 수 있다. 두 근육의 상관만으로는 개별 감마 특징의 신경·근육 성분 비율이나 "
              "성능 향상의 원인을 식별할 수 없다. 감마 제거는 예측기가 이용할 수 있는 정보와 선택 후보 수를 함께 바꾼다. 두피 고주파 EEG의 근육 혼입은 근신경 차단 실험에서도 관찰됐다. [Whitham 등 원 연구](https://pubmed.ncbi.nlm.nih.gov/17574912/)","",
              "## 파일과 재실행","","BrainFicial 폴더에서 기존 분석 환경의 Python으로 ablation/run.py, ablation/check_emg.py, ablation/summarize.py를 차례로 실행한다. "
              "metrics.csv와 participant_metrics.csv는 모델별·개인별 성능, paired_contrasts.csv는 모든 감마·구간 비교의 개선·악화 인원과 MAE·R² 차이 및 구간, "
              "participant_differences.csv는 개인별 대응 차이다. predictions.csv.gz에는 시행별 보류 예측과 선택 α가 있다."]
    (OUT/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


if __name__=="__main__":
    summarize()
