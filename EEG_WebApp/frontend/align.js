const el=id=>document.getElementById(id);
let sid,detail,fileId;
async function read(url,options){
 const response=await fetch(url,options);const data=await response.json();
 if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:JSON.stringify(data.detail));
 return data;
}
async function select(){
 sid=el("sessions").value;fileId=null;el("file").value="";el("channels").replaceChildren();
 if(!sid)return;detail=await read("/api/offline/"+sid);
 el("partial").hidden=detail.status==="finished";
 el("events").textContent="참가자 "+detail.participant+" · "+detail.status+"\n"+detail.records.flatMap(r=>r.events).map(e=>e.name+" · "+e.elapsed_s.toFixed(3)+"초"+(e.trial_index===null?"":" · 시행 "+(e.trial_index+1))).join("\n");
}
el("sessions").onchange=()=>select().catch(e=>el("status").textContent=e.message);
el("partial").onclick=async()=>{
 if(!confirm("이 기록이 다른 창에서 실행 중이면 먼저 그 창을 닫으세요. 지금까지 저장된 사진으로 종료할까요?"))return;
 try{await read("/api/offline/"+sid+"/finish-partial",{method:"POST"});await select();}
 catch(e){el("status").textContent=e.message;}
};
el("file").onchange=async()=>{
 fileId=null;const file=el("file").files[0];if(!sid||!file)return;
 el("analyze").disabled=true;
 try{
  const info=await read("/api/offline/"+sid+"/eeg",{method:"PUT",body:file});
  fileId=info.file_id;el("file-status").textContent=info.rows+"개 샘플";
  el("channels").replaceChildren();el("time").replaceChildren(new Option("없음 · 첫 샘플 0초",""));
  info.columns.forEach(c=>el("time").append(new Option(c,c)));
  for(const name of ["O1","Oz","O2","Pz"]){
   const label=document.createElement("label");label.textContent=name+" 입력 열 ";
   const select=document.createElement("select");select.dataset.channel=name;
   select.append(new Option("선택",""));select.required=true;info.columns.forEach(c=>select.append(new Option(c,c)));
   if(info.columns.includes(name))select.value=name;label.append(select);el("channels").append(label);
  }
 }catch(e){el("file-status").textContent=e.message;}
 finally{el("analyze").disabled=false;}
};
el("download").onclick=()=>{
 if(!detail)return;const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([JSON.stringify(detail,null,2)],{type:"application/json"}));a.download=sid+".json";a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);
};
el("form").onsubmit=async e=>{
 e.preventDefault();if(!fileId){el("status").textContent="EEG 파일을 먼저 올려 주세요.";return;}
 const channels={};document.querySelectorAll("[data-channel]").forEach(s=>channels[s.dataset.channel]=s.value);
 const body={file_id:fileId,channels,fs:Number(el("fs").value),unit:el("unit").value,time_column:el("time").value,time_unit:el("time-unit").value,
 web_anchor_s:Number(el("web1").value),eeg_anchor_s:Number(el("eeg1").value),
 web_anchor2_s:el("web2").value===""?null:Number(el("web2").value),eeg_anchor2_s:el("eeg2").value===""?null:Number(el("eeg2").value),method:el("method").value};
 el("analyze").disabled=true;el("status").textContent="정렬과 EEG 분석 중…";el("result").hidden=true;
 try{const data=await read("/api/offline/"+sid+"/align",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
 el("status").textContent="분석 완료 · 시계 비율 "+data.scale.toFixed(8);
 el("result").href="/static/field.html?session="+encodeURIComponent(data.session_id);el("result").hidden=false;
 }catch(e){el("status").textContent=e.message;}finally{el("analyze").disabled=false;}
};
(async()=>{const ids=await read("/api/offline");el("sessions").append(new Option("기록 선택",""));ids.forEach(s=>el("sessions").append(new Option(s,s)));})().catch(e=>el("status").textContent=e.message);

