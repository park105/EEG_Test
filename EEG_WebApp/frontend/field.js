const el=id=>document.getElementById(id);
const fmt=v=>Number.isFinite(v)?v.toFixed(2):"—";
const node=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
const cat={nature:"자연",city:"도시",animal:"동물",food:"음식"};
let id=new URLSearchParams(location.search).get("session"),result,papers;
async function request(url,body){
  const r=await fetch(url,body?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}:{});
  const data=await r.json();if(!r.ok)throw Error(typeof data.detail==="string"?data.detail:"입력값을 확인하세요.");return data;
}
const endpoint=()=>"/api/sessions/"+encodeURIComponent(id)+"/paper";
function metrics(p){
  el("errors").replaceChildren();
  el("metrics").textContent=p?`비교 가능한 ${p.level==="photo"?"사진":"범주"} ${p.n}개 · MAE ${fmt(p.mae)}점 · RMSE ${fmt(p.rmse)}점 · ±1점 이내 ${Number.isFinite(p.within_one)?Math.round(p.within_one*100)+"%":"—"} (1–9점 환산)`:"";
  for(const r of p?.rows||[])el("errors").append(node("p",`${cat[r.key]||r.key} · 설문 환산 ${fmt(r.target)} / EEG ${fmt(r.prediction)} / 차이 ${fmt(r.error)}`));
}
function inputs(){
  const level=el("level").value,p=papers[level], box=el("scores");box.replaceChildren();
  el("scale").value=p?.scale||9;metrics(p);
  const seen=new Set();
  for(const r of result.items){
    const key=level==="photo"?r.stimulus_id:r.category;if(!key||seen.has(key))continue;seen.add(key);
    const label=node("label",level==="photo"?r.title+" ("+key+")":cat[key]||key);
    label.className="field"; const input=node("input","");input.type="number";input.step="any";input.min=1;input.max=el("scale").value;input.dataset.key=key;input.value=p?.scores[key]??"";
    label.append(input);box.append(label);
  }
}
async function init(){
  const ids=await request("/api/field/sessions");el("sessions").append(new Option("기록을 선택하세요",""));
  ids.forEach(key=>el("sessions").append(new Option(key,key)));
  el("sessions").onchange=()=>location.assign("?session="+encodeURIComponent(el("sessions").value));
  if(!id){el("status").textContent=ids.length?"완료한 세션을 선택하세요.":"아직 완료한 측정이 없습니다.";return;}
  const data=await request(endpoint());result=data.result;papers=data.papers;el("sessions").value=id;
  el("status").textContent=(result.synthetic?"모의 EEG · ":"")+"참가자 "+result.participant_id+" · "+id;
  el("analysis").hidden=el("survey").hidden=false;
  result.items.sort((a,b)=>a.trial_index-b.trial_index);
  el("summary").textContent=`측정 ${result.n_trials}회 · 4채널 예측 ${result.items.filter(r=>Number.isFinite(r.posterior_liking)).length}회 · ${result.posterior_liking_note||""}`;
  const assoc=result.camera_associations||{};
  el("assoc").textContent=["smile_delta","shoulder_delta"].map((k,i)=>`감마와 ${i?"어깨":"입꼬리"} 변화의 순위상관 ρ ${fmt(assoc[k]?.rho)} (사진 ${assoc[k]?.n||0}개)`).join(" · ");
  for(const r of result.items){
    const tr=node("tr",""), c=r.camera||{};
    const label=node("td",r.title+" ("+r.stimulus_id+")");
    if(r.src?.startsWith("/")){const img=document.createElement("img");img.src=r.src;img.width=64;img.alt="";label.prepend(img);}
    tr.append(label,...[fmt(r.posterior_liking),fmt(r.gamma_db),...["smile","shoulder"].map(k=>fmt(c[k+"_delta"])+" ("+(c[k+"_base_n"]||0)+"/"+(c[k+"_photo_n"]||0)+")")].map(v=>node("td",v)));el("trials").append(tr);
  }
  el("level").onchange=inputs;el("scale").onchange=()=>document.querySelectorAll("#scores input").forEach(i=>i.max=el("scale").value);
  inputs();
  el("paper").onsubmit=async e=>{e.preventDefault();const scores={};for(const i of document.querySelectorAll("#scores input"))if(i.value!=="")scores[i.dataset.key]=Number(i.value);
    try{const p=await request(endpoint(),{level:el("level").value,scale:Number(el("scale").value),scores});papers[p.level]=p;metrics(p);}catch(err){el("metrics").textContent=err.message;}};
}
init().catch(e=>el("status").textContent=e.message);
