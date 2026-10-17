// Bench Buddy serial firmware. Owner: H. Protocol in PLAN.md.
// 115200 baud, one command per line, one reply per line:
//   PING              -> OK
//   READ A0           -> OK <mV>
//   SAMPLE A1 3000    -> OK <min mV> <max mV> <mean mV>
//   FREQ 4000         -> OK <Hz> <edges>     (from the time between rising edges on D2)
//   anything else     -> ERR <reason>

const byte FREQ_PIN = 2;               // 555 pin 3 (OUT); interrupt pin on the Uno/Nano
const unsigned long MAX_MS = 10000;

volatile unsigned int edges = 0;
volatile unsigned long firstEdge = 0;
volatile unsigned long lastEdge = 0;

void onEdge() {
  unsigned long t = micros();
  if (edges == 0) firstEdge = t;
  lastEdge = t;
  edges++;
}

// "A0".."A7" -> analog pin number, or -1
int analogPin(const String &name) {
  if (name.length() == 2 && name[0] == 'A' && name[1] >= '0' && name[1] <= '7') return A0 + (name[1] - '0');
  return -1;
}

// Assumes the 5 V rail is exactly 5 V; USB power is often 4.7-5.1 V.
long readMv(int pin) {
  return (long)analogRead(pin) * 5000L / 1023L;
}

void setup() {
  Serial.begin(115200);
  pinMode(FREQ_PIN, INPUT);
}

void loop() {
  if (!Serial.available()) return;

  String line = Serial.readStringUntil('\n');
  line.trim();
  int sp = line.indexOf(' ');
  String cmd = sp < 0 ? line : line.substring(0, sp);
  String args = sp < 0 ? "" : line.substring(sp + 1);
  args.trim();

  if (cmd == "PING") {
    Serial.println("OK");

  } else if (cmd == "READ") {
    int pin = analogPin(args);
    if (pin < 0) { Serial.println("ERR usage: READ <A0-A7>"); return; }
    Serial.print("OK ");
    Serial.println(readMv(pin));

  } else if (cmd == "SAMPLE") {
    int sp2 = args.indexOf(' ');
    int pin = analogPin(sp2 < 0 ? args : args.substring(0, sp2));
    unsigned long ms = sp2 < 0 ? 0 : args.substring(sp2 + 1).toInt();
    if (pin < 0 || ms == 0 || ms > MAX_MS) { Serial.println("ERR usage: SAMPLE <A0-A7> <1-10000 ms>"); return; }
    long lo = 5000, hi = 0, sum = 0, n = 0;
    unsigned long start = millis();
    while (millis() - start < ms) {
      long v = readMv(pin);
      if (v < lo) lo = v;
      if (v > hi) hi = v;
      sum += v;
      n++;
    }
    Serial.print("OK ");
    Serial.print(lo); Serial.print(' ');
    Serial.print(hi); Serial.print(' ');
    Serial.println(sum / n);

  } else if (cmd == "FREQ") {
    unsigned long ms = args.toInt();
    if (ms == 0 || ms > MAX_MS) { Serial.println("ERR usage: FREQ <1-10000 ms>"); return; }
    noInterrupts(); edges = 0; interrupts();
    attachInterrupt(digitalPinToInterrupt(FREQ_PIN), onEdge, RISING);
    delay(ms);
    detachInterrupt(digitalPinToInterrupt(FREQ_PIN));
    noInterrupts();
    unsigned int n = edges;
    unsigned long span = lastEdge - firstEdge;
    interrupts();
    float hz = (n >= 2 && span > 0) ? (n - 1) * 1e6 / span : 0.0;
    Serial.print("OK ");
    Serial.print(hz, 3); Serial.print(' ');
    Serial.println(n);

  } else {
    Serial.print("ERR unknown command ");
    Serial.println(cmd);
  }
}
