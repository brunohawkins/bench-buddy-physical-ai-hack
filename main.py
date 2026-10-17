"""Entry point.

    python main.py --fake                 # everything fake: no hardware, no API keys, no packages
    python main.py --fake vision bench    # real voice + brain, fake vision + bench
    python main.py                        # everything real
"""
import argparse
import os
import threading

from fsm import BenchBuddy

MODULES = ("vision", "voice", "brain", "bench")


def build(fake: set[str], args):
    if "vision" in fake:
        from vision import FakeVision
        vision = FakeVision()
    else:
        from camera import Camera, parse_source
        from vision import Vision
        vision = Vision(Camera(parse_source(os.environ.get("CAMERA_SOURCE", "0"))))

    if "voice" in fake:
        from voice import FakeVoice
        voice = FakeVoice(speak=args.speak)
    else:
        from voice import Voice
        voice = Voice()

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
        bench = Bench(os.environ["SERIAL_PORT"])

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
    p.add_argument("--fault", choices=("reset", "none"), default="reset",
                   help="fault the fake bench develops after the first measurement")
    p.add_argument("--speak", action="store_true", help="fake voice reads replies aloud with macOS say")
    args = p.parse_args()
    fake = set(MODULES) if args.fake == [] else set(args.fake or ())

    vision, voice, brain, bench = build(fake, args)
    buddy = BenchBuddy(vision, voice, brain, bench)

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
        else:
            run_quietly()
    except KeyboardInterrupt:
        pass
    print("\nbye")


if __name__ == "__main__":
    main()
