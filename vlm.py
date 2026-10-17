"""Vision-model second opinion (OpenAI). Owner: V.

The real-time loop is OpenCV (vision.py). This runs on events, in the background: it is shown the
flat board with row numbers and column letters drawn on and the changed area outlined, and says what
was placed, where its legs are, and whether anything looks wrong. 1-3 s per call, so never in the loop.

    OPENAI_API_KEY in .env; OPENAI_VISION_MODEL to override the model.
"""
import base64
import json
import os

DEFAULT_MODEL = "gpt-4o-mini"

PROMPT = """This is a top-down photo of a breadboard, warped flat. Row numbers run along the top, column \
letters a-j down the left side. The power rails are above and below the holes: a red stripe marks +, a \
blue stripe marks -. The yellow outline marks what just changed; circles mark wire plugs that were found.

The parts in this project are: jumper wires (black plug housings), an LD2402 radar module (small PCB with \
pins V, G, IO, TX, RX), a resistor, and an LED.

Say what was just placed or removed, which rows its legs or pins are in, and anything that looks wrong, \
for example both LED legs in the same row (shorted) or a part not pushed in. If unsure, say so.

Reply as JSON only: {"component": str, "action": "placed"|"removed"|"unclear", "rows": [int], \
"rails": [str], "problem": str or null, "summary": "one short sentence to say out loud"}"""


def available() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY")) and os.environ.get("VISION_VLM", "1") != "0"


def describe(image_bgr, question: str | None = None, timeout: float = 20) -> dict:
    """Ask the vision model about a labelled board image. Raises on API errors."""
    import cv2
    from openai import OpenAI
    ok, jpg = cv2.imencode(".jpg", image_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise ValueError("couldn't encode image")
    url = "data:image/jpeg;base64," + base64.b64encode(jpg.tobytes()).decode()
    text = PROMPT + (f"\n\nAlso answer: {question}" if question else "")
    resp = OpenAI().chat.completions.create(
        model=os.environ.get("OPENAI_VISION_MODEL") or DEFAULT_MODEL,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": [{"type": "text", "text": text},
                                               {"type": "image_url", "image_url": {"url": url, "detail": "high"}}]}],
        timeout=timeout)
    return json.loads(resp.choices[0].message.content)


def labelled_crop(board, warped, overlay=None, expect_rows=(), pad_rows: int = 6):
    """The flat board with every row numbered and the change outlined, cropped around the change."""
    import cv2
    import numpy as np
    from calibrate import PITCH, TOP_COL
    from vision import draw_result
    img = draw_result(board, warped.copy(), overlay, expect_rows)
    for r in range(1, board.rows + 1):                      # number every row, not just every 5th
        x, y = board.hole_xy(r, TOP_COL)
        cv2.putText(img, str(r), (x - 7, y - int(1.6 * PITCH)), cv2.FONT_HERSHEY_SIMPLEX, 0.33, (60, 60, 60), 1, cv2.LINE_AA)
    if overlay is not None and overlay.get("mask") is not None and overlay["mask"].any():
        xs = np.nonzero(overlay["mask"].any(axis=0))[0]
        x0 = max(0, int(xs.min() - pad_rows * PITCH))
        x1 = min(img.shape[1], int(xs.max() + pad_rows * PITCH))
        img = img[:, x0:x1]
    return cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)


if __name__ == "__main__":
    # python vlm.py path/to/flat_board.png  -> ask about a saved image (e.g. frames/debug/*_after.png)
    import sys
    import cv2
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    print(json.dumps(describe(cv2.imread(sys.argv[1])), indent=2))
