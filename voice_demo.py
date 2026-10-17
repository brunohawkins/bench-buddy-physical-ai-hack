"""Try the voice layer on its own: talk, hear it repeat what it heard, see the latency. Owner: L.

    python voice_demo.py
"""
from dotenv import load_dotenv

load_dotenv()
from voice import Voice  # noqa: E402  (needs .env loaded first)

v = Voice()
greeting = "Hi, I'm Bench Buddy. Say something and I'll repeat it."
v.warm_cache([greeting])
v.say(greeting)
print(f"  speech started after {v.last_latency_ms} ms (cached)\n")

while True:
    text = v.listen()
    if text.lower() in ("q", "quit", "exit"):
        break
    stt = f"transcribed in {v.last_stt_ms} ms" if v.last_stt_ms is not None else "typed"
    v.say(f"I heard: {text}")
    print(f"  {stt}; speech started after {v.last_latency_ms} ms (live)")
    v.say(f"I heard: {text}")
    print(f"  same line again: {v.last_latency_ms} ms (cached)\n")
