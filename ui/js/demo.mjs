// In-browser stand-in for `python main.py --fake`, used when no ui_server is running.
// It is a small port of fsm.py + FakeBrain + FakeVision + FakeBench and emits the same
// log lines, so the UI code path is identical in demo and live mode.

const R1 = 10_000, R2 = 68_000, C = 10e-6;
const F = 1.44 / ((R1 + 2 * R2) * C);
const DUTY = (R1 + R2) / (R1 + 2 * R2);

export const DEMO_PROJECT = {
  name: "555 blinker",
  predicted: F,
  duty: DUTY,
  steps: [{ id: "reset", say: "Connect pin 4 to the 5 volt rail with a red wire.", check: { kind: "vision", expect_rows: [13], wire_colour: "red" } }],
};
const REQUIRED = [
  { type: "ic", part: "555", qty: 1 }, { type: "resistor", value: 10_000, qty: 2 }, { type: "resistor", value: 68_000, qty: 1 },
  { type: "resistor", value: 330, qty: 1 }, { type: "capacitor", value: 10e-6, qty: 1 }, { type: "capacitor", value: 100e-9, qty: 1 },
  { type: "capacitor", value: 10e-9, qty: 1 }, { type: "led", qty: 1 },
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const clock = () => new Date().toTimeString().slice(0, 8);

function classify(text) {
  const t = text.toLowerCase().trim();
  if (["not working", "doesn't work", "isn't working", "broken", "stopped"].some((w) => t.includes(w))) return "NOT_WORKING";
  if (["again", "repeat"].some((w) => t.includes(w))) return "REPEAT";
  if (t.endsWith("?")) return "QUESTION";
  if (["resistor", "capacitor", "555", "led", "ohm", "farad", "cap"].some((w) => t.includes(w))) return "PARTS";
  if (["done", "ok", "okay", "next", "yes", "ready", "go", "in"].some((w) => t.split(/\W+/).includes(w))) return "DONE";
  return "OTHER";
}

function answer(question) {
  const q = question.toLowerCase();
  if (q.includes("hz") || q.includes("hertz") || q.includes("fast") || q.includes("frequency"))
    return `The 555 sets the rate: 1.44 over R1 plus two R2, times C. With your parts that's ${F.toFixed(2)} hertz.`;
  if (q.includes("pin 4") || q.includes("reset")) return "Pin 4 is reset. If it isn't tied high, the chip just sits there and the LED stays off.";
  return null;
}

/** emit(event) may return a promise (the UI resolves it once a spoken line has finished). */
export function createDemo(emit) {
  let state = "IDLE", resume = "MEASURE", stepI = 0, retry = null, visionCalls = 0, pulled = false;
  const inbox = [];
  let waiter = null;

  const log = (fields) => emit({ type: "log", line: { t: clock(), state, ...fields } });
  const say = async (text) => { await log({ said: text }); };
  const listen = () => new Promise((resolve) => {
    emit({ type: "status", waiting: true });
    if (inbox.length) resolve(inbox.shift());
    else waiter = resolve;
  }).then((t) => { emit({ type: "status", waiting: false }); return t; });

  async function ask(prompt, accept) {
    await say(prompt);
    for (;;) {
      const text = await listen();
      const kind = classify(text);
      log({ heard: text, intent: kind });
      await sleep(450);
      if (accept.has(kind) || kind === "NOT_WORKING") return kind;
      if (kind === "REPEAT") await say(prompt);
      else if (kind === "QUESTION") await say((answer(text) ?? "I can't answer that one yet.") + " " + prompt);
      else await say("Sorry, I didn't catch that. " + prompt);
    }
  }

  const freq = () => (pulled ? 0 : 0.97);

  const states = {
    async IDLE() { await sleep(500); await say("Hi, I'm Bench Buddy."); return "INVENTORY"; },
    async INVENTORY() {
      const kind = await ask("Tell me what parts you have.", new Set(["PARTS"]));
      if (kind === "NOT_WORKING") return "DEBUG";
      log({ parts: { parts: REQUIRED, unclear: [] }, missing: [] });
      return "PROPOSE";
    },
    async PROPOSE() {
      const kind = await ask(`You have everything for a 555 blinker. With your parts it should blink at ${F.toFixed(2)} hertz. Say done when you're ready to start.`, new Set(["DONE"]));
      return kind === "NOT_WORKING" ? "DEBUG" : "STEP";
    },
    async STEP() {
      const step = DEMO_PROJECT.steps[stepI];
      if (!step) return "MEASURE";
      const prompt = retry || step.say + " Say done when it's in.";
      retry = null;
      const kind = await ask(prompt, new Set(["DONE"]));
      return kind === "NOT_WORKING" ? "DEBUG" : "CHECK";
    },
    async CHECK() {
      const step = DEMO_PROJECT.steps[stepI];
      const row = step.check.expect_rows[0];
      await sleep(1600);
      visionCalls++;
      if (visionCalls === 1) {
        const detail = `That went into row ${row + 1}, it should be row ${row}.`;
        log({ step: step.id, check: "vision", result: "fail", detail, frame: "", rows_found: [row + 1] });
        retry = detail + " Move it and say done.";
      } else {
        const detail = `Row ${row}, ${step.check.wire_colour} wire in place. Looks good.`;
        log({ step: step.id, check: "vision", result: "pass", detail, frame: "", rows_found: [row] });
        await say(detail);
        stepI++;
      }
      return "STEP";
    },
    async MEASURE() {
      await say("Measuring the blink rate.");
      await sleep(2600);
      const hz = freq();
      const ok = Math.abs(hz - F) <= 0.25 * F;
      log({ check: "measure", result: ok ? "pass" : "fail", detail: `predicted ${F.toFixed(2)} Hz, measured ${hz.toFixed(2)} Hz` });
      await say(`Predicted ${F.toFixed(2)} hertz, measured ${hz.toFixed(2)}, ${ok ? "within" : "outside"} tolerance.`);
      return ok ? "DONE" : "DEBUG";
    },
    async DONE() {
      await ask("Your blinker is working. Tell me if anything stops working.", new Set());
      // The demo's fault: the user has pulled the reset jumper.
      pulled = true;
      emit({ type: "board", pulled: "reset" });
      return "DEBUG";
    },
    async DEBUG() {
      await say("Let me measure.");
      await sleep(1800);
      let r;
      if (pulled) r = { ok: false, node: "RESET (pin 4)", reading: "pin 4 is at 0.02 volts", hint: "The chip is held in reset. Tie pin 4 to the 5 volt rail." };
      else r = { ok: true, node: null, reading: "the output is running at 0.97 hertz", hint: "Everything measures healthy." };
      log({ check: "probe", result: r.ok ? "pass" : "fail", node: r.node, detail: r.reading });
      await say(r.ok ? r.hint : `I measured that ${r.reading}. ${r.hint}`);
      if (r.ok) return resume;
      await ask("Say done when you've fixed it.", new Set(["DONE"]));
      pulled = false;
      emit({ type: "board", restored: "reset" });
      return "DEBUG";
    },
  };

  async function run() {
    emit({ type: "hello", project: DEMO_PROJECT, mode: "demo" });
    for (;;) {
      const next = await states[state]();
      if (next === "DEBUG" && state !== "DEBUG") resume = state === "MEASURE" || state === "DONE" ? "MEASURE" : state;
      if (next !== state) log({ transition: next });
      state = next;
    }
  }

  return {
    start: run,
    send(text) {
      if (waiter) { const w = waiter; waiter = null; w(text); } else inbox.push(text);
    },
  };
}
