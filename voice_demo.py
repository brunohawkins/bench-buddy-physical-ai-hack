"""Talk to Bench Buddy hands-free: real voice + LLM, fake camera + Arduino. Owner: L.

    .venv/bin/python voice_demo.py            (same as: python main.py --fake vision bench)
    .venv/bin/python voice_demo.py --ptt      press Enter to talk instead
"""
import sys

import main

sys.argv = [sys.argv[0], "--fake", "vision", "bench", *sys.argv[1:]]
main.main()
