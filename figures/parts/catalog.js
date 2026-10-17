// Every component the gallery shows and the exporter writes. "demo" marks the parts in
// bench-buddy's radar-led-demo.md. build(options) takes the part's own options (span, legs, …);
// "seated" are the options used when the part is pushed into a breadboard (legs trimmed so the
// body sits just above the board), and "span" says the part's leads can stretch over that many holes.
import * as basics from "./components/basics.js";
import * as demo from "./components/demo.js";
import { buildPi5, ASSEMBLIES as PI5_ASSEMBLIES } from "../pi5/model.js";

export const CATALOG = [
  { id: "hlk-ld2402-radar", title: "HLK-LD2402 radar", category: "Radar LED demo", demo: true, build: (o) => demo.radar(o) },
  { id: "breadboard-half", title: "Breadboard (half)", category: "Radar LED demo", demo: true, build: (o) => demo.breadboard(o) },
  { id: "breadboard-full", title: "Breadboard (full, 63 rows)", category: "Radar LED demo", demo: true, build: (o) => demo.breadboard({ rows: 63, ...o }) },
  { id: "breadboard-power-mb102", title: "Power module (MB102)", category: "Radar LED demo", demo: true, build: (o) => demo.powerModule(o) },
  { id: "led-5mm-red", title: "5 mm LED (red)", category: "Radar LED demo", demo: true, build: (o) => basics.led({ colour: "red", ...o }), seated: { legs: 7 } },
  { id: "resistor-1k", title: "Resistor 1 kΩ", category: "Radar LED demo", demo: true, build: (o) => basics.resistor({ ohms: 1000, ...o }), seated: { legs: 6.6 }, span: 4 },
  { id: "capacitor-100uf", title: "Capacitor 100 µF", category: "Radar LED demo", demo: true, build: (o) => basics.electrolytic(o), seated: { legs: 6.5 } },
  { id: "jumper-wires-mm", title: "Jumper wires", category: "Radar LED demo", demo: true, build: (o) => demo.jumperWires(o), seated: { count: 1 }, span: 6 },
  { id: "jetson-nano-devkit", title: "Jetson Nano", category: "Radar LED demo", demo: true, build: (o) => demo.jetsonNano(o) },
  { id: "csi-camera-v2", title: "CSI camera (IMX219)", category: "Radar LED demo", demo: true, build: (o) => demo.csiCamera(o) },
  { id: "resistor-220r", title: "Resistor 220 Ω", category: "Basics", build: (o) => basics.resistor({ ohms: 220, ...o }), seated: { legs: 6.6 }, span: 4 },
  { id: "resistor-10k", title: "Resistor 10 kΩ", category: "Basics", build: (o) => basics.resistor({ ohms: 10000, ...o }), seated: { legs: 6.6 }, span: 4 },
  { id: "capacitor-ceramic-100nf", title: "Ceramic cap 100 nF", category: "Basics", build: (o) => basics.ceramicCap(o), seated: { legs: 6.5 }, span: 2 },
  { id: "capacitor-ceramic-10nf", title: "Ceramic cap 10 nF", category: "Basics", build: (o) => basics.ceramicCap({ nf: 10, ...o }), seated: { legs: 6.5 }, span: 2 },
  { id: "capacitor-10uf", title: "Capacitor 10 µF", category: "Basics", build: (o) => basics.electrolytic({ uf: 10, volts: 25, ...o }), seated: { legs: 6.5 } },
  { id: "resistor-68k", title: "Resistor 68 kΩ", category: "Basics", build: (o) => basics.resistor({ ohms: 68000, ...o }), seated: { legs: 6.6 }, span: 4 },
  { id: "resistor-330r", title: "Resistor 330 Ω", category: "Basics", build: (o) => basics.resistor({ ohms: 330, ...o }), seated: { legs: 6.6 }, span: 4 },
  { id: "transistor-2n2222a", title: "2N2222A NPN", category: "Basics", build: (o) => basics.to92(o), seated: { legs: 7.5 } },
  { id: "mosfet-irlz44n", title: "IRLZ44N MOSFET", category: "Basics", build: (o) => basics.to220(o), seated: { legs: 8.5 } },
  { id: "diode-1n4007", title: "1N4007 diode", category: "Basics", build: (o) => basics.diode({ glass: false, ...o }), seated: { legs: 6.6 }, span: 4 },
  { id: "diode-1n4148", title: "1N4148 diode", category: "Basics", build: (o) => basics.diode({ glass: true, ...o }), seated: { legs: 6.6 }, span: 4 },
  { id: "button-tactile-6mm", title: "Tactile button", category: "Basics", build: (o) => basics.tactile(o) },
  { id: "ic-ne555-dip8", title: "NE555 timer", category: "Basics", build: (o) => basics.dip8(o) },
  { id: "arduino-uno", title: "Arduino Uno", category: "Boards", build: (o) => demo.arduinoUno(o) },
  { id: "raspberry-pi-5-4gb", title: "Raspberry Pi 5 (4 GB)", category: "Boards", build: () => ({ ...buildPi5(), assemblies: PI5_ASSEMBLIES }) },
];
