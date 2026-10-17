# Parts gallery and breadboard twin

3D component models plus a simulated copy of the user's breadboard that follows the real bench.

```bash
cd figures                       # inside bench-buddy
npm install                      # three + esbuild
node parts/build.mjs             # → parts/index.html (single file, works offline from disk)
node parts/export.mjs            # → parts/glb/*.glb + manifest.json (pins, holes, specs)
node parts/circuit.test.mjs && node parts/twin.test.mjs && node parts/projects.test.mjs
```

Open `parts/index.html`, press **Breadboard (B)**. Buttons load the radar LED demo or Bench Buddy's 555
blinker; **Follow Bench Buddy** mirrors a live run (below).

## Files

| File | What |
|---|---|
| `kit.js`, `components/*.js` | Part models (three.js, mm). Leaded parts take `span` / `legs` and report `pins`, `tip`, `insert` |
| `catalog.js` | Every part, with breadboard defaults (`seated`, `span`) |
| `board.js` | Breadboard mode: snapping, wires, devices, projects, live visuals |
| `circuit.js` | Solver: nodal analysis + Newton (diodes, BJT, MOSFET), backward-Euler capacitors |
| `electrical.js` | What each part does electrically (LED, 555 latch, radar IO, MB102 rails, Arduino 5 V + inputs …) |
| `twin.js` | Layout → nets → simulation; measurements, mismatch check, single-fault diagnosis |
| `projects.js` | Bench Buddy projects as layouts: base build, per-step placements, Arduino test points |
| `live.js` | Turns FSM log lines into twin updates |
| `../../twin_feed.py` | Streams `log.jsonl` as SSE (CORS open) on :8766 |

## How the twin stays in step with the bench

```bash
cd .. && python twin_feed.py            # tails ./log.jsonl
python main.py --fake                            # or the real thing
# open figures/parts/index.html?live=http://localhost:8766
```

| FSM log line | Twin does |
|---|---|
| `said: "Hi, I'm Bench Buddy."` | reset to the project's start |
| `check: vision, result: pass` | place the step's parts where the project says |
| `check: vision, result: fail` ("row 14") | place them in row 14 instead, tinted red |
| `check: measure` with `step` | pass → flip the step's inputs (Arduino plugged in); reading → pinned to that test point |
| `check: measure` ("measured 0.97 Hz") | compared with the simulated blink rate |
| `check: probe` ("pin 4 is at 0.02 volts") | reading at the test point; on a mismatch, diagnose and pulse the suspect part |

`twin.apply(event)` takes the same updates as JSON from anything else:
`{type:"layout"|"place"|"remove"|"set"|"measure", …}` (see `twin.js`).

## Limits

- One behavioural model per module (radar, MB102, Arduino); no RF, no UART traffic.
- The 555 is a latch-and-comparator model, so blink timing is right to a few % but edges are ideal.
- Diagnosis tries single faults only (a lead out, a part missing, a polarised part reversed).
- Jetson Nano port layout is approximate; LD2402 pinout follows the demo doc (V G IO TX RX).
