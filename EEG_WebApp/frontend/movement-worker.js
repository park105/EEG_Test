let face, pose;
self.onmessage = async ({data}) => {
  const bitmap = data.bitmap;
  try {
    if (data.init) {
      const root = "/static/vendor/face/";
      const {FilesetResolver,FaceLandmarker,PoseLandmarker} = await import(root+"vision_bundle.js");
      const wasm = await FilesetResolver.forVisionTasks(root+"wasm");
      face = await FaceLandmarker.createFromOptions(wasm,{baseOptions:{modelAssetPath:root+"face_landmarker.task"},
        runningMode:"VIDEO",numFaces:1,outputFaceBlendshapes:true});
      pose = await PoseLandmarker.createFromOptions(wasm,{baseOptions:{modelAssetPath:root+"pose_landmarker_lite.task"},
        runningMode:"VIDEO",numPoses:1});
      postMessage({ready:true});
      return;
    }
    const values = face.detectForVideo(bitmap,data.time).faceBlendshapes[0]?.categories || [];
    const smiles = values.filter(v=>["mouthSmileLeft","mouthSmileRight"].includes(v.categoryName));
    const smile = smiles.length===2 ? (smiles[0].score+smiles[1].score)/2 : null;
    const points = pose.detectForVideo(bitmap,data.time).landmarks[0];
    let shoulder = null;
    if (points && [7,8,11,12].every(i=>points[i].visibility>=0.6 && points[i].x>=0 && points[i].x<=1 && points[i].y>=0 && points[i].y<=1)) {
      const [a,b]=[points[11],points[12]];
      const span=Math.hypot((a.x-b.x)*bitmap.width,(a.y-b.y)*bitmap.height);
      if(span>1) shoulder=(points[7].y+points[8].y-a.y-b.y)*bitmap.height/(2*span);
    }
    postMessage({smile,shoulder,phase:data.phase,elapsed_ms:data.elapsed_ms,epoch:data.epoch});
  } catch(err) { postMessage({error:String(err)}); }
  finally {bitmap?.close();}
};

