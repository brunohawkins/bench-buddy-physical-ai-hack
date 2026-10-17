"""Entry point.

    python main.py --fake                 # everything fake: no hardware, no API keys, no packages
    python main.py --fake vision bench --ptt   # push-to-talk (Enter) instead of hands-free listening
    python main.py --script               # the old fixed 555 script (fsm.py) instead of tutor mode
    python main.py --fake vision bench    # real voice + brain, fake vision + bench
    python main.py                        # everything real
    python main.py --fake --ui            # browser UI on http://localhost:8000 instead of the terminal
"""
import argparse
import os
import threading

from fsm import BenchBuddy
from tutor import Tutor

MODULES = ("vision", "voice", "brain", "bench")


def build(fake: set[str], args):
    if "vision" in fake:
        from vision import FakeVision
        vision = FakeVision()
    else:
        from camera import Camera, default_source
        from vision import Vision
        vision = Vision(Camera(default_source()))

    if "voice" in fake:
        from voice import FakeVoice
        voice = FakeVoice(speak=args.speak)
    else:
        from voice import Voice
        voice = Voice(hands_free=not args.ptt)

    if "brain" in fake:
        from brain import FakeBrain
        brain = FakeBrain()
    else:
        from brain import Brain
        brain = Brain()

    if "bench" in fake:
        from bench_serial import FakeBench
        bench = FakeBench(fault=None if args.fault == "none" else args.fault)
    else:
        from bench_serial import Bench
        try:
            bench = Bench(os.environ["SERIAL_PORT"])
        except Exception as e:                      # the radar demo has no Arduino
            if args.script:
                raise
            print(f"[main] no Arduino ({e!r}); running without measurements")
            bench = None

    return vision, voice, brain, bench


def main():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    p = argparse.ArgumentParser(description="Bench Buddy")
    p.add_argument("--fake", nargs="*", choices=MODULES, metavar="MODULE",
                   help=f"use fakes for these modules ({', '.join(MODULES)}); all of them if none listed")
    p.add_argument("--script", action="store_true", help="run the fixed 555 script (fsm.py) instead of tutor mode")
    p.add_argument("--ptt", action="store_true", help="push-to-talk with Enter (Space/mic in the UI) instead of hands-free listening")
    p.add_argument("--fault", choices=("reset", "none"), default="reset",
                   help="fault the fake bench develops after the first measurement")
    p.add_argument("--speak", action="store_true", help="fake voice reads replies aloud with macOS say")
    p.add_argument("--ui", action="store_true", help="talk to it in the browser (ui_server.py) instead of the terminal")
    p.add_argument("--port", type=int, default=8000, help="port for --ui")
    p.add_argument("--no-browser", action="store_true", help="with --ui, don't open a browser tab")
    args = p.parse_args()
    fake = set(MODULES) if args.fake == [] else set(args.fake or ())

    vision, voice, brain, bench = build(fake, args)
    if args.ui:
        from ui_server import UI, UIVoice
        ui = UI(port=args.port, vision=vision, voice=voice)
        voice = UIVoice(voice, ui)
    buddy = (BenchBuddy if args.script else Tutor)(vision, voice, brain, bench)
    if args.ui:
        ui.attach(buddy)
        ui.start(open_browser=not args.no_browser)

    def run_quietly():
        try:
            buddy.run()
        except (KeyboardInterrupt, EOFError):
            pass

    try:
        if hasattr(vision, "show_forever"):
            # macOS only allows OpenCV windows on the main thread, so the state machine runs beside it.
            fsm = threading.Thread(target=run_quietly, daemon=True)
            fsm.start()
            vision.show_forever(stop=lambda: not fsm.is_alive())
        elif args.ui:
            # Keep the main thread free for Ctrl-C while the page drives the state machine.
            fsm = threading.Thread(target=run_quietly, daemon=True)
            fsm.start()
            while fsm.is_alive():
                fsm.join(0.5)
        else:
            run_quietly()
    except KeyboardInterrupt:
        pass
    finally:
        close = getattr(voice, "close", None)
        if close:
            close()
    print("\nbye")


if __name__ == "__main__":
    main()
