/* EEG 선호도 측정 웹앱 (빌드 도구 없이 동작하는 단일 페이지)
 * 두 가지 방식
 *   장비 모드:  시작 → ① 설문 → ② 연결·신호 확인·기준선 → ③ 안내·자극 시행 → ④ 추론 → ⑤ 결과
 *   파일 모드:  시작 → ① 설문(선택) → ② EEG·이벤트 파일 올리기 → ④ 추론 → ⑤ 결과
 * 개발용: 주소 뒤에 ?quick=1 → 기준선 10초, 시행 4개.
 * 새로고침해도 진행 중인 세션은 시작 화면에서 "이어서 하기"로 돌아올 수 있다.
 */
const $ = (s) => document.querySelector(s);
const QUICK = new URLSearchParams(location.search).has("quick");
const STORE_KEY = "eeg-webapp-session";
const RATING_SECONDS = 5; // 예상 시간 계산용 평정 소요(초)
const S = {
  config: null, mode: "device", session: null, participant: "", trials: [], nextTrial: 0, answers: {},
  uploads: {}, ratingsNeeded: false,
  // 장비 상태: streaming = 서버 기준 "최근 2초 안에 실제 샘플이 들어옴", at = 그 소식을 받은 시각
  dev: { connectedOnce: false, streaming: false, at: 0, error: null }, rejected: false,
  ws: null, wsEverOpen: false, quality: [], pauseRequested: false, stopRequested: false, result: null,
};

const LABEL_KO = { like: "선호", dislike: "비선호", neutral: "중립", uncertain: "불확실",
  unavailable: "측정 불가", unknown: "-" };
const AGREE_KO = { agree: "설문과 일치", disagree: "설문과 어긋남", undecided: "판단 보류" };
const AGREE_RATING_KO = { agree: "평정과 일치", disagree: "평정과 어긋남", undecided: "판단 보류" };
const STEPS = {
  device: [["survey", "설문"], ["device", "연결·기준선"], ["trials", "자극 측정"], ["inference", "추론"], ["results", "결과"]],
  upload: [["survey", "설문(선택)"], ["upload", "데이터 올리기"], ["inference", "추론"], ["results", "결과"]],
};
const CAT_KO = { nature: "자연", city: "도시", animal: "동물", food: "음식" };
const CAT_ORDER = ["nature", "city", "animal", "food"];
const QUALITY_KO = { good: "양호", fair: "보통", bad: "불량", unknown: "확인 중" };

/* ---------------- 공통 ---------------- */
async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(errText(data.detail) || res.statusText);
  return data;
}
// FastAPI 검증 오류(detail이 배열)도 읽을 수 있는 문장으로
const errText = (d) => (Array.isArray(d) ? d.map((x) => x.msg).join(", ") : d);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// 화면에 실제로 그려진 직후에 마커를 보내기 위한 대기 (두 프레임)
const afterPaint = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pct = (v) => (v === null || v === undefined ? "-" : `${Math.round(v * 100)}%`);
const fmtMin = (sec) => (sec < 60 ? `${Math.round(sec)}초` : `약 ${Math.round(sec / 60)}분`);

let toastTimer;
function toast(msg, ms = 4000) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.hidden = true), ms);
}

const store = {
  save() {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({ session: S.session, participant: S.participant,
        trials: S.trials.map(({ preload, ...t }) => t), quick: QUICK }));
    } catch (e) { /* 저장 불가 환경: 이어하기만 안 됨 */ }
  },
  load() { try { return JSON.parse(localStorage.getItem(STORE_KEY) || "null"); } catch (e) { return null; } },
  clear() { try { localStorage.removeItem(STORE_KEY); } catch (e) { /* noop */ } },
};

function renderSteps() {
  $("#steps").innerHTML = STEPS[S.mode].map(([k, lbl], i) =>
    `<li data-step="${k}"><span class="num">${i + 1}</span><span class="lbl">${lbl}</span></li>`).join("");
}

function show(view) {
  document.querySelectorAll(".view").forEach((v) => (v.hidden = v.id !== `view-${view}`));
  const order = STEPS[S.mode].map(([k]) => k);
  const idx = order.indexOf(view);
  document.querySelectorAll("#steps li").forEach((li) => {
    const i = order.indexOf(li.dataset.step);
    li.classList.toggle("active", i === idx);
    li.classList.toggle("done", idx > -1 && i < idx);
    if (i === idx) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
  });
  window.scrollTo({ top: 0 });
}

function timing() {
  const T = S.config.timing;
  return { ...T, baseline_s: QUICK ? 10 : T.baseline_s };
}
function trialSeconds() {
  const T = timing();
  return T.fixation_s + T.stimulus_s + T.recovery_s + RATING_SECONDS;
}

/* ---------------- 시작 ---------------- */
async function init() {
  S.config = await api("/api/config");
  updateSourceBadge(S.config.device);
  renderSteps();
  renderOverview();
  renderSurvey();
  setupDevice();
  setupUpload();
  document.querySelectorAll('input[name="mode"]').forEach((r) => (r.onchange = () => setMode(r.value)));
  setMode(document.querySelector('input[name="mode"]:checked').value);
  const check = () => ($("#btn-start").disabled = !($("#participant").value.trim() && $("#consent").checked));
  $("#participant").addEventListener("input", check);
  $("#consent").addEventListener("change", check);
  $("#participant").addEventListener("keydown", (e) => { if (e.key === "Enter" && !$("#btn-start").disabled) startSession(); });
  $("#btn-start").onclick = startSession;
  $("#btn-begin-trials").onclick = () => runTrials();
  $("#btn-retry").onclick = finish;
  show("start");
  await checkResume();
}

function setMode(mode) {
  S.mode = mode;
  renderSteps(); renderOverview();
  const up = mode === "upload";
  $("#consent-text").textContent = up
    ? "올리는 EEG 데이터를 이 용도로 쓸 권한이 있고, 서버에 저장되는 것에 동의합니다."
    : "실험 안내를 듣고 참여와 EEG·응답 저장에 동의합니다. 언제든 중단할 수 있어요.";
  $("#btn-start").textContent = up ? "파일로 시작하기" : "시작하기";
  $("#btn-skip-survey").hidden = !up;
  $("#btn-survey").textContent = up ? "다음: 데이터 올리기" : "다음: 장비 연결";
  $("#survey-desc").textContent = up
    ? "답하면 EEG 추정을 평소 취향과 비교해요. 건너뛰면 파일 속 본인 평정과만 비교해요. 1(전혀 아님)–9(매우)."
    : "실험에 나올 사진은 미리 보여드리지 않아요. 평소 취향을 1(전혀 아님)부터 9(매우)까지 골라 주세요.";
  if (up) updateSourceBadge({ kind: "upload" }); else updateSourceBadge(S.config.device);
  updateSurveyProgress();
}

function renderOverview() {
  if (S.mode === "upload") {
    $("#overview").innerHTML = [
      ["평소 취향 설문", `선택 · ${S.config.survey.length}문항`, "1분"],
      ["EEG 파일 올리기", "CSV·TSV, 시각 열 + 채널 열", ""],
      ["이벤트 파일 올리기", "자극 시각과 평정(1–9 또는 1–5)", ""],
      ["결과 보기", "EEG 기반 추정과 설문·평정 비교", "몇 초"],
    ].map(([a, b, t]) => `<li><span><b>${a}</b> <span class="muted small">${b}</span></span><span class="t">${t}</span></li>`).join("");
    return;
  }
  const T = timing();
  const n = QUICK ? Math.min(4, S.config.n_stimuli) : S.config.n_stimuli;
  const steps = [
    ["평소 취향 설문", `${S.config.survey.length}문항`, 60],
    ["장비 연결과 신호 확인", "전극 상태 점검", 120],
    ["휴식 기준선", "화면 중앙 + 응시", T.baseline_s],
    ["사진 감상과 평가", `${n}장 · 중간 휴식 1회`, n * trialSeconds()],
    ["결과 보기", "EEG 기반 추정과 설문 비교", 0],
  ];
  $("#overview").innerHTML = steps.map(([a, b, s]) =>
    `<li><span><b>${a}</b> <span class="muted small">${b}</span></span><span class="t">${s ? fmtMin(s) : ""}</span></li>`).join("");
}

function updateSourceBadge(dev) {
  const b = $("#source-badge");
  if (dev.kind === "upload") {
    b.textContent = "파일 데이터"; b.classList.remove("synthetic"); b.title = "업로드한 EEG 파일로 추론";
    return;
  }
  const synthetic = !!dev.synthetic || dev.kind === "mock";
  b.textContent = synthetic ? "모의 EEG" : `장비: ${dev.kind}`;
  b.classList.toggle("synthetic", synthetic);
  b.title = synthetic ? "실제 장비 없이 합성 신호로 동작 중" : "";
}

async function checkResume() {
  const saved = store.load();
  if (!saved || !saved.session || saved.quick !== QUICK) return;
  let p;
  try { p = await api(`/api/sessions/${saved.session}/progress`); } catch (e) { return; }
  if (!p.active) { store.clear(); return; }
  const done = p.completed_trials.length;
  $("#resume-detail").textContent = `참가자 ${saved.participant} · ` +
    (p.baseline_done ? `사진 ${done}/${saved.trials.length}장 완료` : p.survey_done ? "설문 완료" : "설문 전");
  $("#resume-box").hidden = false;
  $("#btn-discard").onclick = () => { store.clear(); $("#resume-box").hidden = true; };
  $("#btn-resume").onclick = () => resume(saved, p);
}

function resume(saved, p) {
  S.session = saved.session; S.participant = saved.participant;
  S.trials = saved.trials; preload(S.trials);
  const doneSet = new Set(p.completed_trials);
  S.nextTrial = S.trials.findIndex((t) => !doneSet.has(t.trial_index));
  if (S.nextTrial < 0) S.nextTrial = S.trials.length;
  if (!p.survey_done) return show("survey");
  if (!p.recording || !p.baseline_done) {
    show("device");
    if (p.recording) afterConnected(p.device, false);
    return;
  }
  openSocket(); updateSourceBadge(p.device);
  S.dev = { connectedOnce: true, streaming: !!p.device.streaming, at: performance.now(), error: p.device.error || null };
  if (S.nextTrial >= S.trials.length) return finish();
  showTrialIntro();
}

function preload(trials) {
  trials.forEach((t) => { const im = new Image(); im.src = t.src; t.preload = im; });
}

async function startSession() {
  $("#btn-start").disabled = true;
  if (S.mode === "upload") {
    try {
      const res = await api("/api/uploads", { participant_id: $("#participant").value.trim() });
      S.session = res.session_id; S.participant = $("#participant").value.trim();
      S.uploads = {}; S.answers = {};
      show("survey");
    } catch (e) {
      toast(`시작할 수 없어요: ${e.message}`);
      $("#btn-start").disabled = false;
    }
    return;
  }
  try {
    const res = await api("/api/sessions", { participant_id: $("#participant").value.trim() });
    S.session = res.session_id; S.participant = $("#participant").value.trim();
    S.trials = QUICK ? res.trials.slice(0, 4) : res.trials;
    S.nextTrial = 0;
    preload(S.trials);
    store.save();
    show("survey");
  } catch (e) {
    toast(`시작할 수 없어요: ${e.message}`);
    $("#btn-start").disabled = false;
  }
}

/* ---------------- ① 설문 ---------------- */
function renderSurvey() {
  const form = $("#survey-form");
  const items = S.config.survey;
  let section = "";
  items.forEach((item, idx) => {
    if (item.section !== section) {
      section = item.section;
      form.insertAdjacentHTML("beforeend", `<div class="survey-section">${esc(section)}</div>`);
    }
    const div = document.createElement("div");
    div.className = "survey-item";
    div.id = `q-${item.id}`;
    div.innerHTML = `<div class="q-text" id="qt-${item.id}">${esc(item.text)}</div>
      <div class="likert" role="radiogroup" aria-labelledby="qt-${item.id}"></div>
      <div class="likert-labels"><span>1 전혀 아님</span><span>5 보통</span><span>9 매우</span></div>`;
    const group = div.querySelector(".likert");
    for (let v = 1; v <= 9; v++) {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = v;
      b.setAttribute("role", "radio"); b.setAttribute("aria-checked", "false");
      b.onclick = () => {
        const first = !(item.id in S.answers);
        S.answers[item.id] = v;
        group.querySelectorAll("button").forEach((x) => {
          x.classList.toggle("sel", x === b); x.setAttribute("aria-checked", String(x === b));
        });
        div.classList.add("answered");
        updateSurveyProgress();
        // 처음 답한 문항이면 다음 미응답 문항으로 부드럽게 이동
        const next = items.slice(idx + 1).find((it) => !(it.id in S.answers));
        if (first && next) document.getElementById(`q-${next.id}`).scrollIntoView({ behavior: "smooth", block: "center" });
      };
      group.appendChild(b);
    }
    form.appendChild(div);
  });
  updateSurveyProgress();
  $("#btn-survey").onclick = async (e) => {
    e.preventDefault();
    try {
      await api(`/api/sessions/${S.session}/survey`, S.answers);
      show(S.mode === "upload" ? "upload" : "device");
    } catch (err) { toast(`설문을 저장하지 못했어요: ${err.message}`); }
  };
  $("#btn-skip-survey").onclick = (e) => {
    e.preventDefault();
    if (Object.keys(S.answers).length && !confirm("입력한 설문 응답을 저장하지 않고 넘어갈까요?")) return;
    S.answers = {};
    show("upload");
  };
}

function updateSurveyProgress() {
  const n = Object.keys(S.answers).length, total = S.config.survey.length;
  $("#survey-progress").textContent = `${n} / ${total} 응답`;
  // 파일 모드에서는 일부만 답해도 넘어갈 수 있다(답한 문항만 비교에 쓴다)
  $("#btn-survey").disabled = S.mode === "upload" ? n === 0 : n < total;
}

/* ---------------- ② 연결·신호 확인·기준선 ---------------- */
function setupDevice() {
  const T = timing();
  $("#baseline-desc").textContent = `${fmtMin(T.baseline_s)} 동안 화면 중앙의 + 를 편하게 바라보며 쉬어요. 이 구간이 개인 기준 뇌파가 돼요.`;
  $("#btn-connect").onclick = async () => {
    $("#btn-connect").disabled = true;
    S.connecting = true;
    $("#device-info").textContent = "연결 중… 장비에서 데이터가 들어오는지 확인하고 있어요.";
    try {
      const dev = await api(S.dev.connectedOnce ? "/api/device/reconnect" : "/api/device/connect", {});
      await api(`/api/sessions/${S.session}/recording/start`, {});
      afterConnected(dev, !S.dev.connectedOnce);
    } catch (e) {
      $("#device-info").textContent = `연결하지 못했어요. ${e.message}`;
      $("#device-info").classList.add("error");
      $("#btn-connect").disabled = false;
      $("#btn-connect").textContent = "다시 연결";
    }
    S.connecting = false;
  };
  $("#btn-baseline").onclick = runBaseline;
  setInterval(updateGate, 400);
}

// 지금 측정을 진행해도 되는 상태인지. 연결 버튼을 눌렀다는 사실이 아니라 실제 데이터 수신으로 판단한다.
function deviceState() {
  if (!S.dev.connectedOnce) return { ok: false, reason: "장비를 먼저 연결해 주세요." };
  if (!S.ws || S.ws.readyState !== WebSocket.OPEN || performance.now() - S.dev.at > 2500)
    return { ok: false, reason: "서버와 연결이 끊겼어요. 서버가 켜져 있는지 확인해 주세요." };
  if (!S.dev.streaming)
    return { ok: false, reason: `장비 연결이 끊겼어요${S.dev.error ? ` (${S.dev.error})` : ""}.` };
  return { ok: true, reason: "" };
}

// ② 화면: 연결돼 데이터가 들어올 때만 기준선 버튼을 연다. 끊기면 다시 잠그고 "다시 연결"을 보여 준다.
function updateGate() {
  if ($("#view-device").hidden) return;
  const st = deviceState();
  $("#btn-baseline").disabled = !st.ok;
  const g = $("#gate-msg");
  g.textContent = st.ok ? "장비 연결됨 · 데이터 수신 중" : `${st.reason} 연결돼야 다음으로 넘어갈 수 있어요.`;
  g.className = `gate-msg ${st.ok ? "ok" : "blocked"}`;
  if (!S.dev.connectedOnce || S.connecting) return;
  $("#btn-connect").disabled = st.ok;
  $("#btn-connect").textContent = st.ok ? "연결됨" : "다시 연결";
  $("#scope-empty").hidden = st.ok;
  // 끊긴 뒤 남아 있는 파형·품질은 지난 값이므로 흐리게 한다
  document.querySelector(".scope-wrap").classList.toggle("lost", !st.ok);
  $("#quality").classList.toggle("lost", !st.ok);
  if (!st.ok) $("#scope-empty").textContent = "신호가 끊겼어요. 장비를 확인하고 다시 연결해 주세요.";
}

function afterConnected(dev, fresh) {
  updateSourceBadge(dev);
  S.dev = { connectedOnce: true, streaming: true, at: performance.now(), error: null };
  $("#device-info").classList.remove("error");
  $("#btn-connect").disabled = true;
  $("#btn-connect").textContent = "연결됨";
  $("#device-info").textContent = `${dev.kind} · ${dev.channels.length}채널 · ${dev.fs} Hz` + (dev.synthetic ? " · 합성 신호" : "") + (fresh ? "" : " · 기록 이어서 진행 중");
  $("#scope-empty").hidden = true;
  openSocket();
  updateGate();
}

function openSocket() {
  if (S.ws) return;
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onopen = () => { S.wsEverOpen = true; setConn(true); };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "signal" || msg.type === "quality") { S.dev.streaming = !!msg.streaming; S.dev.at = performance.now(); }
    if (msg.type === "quality") S.dev.error = msg.error || null;
    if (msg.type === "marker_rejected") { S.dev.streaming = false; S.rejected = true; }
    if (msg.type === "signal" && msg.streaming) drawScope(msg);
    if (msg.type === "quality") renderQuality(msg);
  };
  ws.onclose = () => { S.ws = null; if (S.wsEverOpen) setConn(false); setTimeout(openSocket, 1000); };
  S.ws = ws;
}

function setConn(ok) {
  const c = $("#conn");
  c.hidden = ok;
  c.querySelector(".txt").textContent = "서버 연결 끊김 · 다시 연결 중";
}

// 시점 마커: 서버가 EEG와 같은 시계로 시각을 찍는다. 소켓이 끊겼으면 REST로 보낸다.
function marker(name, trial = {}) {
  const m = { type: "marker", name, trial_index: trial.trial_index ?? null,
    stimulus_id: trial.stimulus_id ?? null, client_ts_ms: performance.now() };
  if (S.ws && S.ws.readyState === WebSocket.OPEN) S.ws.send(JSON.stringify(m));
  else api(`/api/sessions/${S.session}/markers`, m).catch(() => { S.rejected = true; toast("마커를 보내지 못했어요. 서버 연결을 확인하세요."); });
}

function renderQuality(msg) {
  if (!msg.channels.length) return;
  S.quality = msg.channels;
  const counts = { good: 0, fair: 0, bad: 0 };
  msg.channels.forEach((c) => { if (c.status in counts) counts[c.status]++; });
  const icon = { good: "✓", fair: "!", bad: "✕" };
  $("#quality-summary").innerHTML = msg.error ? `<span class="qchip bad">✕ ${esc(msg.error)}</span>` :
    ["good", "fair", "bad"].map((k) => `<span class="qchip ${k}">${icon[k]} ${QUALITY_KO[k]} ${counts[k]}</span>`).join("");
  $("#quality").innerHTML = msg.channels.map((c) => `<div class="qcell ${c.status}" title="${esc(c.message)}">
      <b>${esc(c.channel)}</b> <span class="q ${c.status}">${QUALITY_KO[c.status]}</span>
      <div class="muted">${c.std_uv !== undefined ? `σ ${c.std_uv} µV` : esc(c.message)}</div></div>`).join("");
}

function drawScope(msg) {
  const cv = $("#scope"), ctx = cv.getContext("2d");
  const dpr = devicePixelRatio || 1;
  const w = (cv.width = cv.clientWidth * dpr), h = (cv.height = cv.clientHeight * dpr);
  ctx.clearRect(0, 0, w, h);
  const css = getComputedStyle(document.documentElement);
  const n = msg.channels.length, rowH = h / n, scale = rowH / 120; // 한 줄 ±60 µV
  const bad = new Set(S.quality.filter((q) => q.status === "bad").map((q) => q.channel));
  ctx.font = `${11 * dpr}px sans-serif`;
  msg.data.forEach((ch, i) => {
    const y0 = rowH * (i + 0.5);
    ctx.fillStyle = css.getPropertyValue("--muted"); ctx.fillText(msg.channels[i], 6 * dpr, y0 + 4 * dpr);
    ctx.strokeStyle = css.getPropertyValue(bad.has(msg.channels[i]) ? "--bad" : "--series-1");
    ctx.lineWidth = 1.2 * dpr; ctx.beginPath();
    ch.forEach((v, k) => {
      const x = 44 * dpr + (k / ch.length) * (w - 50 * dpr);
      const y = y0 - Math.max(-60, Math.min(60, v)) * scale;
      k ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    });
    ctx.stroke();
  });
}

async function runBaseline() {
  const st = deviceState();
  if (!st.ok) { toast(st.reason); updateGate(); return; }
  const bad = S.quality.filter((c) => c.status === "bad").map((c) => c.channel);
  if (bad.length && !confirm(`신호가 불량한 채널이 있어요: ${bad.join(", ")}\n그래도 진행할까요?`)) return;
  const seconds = timing().baseline_s;
  const stage = enterStage();
  $("#fixation").hidden = false;
  const meter = $("#baseline-meter");
  meter.hidden = false; meter.firstElementChild.style.width = "0%";
  await afterPaint();
  S.rejected = false;
  marker("baseline_start");
  let lost = 0;
  for (let s = 0; s < seconds; s++) {
    $("#stage-msg").textContent = `편안히 화면 중앙의 + 를 봐주세요 · ${seconds - s}초`;
    meter.firstElementChild.style.width = `${((s + 1) / seconds) * 100}%`;
    await sleep(1000);
    lost = deviceState().ok && !S.rejected ? 0 : lost + 1;
    if (lost >= 2) {  // 2초 넘게 데이터가 없으면 이 기준선은 쓸 수 없다 → 중단하고 연결 화면으로
      marker("baseline_abort");
      meter.hidden = true; $("#fixation").hidden = true;
      leaveStage();
      show("device"); updateGate();
      toast("장비 연결이 끊겨 기준선 측정을 중단했어요. 다시 연결한 뒤 처음부터 측정해 주세요.", 9000);
      return;
    }
  }
  marker("baseline_end");
  meter.hidden = true;
  leaveStage();
  showTrialIntro();
}

/* ---------------- ③ 안내 → 자극 시행 ---------------- */
function showTrialIntro() {
  const T = timing();
  const left = S.trials.length - S.nextTrial;
  $("#trial-intro-count").textContent = S.nextTrial > 0
    ? `남은 사진 ${left}장을 이어서 볼게요. 예상 시간 ${fmtMin(left * trialSeconds())}.`
    : `사진 ${left}장을 한 장씩 보고 평가해요. 예상 시간 ${fmtMin(left * trialSeconds())}.`;
  $("#trial-timeline").innerHTML = [
    ["+ 응시", `${T.fixation_s}초`, ""], ["사진 감상", `${T.stimulus_s}초`, "stim"],
    ["빈 화면", `${T.recovery_s}초`, ""], ["평가", "좋아요 1–9 · 본 적 있음", ""],
  ].map(([a, b, c]) => `<li class="${c}"><b>${a}</b><span>${b}</span></li>`).join("");
  $("#btn-begin-trials").textContent = S.nextTrial > 0 ? "이어서 측정" : "측정 시작";
  show("trials");
}

function enterStage() {
  const stage = $("#stage");
  stage.hidden = false;
  stage.classList.remove("interactive");
  $("#rating").hidden = true; $("#pause").hidden = true; $("#stim-img").hidden = true;
  $("#stage-msg").textContent = "";
  stage.requestFullscreen?.().catch(() => {});
  return stage;
}
function leaveStage() {
  $("#stage").hidden = true;
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("#stage").hidden && $("#pause").hidden && S.running) {
    S.pauseRequested = true;  // 지금 시행은 끝까지 진행하고 평가 뒤에 멈춘다
    if (!$("#rating").hidden) $("#stage-msg").textContent = "평가 후 잠시 멈춰요";
  }
});

async function runTrials() {
  const stage = enterStage();
  S.running = true; S.stopRequested = false;
  const T = timing();
  const n = S.trials.length;
  const breakAt = n >= 12 ? Math.floor(n / 2) : -1;
  setStageProgress(S.nextTrial / n);
  for (let i = S.nextTrial; i < n; i++) {
    const tr = S.trials[i];
    if (!(await ensureDevice())) break;   // 장비가 끊겼으면 다시 연결될 때까지 다음 사진으로 넘어가지 않는다
    S.rejected = false;
    stage.classList.remove("interactive");
    $("#rating").hidden = true; $("#pause").hidden = true; $("#stim-img").hidden = true;
    $("#stage-progress").hidden = true;
    $("#stage-msg").textContent = "";
    // 고정점
    $("#fixation").hidden = false;
    await afterPaint(); marker("fixation_onset", tr);
    await sleep(T.fixation_s * 1000);
    if (S.rejected || !deviceState().ok) { marker("trial_aborted", tr); i--; continue; }
    // 자극 (영상 type: "video"는 확장 예정 → README 참고)
    $("#stim-img").src = tr.src;
    await tr.preload?.decode?.().catch(() => {});
    $("#fixation").hidden = true; $("#stim-img").hidden = false;
    await afterPaint(); marker("stimulus_onset", tr);
    await sleep(T.stimulus_s * 1000);
    // 회복(빈 화면)
    $("#stim-img").hidden = true;
    await afterPaint(); marker("stimulus_offset", tr);
    // 사진을 보는 동안 끊겼으면 이 시행은 쓸 수 없다 → 평가 없이 멈추고, 다시 연결되면 같은 사진부터
    if (S.rejected || !deviceState().ok) { marker("trial_aborted", tr); i--; continue; }
    await sleep(T.recovery_s * 1000);
    // 평정
    marker("rating_shown", tr);
    const r = await askRating(i);
    try {
      await api(`/api/sessions/${S.session}/ratings`, { trial_index: tr.trial_index, stimulus_id: tr.stimulus_id, ...r });
    } catch (e) { toast(`평가를 저장하지 못했어요: ${e.message}`); }
    S.nextTrial = i + 1;
    setStageProgress(S.nextTrial / n);
    if (S.nextTrial < n && (S.pauseRequested || S.nextTrial === breakAt)) {
      const isBreak = !S.pauseRequested;
      S.pauseRequested = false;
      await pauseScreen(isBreak);
      if (S.stopRequested) break;
    }
  }
  S.running = false;
  leaveStage();
  await finish();
}

function setStageProgress(frac) {
  $("#stage-progress").firstElementChild.style.width = `${frac * 100}%`;
}

// 시행 직전 장비 확인. 정상이면 바로 통과, 끊겼으면 "다시 연결" 화면에서 기다린다. false = 측정 끝내기 선택.
async function ensureDevice() {
  for (let k = 0; k < 6 && !deviceState().ok; k++) await sleep(250);  // 소켓이 막 열린 순간의 공백은 기다려 준다
  if (deviceState().ok) return true;
  const stage = $("#stage");
  stage.classList.add("interactive");
  $("#rating").hidden = true; $("#fixation").hidden = true; $("#stim-img").hidden = true; $("#stage-msg").textContent = "";
  $("#stage-progress").hidden = false;
  $("#pause-title").textContent = "장비 연결이 끊겼어요";
  $("#pause").hidden = false;
  const cont = $("#btn-continue"), rec = $("#btn-reconnect");
  let note = "";
  return new Promise((resolve) => {
    const refresh = () => {
      const st = deviceState();
      cont.hidden = !st.ok; rec.hidden = st.ok;
      $("#pause-title").textContent = st.ok ? "다시 연결됐어요" : "장비 연결이 끊겼어요";
      $("#pause-text").textContent = st.ok
        ? `${S.nextTrial} / ${S.trials.length}장 완료. 준비되면 이어서 진행해 주세요. 끊긴 사진은 처음부터 다시 보여드려요.`
        : `${st.reason} 장비 전원과 연결을 확인한 뒤 '다시 연결'을 눌러 주세요. 연결되기 전에는 다음 사진으로 넘어가지 않아요.${note}`;
    };
    const timer = setInterval(refresh, 400);
    refresh();
    const done = (ok) => {
      clearInterval(timer); document.removeEventListener("keydown", onKey);
      $("#pause").hidden = true; cont.hidden = false; rec.hidden = true;
      if (!ok) S.stopRequested = true;
      resolve(ok);
    };
    const onKey = (e) => { if (e.code === "Space" && deviceState().ok) { e.preventDefault(); done(true); } };
    document.addEventListener("keydown", onKey);
    cont.onclick = () => { if (deviceState().ok) done(true); };
    rec.onclick = async () => {
      rec.disabled = true; rec.textContent = "연결 중…"; note = "";
      try {
        const dev = await api("/api/device/reconnect", {});
        S.dev = { connectedOnce: true, streaming: !!dev.streaming, at: performance.now(), error: null };
      } catch (e) { note = ` (${e.message})`; }
      rec.disabled = false; rec.textContent = "다시 연결";
      refresh();
    };
    $("#btn-stop").onclick = () => {
      if (confirm("측정을 여기서 끝내고 지금까지의 결과를 볼까요?")) done(false);
    };
  });
}

function pauseScreen(isBreak) {
  const stage = $("#stage");
  stage.classList.add("interactive");
  $("#btn-continue").hidden = false; $("#btn-reconnect").hidden = true;
  $("#rating").hidden = true; $("#fixation").hidden = true; $("#stage-msg").textContent = "";
  $("#stage-progress").hidden = false;
  $("#pause-title").textContent = isBreak ? "절반 왔어요! 잠시 쉬어가요" : "일시정지";
  $("#pause-text").textContent = `${S.nextTrial} / ${S.trials.length}장 완료. 눈을 깜박이고 자세를 편하게 한 뒤 계속해 주세요.`;
  $("#pause").hidden = false;
  marker("pause_start");
  return new Promise((resolve) => {
    const done = (stop) => {
      document.removeEventListener("keydown", onKey);
      $("#pause").hidden = true;
      marker("pause_end");
      S.stopRequested = stop;
      resolve();
    };
    const onKey = (e) => { if (e.code === "Space") { e.preventDefault(); done(false); } };
    document.addEventListener("keydown", onKey);
    $("#btn-continue").onclick = () => done(false);
    $("#btn-stop").onclick = () => {
      if (confirm("측정을 여기서 끝내고 지금까지의 결과를 볼까요?")) done(true);
    };
    $("#btn-continue").focus();
  });
}

function askRating(i) {
  const stage = $("#stage");
  stage.classList.add("interactive");
  $("#rating").hidden = false; $("#fixation").hidden = true;
  $("#stage-progress").hidden = false;
  $("#stage-msg").textContent = S.pauseRequested ? "평가 후 잠시 멈춰요" : "";
  $("#trial-counter").textContent = `${i + 1} / ${S.trials.length}`;
  const scale = $("#liking-scale");
  scale.innerHTML = "";
  for (let v = 1; v <= 9; v++) scale.insertAdjacentHTML("beforeend", `<button data-v="${v}" role="radio" aria-checked="false">${v}</button>`);
  let liking = null, seen = null;
  const btn = $("#btn-rating");
  const refresh = () => {
    scale.querySelectorAll("button").forEach((b) => {
      const on = +b.dataset.v === liking; b.classList.toggle("sel", on); b.setAttribute("aria-checked", String(on));
    });
    $("#seen-scale").querySelectorAll("button").forEach((b) => {
      const on = seen !== null && +b.dataset.seen === +seen; b.classList.toggle("sel", on); b.setAttribute("aria-checked", String(on));
    });
    btn.disabled = liking === null || seen === null;
  };
  refresh();
  return new Promise((resolve) => {
    const done = () => {
      if (btn.disabled) return;
      document.removeEventListener("keydown", onKey);
      resolve({ liking, seen_before: seen });
    };
    const onKey = (e) => {
      if (/^[1-9]$/.test(e.key)) liking = +e.key;
      else if (e.key.toLowerCase() === "y") seen = true;
      else if (e.key.toLowerCase() === "n") seen = false;
      else if (e.key === "Enter") { e.preventDefault(); return done(); }
      else return;
      refresh();
    };
    document.addEventListener("keydown", onKey);
    scale.onclick = (e) => { const b = e.target.closest("button"); if (b) { liking = +b.dataset.v; refresh(); } };
    $("#seen-scale").onclick = (e) => { const b = e.target.closest("button"); if (b) { seen = b.dataset.seen === "1"; refresh(); } };
    btn.onclick = done;
  });
}

/* ---------------- ② 데이터 파일 올리기 (파일 모드) ---------------- */
const fmtBytes = (b) => (b > 1 << 20 ? `${(b / (1 << 20)).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);

function setupUpload() {
  document.querySelectorAll(".drop").forEach((drop) => {
    const kind = drop.dataset.kind, input = drop.querySelector("input");
    renderDrop(kind);
    drop.onclick = (e) => { if (!e.target.closest("a,button")) input.click(); };
    drop.tabIndex = 0;
    drop.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } };
    input.onchange = () => { if (input.files[0]) uploadFile(kind, input.files[0]); input.value = ""; };
    drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
    drop.ondragleave = () => drop.classList.remove("over");
    drop.ondrop = (e) => {
      e.preventDefault(); drop.classList.remove("over");
      const f = e.dataTransfer.files[0]; if (f) uploadFile(kind, f);
    };
  });
  $("#btn-demo").onclick = useDemo;
  $("#btn-run-upload").onclick = runUpload;
  $("#opt-fs").oninput = refreshUploadState;
}

function renderDrop(kind, progress) {
  const body = $(`#drop-${kind} .drop-body`);
  const u = S.uploads[kind];
  $(`#drop-${kind}`).classList.toggle("ok", !!(u && !u.error));
  $(`#drop-${kind}`).classList.toggle("err", !!(u && u.error));
  if (progress !== undefined) {
    body.innerHTML = `<div class="up-bar"><span style="width:${Math.round(progress * 100)}%"></span></div>
      <div class="muted small">${progress < 1 ? `올리는 중 ${Math.round(progress * 100)}%` : "형식 확인 중…"}</div>`;
    return;
  }
  if (!u) {
    body.innerHTML = `<div class="drop-empty">파일을 끌어다 놓거나 <u>눌러서 선택</u></div>`;
    return;
  }
  if (u.error) {
    body.innerHTML = `<div class="fname">${esc(u.name)}</div><div class="error small">${esc(u.error)}</div>
      <div class="muted small">다른 파일을 끌어다 놓거나 눌러서 다시 선택</div>`;
    return;
  }
  const chips = [];
  if (kind === "eeg") {
    chips.push(`${u.channels.length}채널`, u.fs_est ? `${u.fs_est} Hz` : "Hz 입력 필요",
      u.duration_s !== null ? fmtMin(u.duration_s) : `${u.rows.toLocaleString()}행`);
    if (u.feature_channels_present.length) chips.push(`특징 채널 ${u.feature_channels_present.join("·")}`);
  } else if (kind === "events") {
    chips.push(u.format === "webapp_markers" ? "웹앱 markers.csv" : "events 형식", `시행 ${u.trials}개`);
    if (u.rated !== null) chips.push(`평정 ${u.rated}개${u.scale_guess ? ` (${u.scale_guess}점)` : ""}`);
    chips.push(`자극 목록과 일치 ${u.matched_stimuli}/${u.trials}`);
  } else {
    chips.push(`${u.rows}행`);
  }
  body.innerHTML = `<div class="fname"><span class="okmark" aria-hidden="true">✓</span>${esc(u.name)}
      ${u.bytes ? `<span class="muted small">${fmtBytes(u.bytes)}</span>` : ""}</div>
    <div class="chips">${chips.map((c) => `<span class="chip">${esc(c)}</span>`).join("")}</div>
    ${kind === "eeg" ? `<div class="muted small ch-list" title="${esc(u.channels.join(", "))}">${esc(u.channels.join(", "))}</div>` : ""}`;
}

function uploadFile(kind, file) {
  $("#upload-error").textContent = "";
  renderDrop(kind, 0);
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", `/api/uploads/${S.session}/files/${kind}?name=${encodeURIComponent(file.name)}`);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) renderDrop(kind, e.loaded / e.total); };
    xhr.upload.onload = () => renderDrop(kind, 1);
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch (e) { /* noop */ }
      S.uploads[kind] = xhr.status < 300 ? data : { name: file.name, error: errText(data.detail) || `오류 ${xhr.status}` };
      afterUpload(kind);
      resolve();
    };
    xhr.onerror = () => { S.uploads[kind] = { name: file.name, error: "서버에 보내지 못했어요." }; afterUpload(kind); resolve(); };
    xhr.send(file);
  });
}

function afterUpload(kind) {
  const u = S.uploads[kind];
  renderDrop(kind);
  if (kind === "eeg" && u && !u.error) {
    $("#opt-unit").value = u.unit_guess || "uV";
    $("#opt-fs").placeholder = u.fs_est ? `자동 (${u.fs_est})` : "직접 입력";
  }
  if (kind === "events" && u && !u.error) {
    S.ratingsNeeded = u.format === "webapp_markers";
    $("#drop-ratings").hidden = !S.ratingsNeeded;
    if (u.scale_guess) $("#opt-scale").value = "auto";
  }
  refreshUploadState();
}

function refreshUploadState() {
  const ok = (k) => S.uploads[k] && !S.uploads[k].error;
  const eeg = S.uploads.eeg;
  const needFs = ok("eeg") && !eeg.fs_est && !(+$("#opt-fs").value > 0);
  $("#btn-run-upload").disabled = !(ok("eeg") && ok("events")) || needFs;
  const warns = ["eeg", "events", "ratings"].flatMap((k) => (ok(k) ? S.uploads[k].warnings || [] : []));
  if (needFs) warns.unshift("EEG 파일에 시각 열이 없어 샘플링 레이트를 입력해야 해요.");
  if (ok("eeg") && ok("events") && S.uploads.events.time_range && eeg.t_start !== null) {
    const [a, b] = S.uploads.events.time_range;
    const relative = a >= 0 && b <= eeg.duration_s + 1;
    if ((a < eeg.t_start || b > eeg.t_end) && !relative)
      warns.push(`이벤트 시각(${a.toFixed(1)}–${b.toFixed(1)}s)이 EEG 기록 범위(${eeg.t_start.toFixed(1)}–${eeg.t_end.toFixed(1)}s)를 벗어나요.`);
  }
  const ul = $("#upload-warnings");
  ul.hidden = !warns.length;
  ul.innerHTML = warns.map((w) => `<li>${esc(w)}</li>`).join("");
}

async function useDemo() {
  $("#btn-demo").disabled = true;
  $("#upload-error").textContent = "";
  ["eeg", "events"].forEach((k) => renderDrop(k, 1));
  try {
    const res = await api(`/api/uploads/${S.session}/demo`, {});
    S.uploads = { eeg: res.eeg, events: res.events };
    $("#drop-ratings").hidden = true;
    ["eeg", "events"].forEach(afterUpload);
    toast("예시(모의 합성) 파일을 넣었어요. 실제 뇌파가 아니에요.");
  } catch (e) {
    $("#upload-error").textContent = e.message;
    ["eeg", "events"].forEach((k) => renderDrop(k));
  }
  $("#btn-demo").disabled = false;
}

async function runUpload() {
  const fs = +$("#opt-fs").value;
  const opts = { fs: fs > 0 ? fs : null, unit: $("#opt-unit").value, rating_scale: $("#opt-scale").value };
  show("inference");
  $("#inference-error").textContent = ""; $("#btn-retry").hidden = true;
  try {
    renderResults(await api(`/api/uploads/${S.session}/run`, opts));
  } catch (e) {
    show("upload");
    $("#upload-error").textContent = `계산하지 못했어요: ${e.message}`;
  }
}

/* ---------------- ④ 추론 → ⑤ 결과 ---------------- */
async function finish() {
  show("inference");
  $("#inference-error").textContent = ""; $("#btn-retry").hidden = true;
  try {
    const result = await api(`/api/sessions/${S.session}/finish`, {});
    store.clear();
    renderResults(result);
  } catch (e) {
    $("#inference-error").textContent = `계산하지 못했어요: ${e.message}`;
    $("#btn-retry").hidden = false;
  }
}

// 비교 기준: 설문이 있으면 설문, 파일 모드에서 설문을 건너뛰었으면 본인 평정
function basisOf(r) {
  const bySurvey = r.has_survey !== false || !r.rating_agreement_counts;
  return bySurvey
    ? { key: "agreement", counts: r.agreement_counts, ko: AGREE_KO, what: "설문" }
    : { key: "rating_agreement", counts: r.rating_agreement_counts, ko: AGREE_RATING_KO, what: "본인 평정" };
}

function renderResults(r) {
  S.result = r;
  if (r.mode && r.mode !== S.mode) { S.mode = r.mode; renderSteps(); }
  show("results");
  const B = basisOf(r);
  const c = B.counts, m = r.model;
  const decided = c.agree + c.disagree;
  $("#result-headline").textContent = decided
    ? `판단할 수 있었던 사진 ${decided}장 중 ${c.agree}장에서 EEG 추정이 ${B.what}과 일치했어요`
    : `EEG 추정과 ${B.what}을 비교할 수 있는 사진이 없었어요`;
  const files = r.mode === "upload" && r.upload_files ? ` · ${r.upload_files}` : "";
  $("#result-sub").textContent = `참가자 ${r.participant_id}${r.mode === "upload" ? " · 업로드 데이터" : ""}${files} · 분석 가능한 시행 ${r.n_usable}/${r.n_trials}개 · ${m.description}`;
  $("#synthetic-banner").hidden = !r.synthetic;
  const notes = [...(r.upload_warnings || [])];
  if (m.channel_note) notes.push(m.channel_note);
  $("#result-notes").hidden = !notes.length;
  $("#result-notes").innerHTML = notes.map((w) => `<li>${esc(w)}</li>`).join("");
  const total = c.agree + c.disagree + c.undecided || 1;
  const bar = $("#agree-bar");
  bar.innerHTML = ["agree", "disagree", "undecided"].filter((k) => c[k])
    .map((k) => `<span class="${k}" style="flex:${c[k] / total}" title="${B.ko[k]} ${c[k]}장"></span>`).join("");
  bar.setAttribute("aria-label", `${B.ko.agree} ${c.agree}장, 어긋남 ${c.disagree}장, 판단 보류 ${c.undecided}장`);

  const stats = [
    [`<span class="legend-dot agree"></span>${B.ko.agree}`, `${c.agree}장`, ""],
    [`<span class="legend-dot disagree"></span>${B.ko.disagree}`, `${c.disagree}장`, ""],
    [`<span class="legend-dot undecided"></span>판단 보류`, `${c.undecided}장`, `${B.what}이 중립·없음이거나 EEG 신뢰도가 낮음`],
  ];
  if (m.balanced_accuracy_vs_rating !== undefined)
    stats.push(["본인 평정 대비 정확도", pct(m.balanced_accuracy_vs_rating), "우연 수준 50%"]);
  if (m.auc_vs_rating !== undefined && m.auc_vs_rating !== null)
    stats.push(["본인 평정 대비 AUC", m.auc_vs_rating, "우연 수준 0.5"]);
  const ig = r.integrity && r.integrity.eeg;
  if (ig) stats.push(["데이터 점검", `누락 ${ig.lost_percent}%`,
    r.integrity.markers && r.integrity.markers.status === "ok" ? `마커 흔들림 ${r.integrity.markers.spread_ms_sd}ms` : ""]);
  $("#summary").innerHTML = stats.map(([k, v, s]) =>
    `<div class="stat"><div class="k">${k}</div><div class="v">${esc(v)}</div>${s ? `<div class="s">${esc(s)}</div>` : ""}</div>`).join("");

  $("#model-note").innerHTML = `${esc(m.note || "")} ` +
    (m.model_channels ? `모델 채널: ${esc(m.model_channels.join(", "))} (${esc(m.model_window)}).`
      : `특징: ${esc(m.feature_channels.join(", "))} 채널 밴드파워(θ·α·β) · ${esc(m.feature_backend)}.`) +
    (m.deap_skipped ? `<br>DEAP 모델 미사용: ${esc(m.deap_skipped)}` : "");
  $("#disclaimer").textContent = r.disclaimer;

  renderCategoryChart(r.items);
  renderGrid(r.items, B);
  $("#btn-csv").onclick = () => download(`${r.session_id}_results.csv`, toCSV(r.items), "text/csv");
  $("#btn-json").onclick = () => download(`${r.session_id}_results.json`, JSON.stringify(r, null, 2), "application/json");
  $("#btn-print").onclick = () => window.print();
  $("#btn-restart").onclick = () => { store.clear(); location.href = location.pathname + location.search; };
}

function mean(xs) { const v = xs.filter((x) => x !== null && x !== undefined); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; }

function renderCategoryChart(items) {
  const cats = CAT_ORDER.filter((k) => items.some((it) => it.category === k))
    .concat([...new Set(items.map((it) => it.category))].filter((k) => k && !CAT_ORDER.includes(k)));
  const rows = cats.map((k) => {
    const g = items.filter((it) => it.category === k);
    return { k, n: g.length, p: mean(g.map((it) => it.eeg_like_probability)), survey: mean(g.map((it) => it.survey_expected)),
      rating: mean(g.map((it) => it.rating)), agree: g.filter((it) => it.agreement === "agree").length };
  });
  const el = $("#cat-chart");
  if (!rows.length) {
    el.innerHTML = `<p class="empty">자극 ID가 자극 목록(manifest)과 달라 카테고리별 비교는 생략했어요.</p>`;
    return;
  }
  el.innerHTML = `<div class="head"></div><div class="head">EEG 기반 추정 선호 확률(평균)</div><div class="head">설문 기대 · 본인 평정</div>` +
    rows.map((r, i) => `<div class="name">${esc(CAT_KO[r.k] || r.k)}</div>
      <div class="cat-track"><div class="ref"></div>
        ${r.p === null ? `<span class="val muted" style="left:0">측정 불가</span>` :
          `<div class="bar" style="width:${r.p * 100}%"></div><span class="val" style="left:${r.p * 100}%">${pct(r.p)}</span>`}
        <div class="hit" data-i="${i}"></div></div>
      <div class="nums">설문 ${r.survey === null ? "-" : r.survey.toFixed(1)} · 평정 ${r.rating === null ? "-" : r.rating.toFixed(1)}</div>`).join("") +
    `<div></div><div class="cat-axis"><span>0%</span><span>50%</span><span>100%</span></div><div></div>`;
  const tip = $("#tooltip");
  el.querySelectorAll(".hit").forEach((h) => {
    const r = rows[+h.dataset.i];
    h.onmousemove = (e) => {
      tip.innerHTML = `<b>${esc(CAT_KO[r.k] || r.k)}</b> · 사진 ${r.n}장<br>EEG 추정 평균 ${pct(r.p)}<br>설문 기대 ${r.survey === null ? "-" : r.survey.toFixed(1)} / 9<br>본인 평정 평균 ${r.rating === null ? "-" : r.rating.toFixed(1)} / 9<br>설문과 일치 ${r.agree}장`;
      tip.hidden = false;
      tip.style.left = `${Math.min(e.clientX + 14, innerWidth - 250)}px`; tip.style.top = `${e.clientY + 14}px`;
    };
    h.onmouseleave = () => (tip.hidden = true);
  });
}

function renderGrid(items, B) {
  const key = B.key;
  const counts = { all: items.length, agree: 0, disagree: 0, undecided: 0 };
  items.forEach((it) => counts[it[key]]++);
  document.querySelectorAll("#result-tabs button").forEach((b) => {
    const label = { all: "전체", ...B.ko }[b.dataset.filter];
    b.innerHTML = `${label}<span class="count">${counts[b.dataset.filter]}</span>`;
  });
  const grid = $("#result-grid");
  const draw = (filter) => {
    const list = items.filter((it) => filter === "all" || it[key] === filter);
    grid.innerHTML = list.map((it) => `
      <article class="ritem">
        ${it.src ? `<img src="${esc(it.src)}" alt="${esc(it.title)}" loading="lazy">`
          : `<div class="noimg" aria-hidden="true">${esc(it.stimulus_id)}</div>`}
        <div class="body">
          <div class="title"><b>${esc(it.title)}</b><span class="prob">${pct(it.eeg_like_probability)}</span></div>
          <div class="bar" title="EEG 기반 추정 선호 확률"><span style="width:${(it.eeg_like_probability ?? 0) * 100}%"></span></div>
          <dl class="compare">
            <dt>EEG 추정</dt><dd>${LABEL_KO[it.eeg_label]}${it.confidence !== null ? ` · 신뢰도 ${pct(it.confidence)}` : ""}</dd>
            <dt>설문 기대</dt><dd>${LABEL_KO[it.survey_label]}${it.survey_expected ? ` (${it.survey_expected})` : ""}</dd>
            <dt>본인 평정</dt><dd>${it.rating ?? "-"} / 9${it.seen_before === null ? "" : it.seen_before ? " · 본 적 있음" : " · 처음 봄"}</dd>
          </dl>
          <span class="tag ${it[key]}">${B.ko[it[key]]}</span>
          ${it.quality !== "ok" ? `<span class="tag warnq">신호 문제</span>` : ""}
        </div>
      </article>`).join("") || `<p class="empty">해당하는 사진이 없어요.</p>`;
  };
  document.querySelectorAll("#result-tabs button").forEach((b) => (b.onclick = () => {
    document.querySelectorAll("#result-tabs button").forEach((x) => {
      x.classList.toggle("active", x === b); x.setAttribute("aria-selected", String(x === b));
    });
    draw(b.dataset.filter);
  }));
  draw("all");
}

function toCSV(items) {
  const cols = ["trial_index", "stimulus_id", "title", "category", "tone", "quality", "eeg_like_probability",
    "confidence", "eeg_label", "survey_expected", "survey_label", "rating", "rating_label", "seen_before", "agreement",
    "rating_agreement"];
  const cell = (v) => (v === null || v === undefined ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : v);
  return "﻿" + [cols.join(","), ...items.map((it) => cols.map((c) => cell(it[c])).join(","))].join("\n");
}

function download(name, text, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

init().catch((e) => toast(`서버에 연결할 수 없어요: ${e.message}`, 10000));
