// Bench Buddy front end. Everything is driven by fsm.py log lines: from ui_server.py (live)
// or from the in-browser demo (demo.mjs), so both modes share one code path.
import { createBoard, PARTS, partById } from "./board.mjs";
import { drawMat } from "./mat.mjs";
import { createDemo, DEMO_PROJECT } from "./demo.mjs";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const ALL = PARTS.map((p) => p.id);
const STATE_LABEL = { IDLE: "Hello", INVENTORY: "Your parts", PROPOSE: "The plan", STEP: "Build", CHECK: "Checking", MEASURE: "Measuring", DONE: "Working", DEBUG: "Debugging" };
const SUGGEST = {
  INVENTORY: ["I've got a 555, two 10k resistors, a 68k, a 330 ohm, a 10 microfarad cap, a 100 nanofarad and a 10 nanofarad cap, and an LED"],
  PROPOSE: ["Ready"], STEP: ["Done"], DONE: ["It's not working", "Why 0.99 Hz?"], DEBUG: ["Done"],
};

drawMat($("matMarks"));
const hero = createBoard($("heroBoard"), { interactive: false });
hero.set({ led: true, hz: 0.99 });

// ---------------------------------------------------------------- session state
const ui = {
  started: false, transport: null, mode: "demo", project: DEMO_PROJECT, stepI: 0,
  fsm: "IDLE", muted: false, browserTts: true, serverStt: false, camera: false,
  handsFree: false, micPaused: false, micState: "idle", micError: "", speaking: false,
  lastLocal: "", waiting: false, thinking: false,
};
const prebuilt = () => ALL.filter((id) => !ui.project.steps.some((s) => s.id === id));
let board;

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
    if (!board) {
      board = createBoard($("board"));
      board.reveal(prebuilt());
      $("board").addEventListener("part-hover", (e) => focusPart(e.detail));
      renderPartsList();
    }
    if (!ui.started) connect();
  }, 380);
}

// ---------------------------------------------------------------- transport
async function connect() {
  ui.started = true;
  const params = new URLSearchParams(location.search);
  let hello = null;
  if (!params.has("demo")) {
    try {
      const ctrl = new AbortController();
      setTimeout(() => ctrl.abort(), 1200);
      const res = await fetch("/api/hello", { signal: ctrl.signal });
      if (res.ok) hello = await res.json();
    } catch { /* no server: demo */ }
  }
  if (hello) {
    ui.mode = "live";
    applyHello(hello);
    const es = new EventSource("/events");
    es.onmessage = (m) => handle(JSON.parse(m.data));
    es.onerror = () => setConn("down", "Reconnecting…");
    es.onopen = () => setConn("live", "Live");
    ui.transport = {
      send: (text) => post({ text }),
      ptt: (action) => post({ ptt: action }),
      mic: (action) => post({ mic: action }),
    };
  } else {
    ui.mode = "demo";
    setConn("demo", "Demo");
    $("conn").title = "No ui_server.py found, so this is the built-in demo. Run: python main.py --fake --ui";
    const demo = createDemo(handle);
    ui.transport = { send: (text) => demo.send(text) };
    demo.start();
  }
}
const post = (body) => fetch("/api/input", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).catch(() => toast("Couldn't reach the server."));

function setConn(kind, label) {
  $("conn").className = `conn ${kind}`;
  $("conn").querySelector("span").textContent = label;
}

function applyHello(h) {
  if (h.project) ui.project = { ...DEMO_PROJECT, ...h.project };
  ui.browserTts = !!h.browser_tts;
  ui.serverStt = !!h.server_stt;
  ui.handsFree = !!h.hands_free;
  ui.camera = !!h.camera;
  if (board) { board.reveal(prebuilt()); renderPartsList(); }
  $("readout").textContent = `predicted ${ui.project.predicted.toFixed(2)} Hz · measured —`;
  updateMic();
}

// ---------------------------------------------------------------- events
function handle(ev) {
  if (ev.type === "hello") { applyHello(ev); return; }
  if (ev.type === "status") return status(ev);
  if (ev.type === "board") return boardEvent(ev);
  if (ev.type === "reset") return resetSession();
  if (ev.type === "log") return onLog(ev.line, ev.replay);
}

// The server replays its history to a fresh page, so start from a clean slate first.
function resetSession() {
  $("log").innerHTML = "";
  Object.assign(ui, { stepI: 0, fsm: "", pulledId: null, lastLocal: "", thinking: false });
  board.set({ overrides: {}, wrong: [], targets: [], tags: [], ghost: null, led: false, focus: null });
  board.reveal(prebuilt());
  renderPartsList();
  setFsm("IDLE");
}

function status(ev) {
  for (const [field, key] of Object.entries({ waiting: "waiting", speaking: "speaking", hands_free: "handsFree",
    mic_paused: "micPaused", mic_state: "micState", mic_error: "micError" })) {
    if (field in ev) ui[key] = ev[field];
  }
  if ("speaking" in ev) avatar(ev.speaking ? "speaking" : "");
  updateMic();
}

function updateMic() {
  const active = ui.waiting && !ui.micPaused && !ui.speaking;
  $("mic").classList.toggle("your-turn", ui.handsFree ? active && ["listening", "hearing"].includes(ui.micState) : ui.waiting);
  $("mic").classList.toggle("paused", ui.handsFree && ui.micPaused);
  if (!ui.handsFree) {
    $("mic").setAttribute("aria-label", "Hold to talk");
    $("mic").removeAttribute("aria-pressed");
    $("hint").innerHTML = "Hold <kbd>Space</kbd> or the mic to talk · <kbd>Enter</kbd> sends";
    if (ui.waiting && !ui.speaking) setStatus("Your turn · hold Space to talk");
    return;
  }
  const label = ui.micPaused ? "Resume microphone" : "Pause microphone";
  $("mic").setAttribute("aria-label", label);
  $("mic").setAttribute("aria-pressed", !ui.micPaused);
  $("mic").title = label;
  $("mic").classList.toggle("on", active && ui.micState === "hearing");
  $("hint").textContent = ui.micError || (ui.micPaused
    ? "Mic paused · tap the mic to resume · Enter sends"
    : "Speak naturally · tap the mic to pause · Enter sends");
  if (ui.speaking) return setStatus("Speaking…");
  if (ui.waiting) {
    const labels = { starting: "Preparing microphone…", calibrating: "Preparing microphone…",
      listening: "Listening · speak naturally", hearing: "Listening…", transcribing: "Transcribing…", idle: "Your turn…" };
    setStatus(ui.micError ? "Microphone unavailable · you can type" : ui.micPaused ? "Mic paused · you can type" : labels[ui.micState] || "Your turn…");
    if (active && ui.micState === "hearing") avatar("listening");
  }
}

function onLog(l, replay) {
  const next = l.transition || l.state;
  if (next && next !== ui.fsm) setFsm(next);

  if (l.heard !== undefined) {
    if (l.heard === ui.lastLocal) ui.lastLocal = "";
    else addMsg("you", l.heard, "voice");
    if (!replay) thinking(true);
  }
  if (l.parts) partsCard(l.parts, l.missing || []);
  if (l.check === "vision") visionResult(l);
  if (l.check === "vision_problem") checkCard(l);
  if (l.check === "measure") measureResult(l);
  if (l.check === "probe") probeResult(l);
  if (l.said) return said(l.said, replay);
}

function said(text, replay) {
  thinking(false);
  addMsg("bot", text);
  setInstruction(text);
  if (!replay && (ui.mode === "demo" || ui.browserTts)) return speak(text);
}

// ---------------------------------------------------------------- state + board
function setFsm(s) {
  const prev = ui.fsm;
  ui.fsm = s;
  const order = ["INVENTORY", "PROPOSE", "STEP", "CHECK", "MEASURE", "DONE"];
  const at = order.indexOf(s);
  for (const li of $("fsm").children) {
    const i = order.indexOf(li.dataset.s);
    li.classList.toggle("now", li.dataset.s === s);
    li.classList.toggle("past", at >= 0 && i >= 0 && i < at);
  }
  $("fsm").classList.toggle("debugging", s === "DEBUG");
  const labels = { CHECK: "Looking at your board…", MEASURE: "Measuring…", DEBUG: "Finding the fault…" };
  if (labels[s]) setStatus(labels[s]);
  suggest(SUGGEST[s] || []);
  if (s === "STEP" && prev !== "CHECK") showStep();
  if (s === "CHECK") thinking(true);
}

function currentStep() { return ui.project.steps[ui.stepI]; }

function showStep() {
  const step = currentStep();
  if (!step || !partById(step.id)) return;
  const st = board.get();
  if (st.placed.includes(step.id)) return;
  const p = partById(step.id);
  board.set({ ghost: step.id, targets: [p.from, p.to], wrong: [], tags: [{ part: step.id, title: `Place · ${p.label}`, text: `${p.from[0]}${p.from[1]} → ${railName(p.to)}`, tone: "target" }] });
  renderPartsList();
}
const RAIL = { "+L": "5 V rail", "+R": "5 V rail", "-L": "GND rail", "-R": "GND rail" };
const railName = ([c, r]) => RAIL[c] || `${c}${r}`;

function visionResult(l) {
  const id = l.step;
  const p = partById(id);
  const row = (l.rows_found && l.rows_found[0]) || +(l.detail.match(/row (\d+)/i) || [])[1];
  checkCard(l);
  if (!p) return;
  const st = board.get();
  const placed = [...new Set([...st.placed, id])];
  if (l.result === "pass") {
    const overrides = { ...st.overrides }; delete overrides[id];
    board.set({ placed, ghost: null, targets: [], wrong: [], overrides, tags: [{ part: id, title: "Looks good", text: `${p.label} · row ${p.from[1]}`, tone: "ok" }] });
    ui.stepI++;
    setTimeout(() => board.get().tags[0]?.tone === "ok" && board.set({ tags: [] }), 3500);
    setInstruction(l.detail, "ok");
  } else if (l.result === "fail" && row) {
    const spot = [p.from[0], row];
    board.set({ placed, ghost: null, targets: [p.from], wrong: [spot], overrides: { ...st.overrides, [id]: { from: spot } },
      tags: [{ at: spot, title: `Row ${row}`, text: `Should be row ${p.from[1]}`, tone: "bad" }] });
    setInstruction(l.detail, "bad");
  } else {
    board.set({ tags: [{ part: id, title: "Can't see it", text: "Move your hand out of the way", tone: "bad" }] });
    setInstruction(l.detail, "bad");
  }
  renderPartsList();
}

function measureResult(l) {
  const m = l.detail.match(/predicted ([\d.]+).*measured ([\d.]+)/i);
  const ok = l.result === "pass";
  if (m && !l.step) {
    const [pred, meas] = [+m[1], +m[2]];
    measureCard(pred, meas, ok);
    $("readout").textContent = `predicted ${pred.toFixed(2)} Hz · measured ${meas.toFixed(2)} Hz`;
    const led = partById("led");
    board.set({ led: ok && meas > 0, hz: meas || 1, tags: ok ? [{ part: "led", title: "Blinking", text: `${meas.toFixed(2)} Hz`, tone: "ok" }] : [] });
  } else {
    checkCard({ ...l, check: "measure" });
    if (l.step && ok) ui.stepI++;
  }
}

function probeResult(l) {
  probeCard(l);
  if (l.result === "fail" && /reset|pin 4/i.test(l.node || "")) pulled("reset");
  if (l.result === "pass" && ui.pulledId) boardEvent({ restored: ui.pulledId });
}

function boardEvent(ev) {
  if (ev.pulled) pulled(ev.pulled, true);
  if (ev.restored) {
    ui.pulledId = null;
    const st = board.get();
    board.set({ placed: [...new Set([...st.placed, ev.restored])], ghost: null, targets: [], wrong: [], tags: [] });
    renderPartsList();
  }
}

function pulled(id, quiet) {
  ui.pulledId = id;
  const p = partById(id);
  const st = board.get();
  board.set({ placed: st.placed.filter((x) => x !== id), ghost: id, led: false, targets: [p.from, p.to], wrong: [],
    tags: quiet ? [] : [{ part: id, title: `Missing · ${p.label}`, text: p.detail, tone: "bad" }] });
  $("readout").textContent = `predicted ${ui.project.predicted.toFixed(2)} Hz · measured 0.00 Hz`;
  renderPartsList();
}

function focusPart(id) {
  if (board.get().focus === id) return;
  board.set({ focus: id });
  for (const li of $("partsItems").children) li.classList.toggle("hot", li.dataset.id === id);
}

function renderPartsList() {
  if (!board) return;
  const st = board.get();
  const items = PARTS.map((p) => {
    const placed = st.placed.includes(p.id);
    const bad = placed && st.overrides[p.id];
    const cls = bad ? "bad" : placed ? "" : "todo";
    return `<li class="${cls}" data-id="${p.id}"><span class="chk"><svg viewBox="0 0 10 10"><path d="m2 5 2 2 4-4"/></svg></span><span class="nm">${esc(p.label)}</span><span class="dt">${esc(p.detail)}</span></li>`;
  });
  $("partsItems").innerHTML = items.join("");
  $("partsCount").textContent = `${st.placed.filter((id) => !st.overrides[id]).length} / ${PARTS.length}`;
}
$("partsItems").addEventListener("pointerover", (e) => { const li = e.target.closest("li"); if (li) focusPart(li.dataset.id); });
$("partsItems").addEventListener("pointerleave", () => focusPart(null));

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
  const name = (p) => {
    if (p.type === "resistor") return `${si(p.value)}Ω`;
    if (p.type === "capacitor") return `${si(p.value)}F`;
    if (p.type === "ic") return `${p.part} timer`;
    return p.type.toUpperCase();
  };
  card(`<div class="card-h">Parts I heard <span class="pill ${missing.length ? "fail" : "pass"}">${missing.length ? `${missing.length} missing` : "all set"}</span></div>
    <div class="chips">${parts.parts.map((p) => `<span class="chip">${esc(name(p))}${p.qty > 1 ? ` ×${p.qty}` : ""}</span>`).join("")}
    ${missing.map((m) => `<span class="chip miss">${esc(m)}</span>`).join("")}</div>`);
}
function si(v) {
  for (const [s, pre] of [[1e6, "M"], [1e3, "k"], [1, ""], [1e-6, "µ"], [1e-9, "n"], [1e-12, "p"]]) if (v >= s * 0.999) return `${+(v / s).toPrecision(3)} ${pre}`;
  return `${v} `;
}
function checkCard(l) {
  const title = l.check === "vision_problem" ? "Wiring correction" : l.check === "vision" ? "Camera check" : "Check";
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
  const step = currentStep();
  let label = STATE_LABEL[ui.fsm] || "Bench Buddy";
  if (ui.fsm === "STEP" && step) label = `Step ${ui.stepI + 1} of ${ui.project.steps.length}${partById(step.id) ? ` · ${partById(step.id).label}` : ""}`;
  $("insLabel").textContent = label;
  $("insText").textContent = text.replace(/ Say done when it's in\.$/, "");
  $("instruction").className = `instruction ${tone || (ui.fsm === "DONE" ? "ok" : ui.fsm === "DEBUG" ? "bad" : "")}`;
}
function setStatus(text) { $("statusText").textContent = text; }
function avatar(kind) { $("avatar").className = `avatar ${kind}`; }
function thinking(on) {
  ui.thinking = on;
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
  if (ui.handsFree) return;
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
$("mic").addEventListener("click", () => { if (ui.handsFree) ui.transport?.mic(ui.micPaused ? "resume" : "pause"); });
$("mic").addEventListener("pointerdown", (e) => { if (!ui.handsFree) { e.preventDefault(); pttDown(); } });
$("mic").addEventListener("pointerup", () => { if (!ui.handsFree) pttUp(); });
$("mic").addEventListener("pointercancel", () => { if (!ui.handsFree) pttUp(true); });
const typing = (e) => /TEXTAREA|INPUT|SELECT/.test(e.target.tagName);
addEventListener("keydown", (e) => { if (!ui.handsFree && e.code === "Space" && !e.repeat && !typing(e) && !$("bench").hidden) { e.preventDefault(); pttDown(); } });
addEventListener("keyup", (e) => { if (!ui.handsFree && e.code === "Space" && !typing(e) && !$("bench").hidden) { e.preventDefault(); pttUp(); } });

// ---------------------------------------------------------------- voice out (demo, or when the server asks the browser to speak)
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
    const done = () => { avatar(""); clearTimeout(guard); resolve(); };
    const guard = setTimeout(done, 400 + text.length * 90); // some browsers never fire onend
    u.onstart = () => { avatar("speaking"); setStatus("Speaking…"); };
    u.onend = done; u.onerror = done;
    speechSynthesis.speak(u);
  });
}
function stopSpeaking() { if ("speechSynthesis" in window) speechSynthesis.cancel(); }
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
  if (ui.mode === "live" && ui.camera) {
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
