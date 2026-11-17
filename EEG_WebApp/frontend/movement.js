const fieldMonitor=new BroadcastChannel("brainficial-operator");
const movement = (() => {
  let worker, stream, timer, busy=false, phase=null, start=0, epoch=0, rows=[], active=false, used=false;
  const video=document.querySelector("#cam-preview"), status=document.querySelector("#cam-status");
  function stop(text="카메라 꺼짐") {
    clearInterval(timer); worker?.terminate(); worker=null;
    stream?.getTracks().forEach(t=>t.stop()); stream=null;video.srcObject=null;
    active=false;busy=false;status.textContent=text;
    document.querySelector("#cam-on").disabled=false;
    fieldMonitor.postMessage({camera:text});
  }
  async function enable() {
    const button=document.querySelector("#cam-on");button.disabled=true;
    try {
      if(!document.querySelector("#cam-consent").checked) throw Error("영상 기반 움직임 측정 동의를 확인하세요.");
      stream=await navigator.mediaDevices.getUserMedia({video:{width:{ideal:640},height:{ideal:480},facingMode:"user"},audio:false});
      video.srcObject=stream;await video.play();
      stream.getVideoTracks()[0].onended=()=>stop("카메라 연결 해제");
      status.textContent="안면·어깨 모델 준비 중…";
      worker=new Worker("/static/movement-worker.js");
      worker.onerror=e=>stop("모델 실행 오류: "+e.message);
      worker.onmessage=({data})=>{
        if(data.error){stop("추적 오류: "+data.error);return;}
        if(data.ready){active=true;status.textContent="얼굴과 양쪽 어깨를 카메라에 맞추세요.";return;}
        busy=false;
        if(data.phase && data.epoch===epoch) rows.push({phase:data.phase,elapsed_ms:data.elapsed_ms,smile:data.smile,shoulder:data.shoulder});
        const fmt=v=>v===null?"미검출":v.toFixed(2);
        const label="입꼬리 "+fmt(data.smile)+" · 어깨 "+fmt(data.shoulder);
        status.textContent=label;fieldMonitor.postMessage({camera:label});
      };
      worker.postMessage({init:true});
      timer=setInterval(async()=>{
        if(!active||busy||video.readyState<2)return;
        busy=true;
        try{const time=performance.now(), payload={time,epoch,phase,elapsed_ms:Math.max(0,time-start)};
          const bmp=await createImageBitmap(video);
          if(!worker){bmp.close();return;}
          worker.postMessage({...payload,bitmap:bmp},[bmp]);
        }catch(e){stop("프레임 읽기 오류: "+e.message);}
      },220);
    }catch(e){stop(e.message);}
  }
  document.querySelector("#cam-on").onclick=enable;
  document.querySelector("#cam-off").onclick=()=>stop();
  document.querySelector("#cam-consent").onchange=e=>{if(!e.target.checked)stop();};
  window.addEventListener("pagehide",()=>stop());
  return {mark(name,tr,time){
    fieldMonitor.postMessage({phase:name,photo:tr.stimulus_id||""});
    if(name==="fixation_onset"){epoch++;rows=[];used=active;}
    phase=["fixation_onset","stimulus_onset","stimulus_offset"].includes(name)?name:null;
    start=time;
  },snapshot(id){phase=null;return {stimulus_id:id,camera_enabled:used||rows.length>0,samples:[...rows]};},stop};
})();

