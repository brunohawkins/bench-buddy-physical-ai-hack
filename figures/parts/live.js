// Follow a running Bench Buddy: read its FSM log lines (the same ones log.jsonl and the UI get)
// and keep the breadboard twin in step with the real bench.
//
//   vision check pass          → the step's parts go where the project says
//   vision check fail, row N   → they go where vision saw them (row N), tinted red
//   measure (step) "on A0"     → the reading is pinned to A0's test-point hole; a passing
//                                step also flips its inputs (e.g. the Arduino gets plugged in)
//   measure "measured X Hz"    → compared with the simulated blink rate
//   probe "pin 4 is at 0.02 V" → reading at that test point; a failing probe runs the fault
//                                search and marks the most likely culprit
//   said "Hi, I'm Bench Buddy" → a new run: the bench resets to the project's start
//
// Source: an EventSource on <url>/events (twin_feed.py, or ui_server.py when it allows CORS), or with
// url: null, whatever calls handle(line).
const num = (re, text) => { const m = re.exec(text ?? ""); return m ? parseFloat(m[1]) : null; };

export function follow(board, { url = "http://localhost:8766", projectId = "blinker-555", onStatus = () => {} } = {}) {
  let es = null, measuredHz = null;
  const status = { connected: false, state: "", said: "", lines: 0 };
  const P = () => board.project;
  const update = (extra = {}) => { Object.assign(status, extra); onStatus({ ...status }); };

  function start() {
    board.loadProject(projectId, []);
    board.twin.clearMeasurements();
    board.note("");
    measuredHz = null;
  }

  function probeReading(pin, volts) {
    const hole = P().probes?.[pin];
    if (!hole || volts === null) return null;
    return board.twin.measure(hole, volts);
  }

  function explain() {
    const r = board.twin.results;
    const mism = r?.mismatches ?? [];
    if (!mism.length) { board.suspect(null); return board.note(""); }
    const d = board.twin.diagnose();
    board.suspect(d.likely[0]?.text ?? null);
    const lines = mism.map((m) => `${m.hole}: measured ${m.measured.toFixed(2)} V, the simulation expects ${m.simulated.toFixed(2)} V`);
    board.note(`<b>Bench and simulation disagree.</b> ${lines.join("; ")}.<br>Most likely: ${d.likely.slice(0, 3).map((h) => h.text).join(" · or ")}${d.next ? `<br>Probe <b>${d.next.hole}</b> next to tell these apart.` : ""}`);
  }

  function handle(line) {
    status.lines++;
    if (line.state) update({ state: line.state });
    if (line.said) {
      update({ said: line.said });
      if (/^Hi, I'm Bench Buddy/.test(line.said)) start();
    }
    if (line.transition) update({ state: line.transition });
    if (!P()) return;
    if (line.check === "vision" && line.step) {
      if (line.result === "pass") board.applyStep(line.step, "pass");
      else if (line.result === "fail") board.applyStep(line.step, "wrong", num(/row (\d+)/i, line.detail));
    }
    if (line.check === "measure") {
      if (line.step) {
        if (line.result === "pass") board.applyStep(line.step, "pass");
        const pin = /on (\w+)\.?$/.exec(line.detail ?? "")?.[1];
        probeReading(pin, num(/reading ([\d.]+) volts/, line.detail));
        explain();
      } else {
        measuredHz = num(/measured ([\d.]+) Hz/, line.detail);
        const sim = board.twin.blinkHz;
        board.note(measuredHz !== null ? `Blink rate: measured <b>${measuredHz.toFixed(2)} Hz</b>, simulated <b>${sim ? sim.toFixed(2) : "…"} Hz</b>${sim && Math.abs(sim - measuredHz) > 0.25 * sim ? " — they don't match" : ""}.` : "");
      }
    }
    if (line.check === "probe") {
      const pin = P().nodes?.[line.node];
      probeReading(pin, num(/at ([\d.]+) volts/, line.detail));
      if (line.result === "pass") { board.twin.clearMeasurements(); board.suspect(null); board.note("Debug probe passed: the bench measures healthy, matching the simulation."); }
      else explain();
    }
  }

  function connect() {
    es?.close();
    es = new EventSource(`${url.replace(/\/$/, "")}/events`);
    es.onopen = () => update({ connected: true });
    es.onerror = () => update({ connected: false });
    es.onmessage = (m) => {
      const ev = JSON.parse(m.data);
      if (ev.type === "reset") start();
      if (ev.type === "log") handle(ev.line);
    };
  }
  if (url) connect();                     // url null: lines are fed in through handle() (the UI's own feed)
  else start();
  return { stop: () => { es?.close(); update({ connected: false }); }, handle, status };
}
