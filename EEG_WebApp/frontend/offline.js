const el=id=>document.getElementById(id);
let session, origin, pending=[], current=null, running=false, records=[], saving=false;
const clock=()=> (performance.now()-origin)/1000;
async function request(url,body,method="POST"){
 const response=await fetch(url,body===undefined?{}:{method,headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
 const data=await response.json();if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:JSON.stringify(data.detail));return data;
}
function mark(name){
 const elapsed=clock();
 pending.push({name,elapsed_s:elapsed,epoch_ms:Date.now(),trial_index:current});
 movement.mark(name,{stimulus_id:current===null?"":session.trials[current].id},performance.now());
}
function sync(){
 if(!running||saving)return;
 pending.push({name:"sync",elapsed_s:clock(),epoch_ms:Date.now(),trial_index:null});
 el("sync").textContent="표시됨 · "+clock().toFixed(3)+"초 (S)";
}
el("sync").onclick=sync;
document.addEventListener("keydown",e=>{if(e.key.toLowerCase()==="s")sync();});
async function persist(number,capture=null){
 saving=true;
 const payload={events:pending.splice(0),capture};
 records.push(payload);
 localStorage.setItem("brainficial.offline."+session.session_id,JSON.stringify({session,records}));
 for(;;){
  try{await request("/api/offline/"+session.session_id+"/records/"+number,payload,"PUT");break;}
  catch(e){el("countdown").textContent="저장 실패 · "+e.message;await new Promise(resolve=>{const b=document.createElement("button");b.textContent="같은 기록 다시 저장";b.onclick=()=>{b.remove();resolve();};el("stage").append(b);});}
 }
 saving=false;
}
async function interval(name,seconds){
 mark(name);
 const end=performance.now()+seconds*1000;
 while(performance.now()<end){
  el("countdown").textContent=Math.ceil((end-performance.now())/1000)+"초";
  await new Promise(r=>setTimeout(r,50));
 }
}
function choose(labels){
 el("choices").replaceChildren();el("choices").hidden=false;
 return new Promise(resolve=>labels.forEach(([label,value])=>{
  const b=document.createElement("button");b.textContent=label;b.onclick=()=>{el("choices").hidden=true;resolve(value);};el("choices").append(b);
 }));
}
async function run(){
 if(!el("consent").checked||!el("pid").checkValidity()||!el("pid").value.trim()){el("message").textContent="참가자 ID와 동의를 확인하세요.";return;}
 el("begin").disabled=true;
 try{
  session=await request("/api/offline",{participant:el("pid").value,stimuli:el("set").value,quick:el("quick").checked});
  // Decode before starting the presentation clock.
  const images=await Promise.all(session.trials.map(async t=>{const img=new Image();img.src=t.src;await img.decode();return img;}));
  origin=performance.now();running=true;el("stage").hidden=false;el("sync").hidden=false;
  mark("recording_start");await interval("baseline_start",session.timing.baseline_s);mark("baseline_end");await persist(0);
  for(let i=0;i<session.trials.length;i++){
   current=i;el("progress").textContent=(i+1)+" / "+session.trials.length;
   el("cross").hidden=false;el("photo").hidden=true;await new Promise(requestAnimationFrame);
   await interval("fixation_onset",3);
   el("cross").hidden=true;el("photo").src=images[i].src;el("photo").hidden=false;
   await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
   await interval("stimulus_onset",4);
   el("photo").hidden=true;await new Promise(requestAnimationFrame);await interval("stimulus_offset",3);
   const capture=movement.snapshot(session.trials[i].id);
   mark("rating_shown");el("countdown").textContent="얼마나 마음에 들었나요? 1 매우 싫음 · 5 보통 · 9 매우 좋음";
   capture.live_liking=await choose(Array.from({length:9},(_,i)=>[String(i+1),i+1]));
   await persist(i+1,capture);current=null;
   if(i===15&&session.trials.length>16){mark("pause_start");el("countdown").textContent="잠시 쉬어가세요. 준비되면 계속하세요.";await choose([["계속",true]]);mark("pause_end");}
  }
  mark("recording_end");await persist(session.trials.length+1);
  running=false;movement.stop();el("stage").hidden=true;el("sync").hidden=true;
  el("message").textContent="기록 저장 완료 · "+session.session_id+" · EEG 연결 화면에서 같은 기록을 선택하세요.";
  el("export").hidden=false;
 }catch(e){el("message").textContent=e.message;el("begin").disabled=false;}
}
el("begin").onclick=run;
el("export").onclick=()=>{
 const blob=new Blob([JSON.stringify({session,records},null,2)],{type:"application/json"});
 const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=session.session_id+".json";a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);
};
window.addEventListener("beforeunload",e=>{if(running){e.preventDefault();e.returnValue="";}});

