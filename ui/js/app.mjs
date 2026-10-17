// Bench Buddy front end. Driven by ui_server.py: tutor log lines (said, heard, plan, step checks) and vision's
// live board state, which the 3D twin in the board pane draws and simulates as the board is built.
import { drawMat } from "./mat.mjs";
import { createHero } from "./hero.mjs";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const STATE_LABEL = { IDLE: "Hello", INVENTORY: "Your parts", PROPOSE: "The plan", STEP: "Build", CHECK: "Checking", MEASURE: "Measuring", DONE: "Working", DEBUG: "Debugging" };
const SUGGEST = { PROPOSE: ["Ready"], STEP: ["Done"], DONE: ["It's not working"], DEBUG: ["Done"] };

drawMat($("matMarks"));
createHero({ stage: $("heroStage"), boardEl: $("heroBoard"), chute: $("chute"), landing: $("landing") });

// ---------------------------------------------------------------- session state
const ui = {
  started: false, transport: null, steps: [], stepI: -1,
  fsm: "IDLE", muted: false, browserTts: true, serverStt: false, camera: false,
  lastLocal: "", waiting: false, thinking: false,
};

// ---------------------------------------------------------------- landing → bench
$("start").addEventListener("click", enterBench);
$("back").addEventListener("click", () => {
  $("bench").hidden = true;
  $("landing").hidden = false;
  $("landing").classList.remove("leaving");
});

function enterBench() {
  $("landing").classList.add("leaving");
  setTimeout(() => {
    $("landing").hidden = true;
    $("bench").hidden = false;
    $("bench").classList.add("entering");
    mountTwin();
    if (!ui.started) connect();
  }, 380);
}

// ---------------------------------------------------------------- 3D twin (figures/parts → vendor/twin.bundle.mjs)
// The board pane is the breadboard twin: vision's live part list drawn in 3D and simulated, with the rows vision
// is looking at and the open step's target highlighted.
let twin = null;
const twinQueue = [];                       // events that arrive before the twin has loaded
function mountTwin() {
  if (twin) return;
  twin = "loading";
  import("../vendor/twin.bundle.mjs").then(({ mountTwin }) => {
    twin = mountTwin($("twin"), { onStatus: simStatus });
    for (const ev of twinQueue.splice(0)) toTwin(ev);
  }).catch((err) => {
    console.warn("3D view unavailable", err);
    twin = null;
    $("twin").innerHTML = `<p class="twin-off">The 3D board needs WebGL, which this browser doesn't have. The chat still works.</p>`;
  });
}
function toTwin(ev) {
  if (!twin || twin === "loading") return twinQueue.push(ev);
  if (ev.type === "board") twin.applyVision(ev);
  if (ev.type === "log") twin.applyLog(ev.line);
}
const span = (rows) => (rows.length > 1 ? `rows ${rows[0]}–${rows.at(-1)}` : `row ${rows[0]}`);
function simStatus({ phase, rows, target, simLit, realLit, agree }) {
  let text, tone = "";
  if (phase === "none") text = ui.camera ? "Waiting for the camera…" : "No camera connected";
  else if (phase === "calibrating") text = "Finding the board · keep hands off";
  else if (phase === "hands") (text = "Hands on the board…"), (tone = "busy");
  else if (phase === "looking") (text = rows.length ? `Looking at ${span(rows)}…` : "Looking at the change…"), (tone = "busy");
  else if (!agree) (text = `Simulation says LED ${simLit ? "on" : "off"}, camera sees it ${realLit ? "on" : "off"}`), (tone = "bad");
  else if (simLit !== null) (text = `Simulation · LED ${simLit ? "on" : "off"}${realLit === null ? "" : " · matches the camera"}`), (tone = simLit ? "on" : "");
  else if (target && (target.rows.length || target.rails.length))
    text = `Next: ${[target.rows.length ? span(target.rows) : "", ...target.rails.map((r) => `the ${r === "+" ? "plus" : "minus"} rail`)].filter(Boolean).join(" and ")}`, tone = "target";
  else text = "Watching the board";
  $("simChip").hidden = false;
  $("simChip").className = `sim-chip ${tone}`;
  $("simText").textContent = text;
}
function narrate(ev) {
  const text = ev.problem ? `${ev.problem}` : ev.narration || ev.summary;
  $("narration").hidden = !text;
  $("narration").classList.toggle("bad", !!ev.problem);
  $("narration").textContent = text || "";
}

// ---------------------------------------------------------------- transport
async function hello() {
  try {
    const ctrl = new AbortController();
    setTimeout(() => ctrl.abort(), 1500);
    const res = await fetch("/api/hello", { signal: ctrl.signal });
    return res.ok ? await res.json() : null;
  } catch { return null; }
}
async function connect() {
  ui.started = true;
  const h = await hello();
  if (!h) {
    // Nothing to show without the bench: say how to start it, and keep checking.
    setConn("down", "Offline");
    $("conn").title = "Start the bench: python main.py --ui";
    if (!$("log").querySelector(".offline")) {
      card(`<div class="card-h">Bench Buddy isn't running</div><div>Start it on the laptop at the bench, then this page connects by itself:</div><pre>python main.py --ui</pre>`).classList.add("offline");
    }
    setStatus("Waiting for the bench…");
    return setTimeout(connect, 3000);
  }
  $("log").querySelector(".offline")?.remove();
  applyHello(h);
  const es = new EventSource("/events");
  es.onmessage = (m) => handle(JSON.parse(m.data));
  es.onerror = () => setConn("down", "Reconnecting…");
  es.onopen = () => setConn("live", "Live");
  ui.transport = {
    send: (text) => post({ text }),
    ptt: (action) => post({ ptt: action }),
  };
  // Seed the twin with what vision sees right now (the SSE "board" event only comes on a change).
  fetch("/api/board").then((r) => (r.ok ? r.json() : null)).then((st) => st?.board && handle({ type: "board", ...st })).catch(() => {});
}
const post = (body) => fetch("/api/input", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).catch(() => toast("Couldn't reach the server."));

function setConn(kind, label) {
  $("conn").className = `conn ${kind}`;
  $("conn").querySelector("span").textContent = label;
}

function applyHello(h) {
  ui.browserTts = !!h.browser_tts;
  ui.serverStt = !!h.server_stt;
  ui.camera = !!h.camera;
  $("camBtn").hidden = !ui.camera;
}

// ---------------------------------------------------------------- events
function handle(ev) {
  if (ev.type === "hello") { applyHello(ev); return; }
  if (ev.type === "status") return status(ev);
  if (ev.type === "board") {
    if (!Array.isArray(ev.board)) return;
    narrate(ev);
    return toTwin(ev);
  }
  if (ev.type === "reset") return resetSession();
  if (ev.type === "log") { toTwin(ev); return onLog(ev.line, ev.replay); }
}

// The server replays its history to a fresh page, so start from a clean slate first.
function resetSession() {
  $("log").innerHTML = "";
  Object.assign(ui, { steps: [], stepI: -1, fsm: "", lastLocal: "", thinking: false });
  setFsm("IDLE");
}

function status(ev) {
  if ("waiting" in ev) {
    ui.waiting = ev.waiting;
    $("mic").classList.toggle("your-turn", ev.waiting);
    if (ev.waiting) setStatus("Your turn · hold Space to talk");
  }
  if ("speaking" in ev) avatar(ev.speaking ? "speaking" : "");
}

function onLog(l, replay) {
  const next = l.transition || l.state;
  if (next && next !== ui.fsm) setFsm(next);
  if (Array.isArray(l.plan)) ui.steps = l.plan;

  if (l.heard !== undefined) {
    if (l.heard === ui.lastLocal) ui.lastLocal = "";
    else addMsg("you", l.heard, "voice");
  }
  if (l.parts) partsCard(l.parts, l.missing || []);
  if (l.step && ["vision", "look", "measure"].includes(l.check)) checkCard(l);
  if (l.check === "measure" && !l.step) measureResult(l);
  if (l.check === "probe") probeCard(l);
  if (l.said) {
    const i = ui.steps.findIndex((s) => s.say === l.said);
    if (i >= 0) ui.stepI = i;
    return said(l.said, replay);
  }
}

function said(text, replay) {
  thinking(false);
  addMsg("bot", text);
  setInstruction(text);
  if (!replay && ui.browserTts) return speak(text);
}

function setFsm(s) {
  ui.fsm = s;
  const labels = { CHECK: "Looking at your board…", MEASURE: "Measuring…", DEBUG: "Finding the fault…" };
  if (labels[s]) setStatus(labels[s]);
  suggest(SUGGEST[s] || []);
  if (s === "CHECK") thinking(true);
}

function measureResult(l) {
  const m = l.detail.match(/predicted ([\d.]+).*measured ([\d.]+)/i);
  if (m) measureCard(+m[1], +m[2], l.result === "pass");
  else checkCard({ ...l, check: "measure" });
}

// ---------------------------------------------------------------- panel rendering
function addMsg(who, text, via) {
  const el = document.createElement("div");
  el.className = `msg ${who}`;
  el.innerHTML = (who === "you" && via === "voice" ? `<span class="via">🎙 said</span>` : "") + esc(text);
  return append(el);
}
function append(el) {
  const log = $("log");
  log.querySelector(".typing")?.remove();
  log.append(el);
  if (ui.thinking) log.append(typingEl());
  log.scrollTop = log.scrollHeight;
  return el;
}
const typingEl = () => Object.assign(document.createElement("div"), { className: "typing", innerHTML: "<i></i><i></i><i></i>" });
function card(html) { const el = document.createElement("div"); el.className = "card"; el.innerHTML = html; return append(el); }

function partsCard(parts, missing) {
  // fsm.py logs {parts: [...]}, tutor.py logs the list itself; missing may be strings or {desc}.
  const list = Array.isArray(parts) ? parts : parts.parts || [];
  missing = missing.map((m) => (typeof m === "string" ? m : m.desc || JSON.stringify(m)));
  const name = (p) => {
    if (p.type === "resistor") return `${si(p.value)}Ω`;
    if (p.type === "capacitor") return `${si(p.value)}F`;
    if (p.type === "ic") return `${p.part} timer`;
    return String(p.type || p.desc || p.name || "part").toUpperCase();
  };
  card(`<div class="card-h">Parts I heard <span class="pill ${missing.length ? "fail" : "pass"}">${missing.length ? `${missing.length} missing` : "all set"}</span></div>
    <div class="chips">${list.map((p) => `<span class="chip">${esc(name(p))}${p.qty > 1 ? ` ×${p.qty}` : ""}</span>`).join("")}
    ${missing.map((m) => `<span class="chip miss">${esc(m)}</span>`).join("")}</div>`);
}
function si(v) {
  for (const [s, pre] of [[1e6, "M"], [1e3, "k"], [1, ""], [1e-6, "µ"], [1e-9, "n"], [1e-12, "p"]]) if (v >= s * 0.999) return `${+(v / s).toPrecision(3)} ${pre}`;
  return `${v} `;
}
function checkCard(l) {
  const title = l.check === "vision" ? "Camera check" : "Check";
  card(`<div class="card-h">${title}${l.step ? ` · ${esc(l.step)}` : ""}<span class="pill ${l.result}">${esc(l.result)}</span></div>
    <div>${esc(l.detail)}</div>${l.frame ? `<img src="/${esc(l.frame)}" alt="Annotated camera frame from the check" onerror="this.remove()">` : ""}`);
}
function measureCard(pred, meas, ok) {
  const pos = (v) => Math.max(0, Math.min(100, 50 + ((v - pred) / pred) * 120));
  card(`<div class="card-h">Blink rate<span class="pill ${ok ? "pass" : "fail"}">${ok ? "within ±25%" : "out of range"}</span></div>
    <div class="gauge"><div class="gauge-row"><span>predicted<br><b>${pred.toFixed(2)}</b> Hz</span><span style="text-align:right">measured<br><b>${meas.toFixed(2)}</b> Hz</span></div>
    <div class="gauge-bar"><i class="pred" style="left:50%"></i><i style="left:${pos(meas)}%"></i></div></div>`);
}
function probeCard(l) {
  card(`<div class="card-h">Probe${l.node ? ` · ${esc(l.node)}` : ""}<span class="pill ${l.result}">${l.result === "pass" ? "healthy" : "fault"}</span></div><div>${esc(cap(l.detail))}</div>`);
}
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

function setInstruction(text, tone) {
  let label = STATE_LABEL[ui.fsm] || "Bench Buddy";
  if (ui.fsm === "STEP" && ui.stepI >= 0) label = `Step ${ui.stepI + 1} of ${ui.steps.length}`;
  $("insLabel").textContent = label;
  $("insText").textContent = text.replace(/ Say done when it's in\.$/, "");
  $("instruction").className = `instruction ${tone || (ui.fsm === "DONE" ? "ok" : ui.fsm === "DEBUG" ? "bad" : "")}`;
}
function setStatus(text) { $("statusText").textContent = text; }
function avatar(kind) { $("avatar").className = `avatar ${kind}`; }
function thinking(on) {
  ui.thinking = on;
  const panel = document.querySelector(".panel");
  if (!on && panel.classList.contains("thinking")) {
    panel.classList.add("cooling");
    setTimeout(() => panel.classList.remove("cooling"), 400);
  }
  if (on) panel.classList.remove("cooling");
  panel.classList.toggle("thinking", on);
  $("log").querySelector(".typing")?.remove();
  if (on) { $("log").append(typingEl()); $("log").scrollTop = $("log").scrollHeight; avatar("thinking"); setStatus("Thinking…"); }
  else if ($("avatar").classList.contains("thinking")) avatar("");
}
function suggest(items) {
  $("suggest").innerHTML = items.map((t) => `<button type="button">${esc(t.length > 46 ? t.slice(0, 44) + "…" : t)}</button>`).join("");
  [...$("suggest").children].forEach((b, i) => b.addEventListener("click", () => sendText(items[i])));
}
function toast(text) {
  const t = $("toast"); t.textContent = text; t.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => (t.hidden = true), 3200);
}

// ---------------------------------------------------------------- sending + voice in
function sendText(text, via = "typed") {
  text = text.trim();
  if (!text || !ui.transport) return;
  stopSpeaking();
  ui.lastLocal = text;
  addMsg("you", text, via);
  suggest([]);
  thinking(true);
  ui.transport.send(text);
}
$("composer").addEventListener("submit", (e) => { e.preventDefault(); sendText($("input").value); $("input").value = ""; grow(); });
$("input").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("composer").requestSubmit(); } });
const grow = () => { const t = $("input"); t.style.height = "auto"; t.style.height = Math.min(120, t.scrollHeight) + "px"; };
$("input").addEventListener("input", grow);

// Push-to-talk: hold the mic (or Space) to talk; a quick tap toggles it on until the next tap.
const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null, talking = false, pressedAt = 0, interim = null, finalText = "";

function pttDown() {
  if (talking) return pttUp(true);
  talking = true; pressedAt = performance.now();
  stopSpeaking();
  $("mic").classList.add("on"); avatar("listening"); setStatus("Listening…");
  if (ui.serverStt) return ui.transport.ptt("start");
  if (!Recognition) { pttUp(true); toast("Voice input needs Chrome or Safari here. Type instead."); $("input").focus(); return; }
  finalText = "";
  rec = new Recognition();
  rec.lang = "en-US"; rec.interimResults = true; rec.continuous = true;
  rec.onresult = (e) => {
    let live = "";
    finalText = "";
    for (const r of e.results) (r.isFinal ? (finalText += r[0].transcript) : (live += r[0].transcript));
    const shown = (finalText + live).trim();
    if (!shown) return;
    if (!interim) interim = addMsg("you", "", "voice"), interim.classList.add("interim");
    interim.lastChild.textContent = shown;
  };
  rec.onerror = (e) => { if (e.error !== "aborted" && e.error !== "no-speech") toast(`Mic: ${e.error}`); };
  rec.onend = () => {
    const text = (finalText || interim?.lastChild.textContent || "").trim();
    interim?.remove(); interim = null; rec = null;
    if (text) sendText(text, "voice");
  };
  rec.start();
}
function pttUp(force) {
  if (!talking) return;
  if (!force && performance.now() - pressedAt < 280) return; // tap = latch on
  talking = false;
  $("mic").classList.remove("on"); avatar(""); setStatus("Ready");
  if (ui.serverStt) { thinking(true); return ui.transport.ptt("stop"); }
  rec?.stop();
}
$("mic").addEventListener("pointerdown", (e) => { e.preventDefault(); pttDown(); });
$("mic").addEventListener("pointerup", () => pttUp());
$("mic").addEventListener("pointercancel", () => pttUp(true));
const typing = (e) => /TEXTAREA|INPUT|SELECT/.test(e.target.tagName);
addEventListener("keydown", (e) => { if (e.code === "Space" && !e.repeat && !typing(e) && !$("bench").hidden) { e.preventDefault(); pttDown(); } });
addEventListener("keyup", (e) => { if (e.code === "Space" && !typing(e) && !$("bench").hidden) { e.preventDefault(); pttUp(); } });

// ---------------------------------------------------------------- voice out (when the server asks the browser to speak)
let voice = null;
const pickVoice = () => {
  const vs = speechSynthesis.getVoices();
  voice = ["Samantha", "Ava", "Karen", "Daniel", "Google UK English Female", "Google US English", "Microsoft Aria"]
    .map((n) => vs.find((v) => v.name.includes(n))).find(Boolean) || vs.find((v) => v.lang?.startsWith("en")) || null;
};
if ("speechSynthesis" in window) { pickVoice(); speechSynthesis.onvoiceschanged = pickVoice; }

function speak(text) {
  if (ui.muted || !("speechSynthesis" in window)) return new Promise((r) => setTimeout(r, Math.min(2200, 300 + text.length * 22)));
  return new Promise((resolve) => {
    const u = new SpeechSynthesisUtterance(text);
    if (voice) u.voice = voice;
    u.rate = 1.04;
    let guard, finished = false;
    const talk = {
      arm: () => { clearTimeout(guard); guard = setTimeout(talk.done, 400 + text.length * 90); }, // some browsers never fire onend
      disarm: () => clearTimeout(guard),
      done: () => {
        if (finished) return;
        finished = true; clearTimeout(guard);
        if (current === talk) { current = null; speechBar(null); }
        avatar(""); resolve();
      },
    };
    talk.arm();
    u.onstart = () => { current = talk; speechBar("speaking"); avatar("speaking"); setStatus("Speaking…"); };
    u.onend = talk.done; u.onerror = talk.done;
    speechSynthesis.speak(u);
  });
}
// The utterance being spoken right now, so it can be paused, resumed or stopped.
let current = null;
function speechBar(state) {
  $("speech").hidden = !state;
  $("speech").classList.toggle("paused", state === "paused");
  $("speechLabel").textContent = state === "paused" ? "Paused" : "Speaking";
  $("pauseBtn").setAttribute("aria-pressed", state === "paused");
  $("pauseBtn").querySelector("span").textContent = state === "paused" ? "Resume" : "Pause";
  $("stopBtn").hidden = state !== "paused";
}
function pauseSpeaking() {
  if (!current) return;
  speechSynthesis.pause(); current.disarm();
  speechBar("paused"); avatar(""); setStatus("Paused");
}
function resumeSpeaking() {
  if (!current) return;
  speechSynthesis.resume(); current.arm();
  speechBar("speaking"); avatar("speaking"); setStatus("Speaking…");
}
function stopSpeaking() {
  if (!("speechSynthesis" in window)) return;
  speechSynthesis.cancel();
  speechSynthesis.resume(); // Chrome stays paused after cancel(), which would silence the next reply
  if (current) { current.done(); setStatus("Ready"); }
}
$("pauseBtn").addEventListener("click", () => ($("pauseBtn").getAttribute("aria-pressed") === "true" ? resumeSpeaking() : pauseSpeaking()));
$("stopBtn").addEventListener("click", stopSpeaking);
$("mute").addEventListener("click", () => {
  ui.muted = !ui.muted;
  $("mute").setAttribute("aria-pressed", ui.muted);
  $("mute").title = ui.muted ? "Unmute voice" : "Mute voice";
  if (ui.muted) stopSpeaking();
});

// ---------------------------------------------------------------- camera
let stream = null;
$("camBtn").addEventListener("click", async () => {
  const on = $("camBtn").getAttribute("aria-pressed") !== "true";
  $("camBtn").setAttribute("aria-pressed", on);
  $("cam").hidden = !on;
  if (!on) { stream?.getTracks().forEach((t) => t.stop()); stream = null; $("camImg").removeAttribute("src"); return; }
  if (ui.camera) {
    // Vision owns the phone camera in Python; show its frames (with the hole grid) instead of opening it twice.
    $("camSelect").hidden = true; $("camVideo").hidden = true; $("camImg").hidden = false;
    $("camImg").src = "/camera.mjpg";
    return;
  }
  $("camImg").hidden = true; $("camVideo").hidden = false; $("camSelect").hidden = false;
  await openCamera();
});
async function openCamera(deviceId) {
  try {
    stream?.getTracks().forEach((t) => t.stop());
    stream = await navigator.mediaDevices.getUserMedia({ video: deviceId ? { deviceId: { exact: deviceId } } : true, audio: false });
    $("camVideo").srcObject = stream;
    const cams = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "videoinput");
    const current = stream.getVideoTracks()[0].getSettings().deviceId;
    $("camSelect").innerHTML = cams.map((c, i) => `<option value="${c.deviceId}"${c.deviceId === current ? " selected" : ""}>${esc(c.label || `Camera ${i + 1}`)}</option>`).join("");
  } catch (err) {
    toast("Couldn't open a camera: " + err.message);
  }
}
$("camSelect").addEventListener("change", (e) => openCamera(e.target.value));
