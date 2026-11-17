"use strict";
const el = id => document.getElementById(id);
const target = ["O1", "Oz", "O2", "Pz"];
let streams = [], selected = null, fields = [];
function message(text) { el("message").textContent = text; }
async function request(url, body) {
  const options = body === undefined ? {} : {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)};
  const response = await fetch(url,options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "입력 이름·단위·선택을 확인해 주세요.");
  return data;
}
function changed() {
  el("start").hidden = true;
  el("confirm").checked = false;
  const names = fields.map(f=>f.name.value.trim());
  const missing = target.filter(ch=>!names.includes(ch));
  el("coverage").textContent = missing.length ? "4채널 Liking 모델에 필요한 위치: "+missing.join(", ")+" (선택한 EEG만 기록할 수 있습니다.)" : "O1 · Oz · O2 · Pz 모두 배정됨";
}
function draw(wires) {
  fields=[]; el("rows").replaceChildren(); el("panel").hidden=false;
  for (const [i,w] of wires.entries()) {
    const row = el("rows").insertRow();
    row.insertCell().textContent=String(i+1); row.insertCell().textContent=w.label || "미표기";
    const name=document.createElement("input"); name.setAttribute("list","sites"); name.placeholder="사용 안 함";
    name.setAttribute("aria-label","입력 "+(i+1)+" 전극 위치");
    name.value=target.find(c=>c.toLowerCase()===(w.label||"").toLowerCase()) || "";
    const unit=document.createElement("select"); unit.setAttribute("aria-label","입력 "+(i+1)+" 단위");
    for(const v of ["","uV","mV","V"]) unit.add(new Option(v||"단위 선택", v));
    const u=(w.unit||"").replace(/[µμ]/g,"u"); unit.value=["uV","mV","V"].includes(u)?u:"";
    row.insertCell().append(name); row.insertCell().append(unit);
    fields.push({name,unit}); name.oninput=unit.onchange=changed;
  }
  el("allunit").value=""; changed(); el("connect").disabled=!selected;
}
function wires() {
  const seen=new Set();
  return fields.map(f=>{
    let name=f.name.value.trim(); name=target.find(c=>c.toLowerCase()===name.toLowerCase())||name;
    if(name && (!f.unit.value || seen.has(name.toLowerCase()) || name.toLowerCase()==="timestamp_s")) throw new Error("기록 위치의 중복과 단위를 확인하세요.");
    seen.add(name.toLowerCase());
    return {name,kind:name?"EEG":"skip",unit:f.unit.value||"uV"};
  });
}
function pick(){
  selected=streams.find(s=>s.uid===el("sources").value)||null;
  if(selected){draw(selected.wires);message(selected.name+" · "+selected.fs+" Hz · "+selected.wires.length+"개 입력");}
  else {el("panel").hidden=true;el("start").hidden=true;}
}
el("scan").onclick=async()=>{
  el("scan").disabled=true; message("장비를 찾는 중…");selected=null;el("start").hidden=true;el("panel").hidden=true;el("sources").replaceChildren();
  try{streams=await request("/api/lab/streams");for(const s of streams)el("sources").add(new Option(s.name+" / "+s.host+" / "+s.fs+" Hz",s.uid));pick();if(!streams.length)message("송출 중인 LSL 장비가 없습니다. 제조사 프로그램의 LSL 출력과 네트워크를 확인하세요.");}
  catch(e){message(e.message);}finally{el("scan").disabled=false;}
};
el("sources").onchange=pick;
el("manual").onclick=()=>{const n=el("count").valueAsNumber;if(!Number.isInteger(n)||n<1||n>512)return message("입력 수는 1~512입니다.");selected=null;el("sources").selectedIndex=-1;draw(Array.from({length:n},()=>({})));message("오프라인 배선표입니다. 장비 검색 후 불러와 적용하세요.");};
el("allunit").onchange=()=>{for(const f of fields)f.unit.value=el("allunit").value;changed();};
el("save").onclick=()=>{try{const ws=wires();if(!ws.some(w=>w.name))throw new Error("기록할 전극을 지정하세요.");localStorage.setItem("brainficial.wiring",JSON.stringify(ws));message("이 브라우저에 배선표를 저장했습니다.");}catch(e){message(e.message);}};
el("restore").onclick=()=>{try{const ws=JSON.parse(localStorage.getItem("brainficial.wiring"));if(!ws||ws.length!==fields.length)throw new Error("같은 입력 수의 저장된 배선표가 없습니다.");ws.forEach((w,i)=>{fields[i].name.value=w.name;fields[i].unit.value=w.kind==="skip"?"":w.unit;});changed();message("불러온 위치와 단위가 현재 실제 배선과 맞는지 확인하세요.");}catch(e){message(e.message);}};
el("connect").onclick=async()=>{if(!selected||!el("confirm").checked)return message("실제 장비와 배선 확인 체크가 필요합니다.");el("connect").disabled=true;
try{const data=await request("/api/lab/layout",{uid:selected.uid,wires:wires()});message("신호 수신 확인 · "+data.fs+" Hz · "+data.channels.join(", "));el("start").hidden=false;}
catch(e){message(e.message);}finally{el("connect").disabled=!selected;}};
el("mock").onclick=async()=>{try{await request("/api/lab/rehearsal",{});location.href="/?quick=1";}catch(e){message(e.message);}};

