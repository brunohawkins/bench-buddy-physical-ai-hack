"""Vision model (OpenAI): judges what changed on the board and which holes. Owner: V.

The real-time loop is OpenCV (vision.py): grid, stillness, where and when something changed, hands, LED glow.
When the board settles after a change, judge() is shown labelled BEFORE/AFTER crops of that area (every row
numbered, the change outlined: set-of-mark prompting, arXiv 2310.11441) and names the part and its holes.
On our frames gpt-6-astra read the plug's hole right 4/4 (gpt-4o-mini 0/4, gpt-4.1 0/4), ~3.5 s per call.

    OPENAI_API_KEY in .env; OPENAI_VISION_MODEL to override the model; VISION_VLM=0 to use OpenCV only.
"""
import base64
import json
import os
import re

DEFAULT_MODEL = "gpt-6-astra"
ORIGINAL_DETAIL = ("gpt-5.4", "gpt-5.5", "gpt-5.6", "gpt-6")   # models that take detail="original"

PROMPT = """This is a top-down photo of a breadboard, warped flat. Row numbers run along the top, column \
letters a-j down the left side. The power rails are above and below the holes: a red stripe marks +, a \
blue stripe marks -. The yellow outline marks what just changed; circles mark wire plugs that were found.

The parts in this project are: jumper wires (black plug housings), an LD2402 radar module (small PCB with \
pins V, G, IO, TX, RX), a resistor, and an LED.

Say what was just placed or removed, which rows its legs or pins are in, and anything that looks wrong, \
for example both LED legs in the same row (shorted) or a part not pushed in. Only name a part you can \
actually see in the image: most changes are a single jumper wire (coloured cable, black plug). Do not \
name the radar module unless its circuit board is visible. Often nothing new was plugged in and only a \
loose cable shifted: then say action "none". If unsure, say so.

Reply as JSON only: {"component": str, "action": "placed"|"removed"|"none"|"unclear", "rows": [int], \
"rails": [str], "problem": str or null, "summary": "one short sentence to say out loud"}"""


def available() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY")) and os.environ.get("VISION_VLM", "1") != "0"


JUDGE_PROMPT = """Photos of one breadboard: {images}. In the flattened images row numbers are \
printed above and below the holes; column letters a-e are the top half (a at the top) and f-j the bottom half. The \
power rails run along the long edges: "top" rails above column a, "bottom" rails below column j; the red stripe \
marks + and the blue stripe marks -. The yellow outline marks where the pixels changed. The flattening uses a computed grid that can be off (the \
board gets pushed): if its numbers don't line up with the board's own printed row numbers and letters in the camera \
photos, trust the board's printing, and say "grid misaligned" in "problem".

Parts in this project: jumper wires (coloured cable, black plug at each end), an LD2402 radar module (small PCB, \
pins V G IO TX RX), a resistor, an LED.

Parts already on the board before this change (from earlier looks, may be incomplete):
{board}

What was said at the bench just before (context only: it tells you what the user is trying to do, but the photos \
decide which holes things are in; say so in "problem" if they disagree):
{context}

Current build task and target circuit (instructions, NOT evidence of placement):
{task}

1. What was plugged in or pulled out between BEFORE and AFTER? Give the exact hole of every plug or leg: look where \
it enters the board, not where the cable goes. A cable that only shifted, a hand, or a shadow is not a change.
2. The full list of parts on the board AFTER the change, keeping earlier parts that are still there. A wire whose \
second end goes in later is the same wire: add the end to it.
3. Check the new placement against the CURRENT step, and the whole visible circuit against the target and completed \
steps. Report wrong holes, wrong rails, disconnected junctions, bypassed resistors and shorts immediately. A build \
in progress is not a fault: missing future parts or the second action of an unfinished step are not "wrong".
Electrical rules: a-e of one row are connected; f-j of that row form a DIFFERENT node across the centre gap. \
Two LED legs in d35 and e35 are shorted; e35 and f35 are NOT shorted. Top and bottom rails are separate, and \
some rails split halfway: do not assume continuity across a gap without a visible jumper. Cable crossings do not \
connect. Use lead colours only when the user identified their pin labels; never assume black means ground. \
Do not infer hidden LED polarity, resistor value or a hidden pin from its intended position.
An unlit LED still has a small coloured/clear dome and two thin metal legs. Seeing its body is evidence that \
the LED is present even when its legs cannot be resolved. Report "LED visible, leg holes unclear" as a warning; \
do not call it missing or require it to glow. Any extra AFTER detail photo is a crop of the same current view; \
use the full overview to find parts outside that crop.
LED legs can bend sideways under the dome: follow each metal leg all the way to its insertion hole. The dome's \
row is NOT a leg's row. For any LED placement assessment also return led_holes (the two directly visible entry \
holes, or [] if either is obscured). Earlier LED coordinates and spoken corrections may be wrong; re-read them.
Use severity "wrong" ONLY for a clearly visible wiring error with a specific correction. Give the observed \
hole/rail and the intended destination in fix, naming the lead or leg unambiguously. If polarity is hidden, \
ask them to identify the short/long leg before moving it. Use "warning" for occlusion, ambiguous holes, unknown \
lead colours or grid problems; never invent a hole or accuse the builder when unsure. Put the most urgent error \
first. If no error remains, problem, fix and severity must be null. Recheck old problems against AFTER.
Holes are written "d20" (column letter + row) or, on a power rail, "+top20", "-top20", "+bottom20", "-bottom20" \
(rail + nearest row number).

Reply JSON only:
{{"changes": [{{"part": "wire"|"radar"|"resistor"|"led"|"other", "action": "placed"|"removed", "holes": ["d20"], \
"colour": "<cable or body colour, or null>"}}],
"board": [{{"id": "<short stable id, e.g. wire1, radar, r1, led>", "part": "wire"|"radar"|"resistor"|"led"|"other", \
"colour": "<colour or null>", "holes": ["d20", "+top20"]}}],
"problem": "<anything wrong, e.g. LED legs in the same row, or null>",
"fix": "<one concise actionable correction, or null>", "severity": "wrong"|"warning"|null,
"grid": "aligned"|"misaligned"|"uncertain", "led_holes": ["<visible LED entry holes, or empty>"],
"summary": "<what just changed, one short sentence to say out loud, or empty>",
"narration": "<two or three plain sentences describing the whole board as it is now, for someone who can't see it>"}}
If nothing was plugged in or pulled out, "changes" is []. Still inspect the whole board: at startup the earlier \
list may be empty, and a corrected grid may reveal an earlier misread. Update "board" from what is visible."""


def _model() -> str:
    return os.environ.get("OPENAI_VISION_MODEL") or DEFAULT_MODEL


def _ask(text: str, images: list, timeout: float) -> dict:
    """One Responses API call with text and BGR images; returns the parsed JSON reply."""
    import cv2
    from openai import OpenAI
    model = _model()
    detail = "original" if model.startswith(ORIGINAL_DETAIL) else "high"
    content = [{"type": "input_text", "text": text}]
    for img in images:
        ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            raise ValueError("couldn't encode image")
        content.append({"type": "input_image", "detail": detail,
                        "image_url": "data:image/jpeg;base64," + base64.b64encode(jpg.tobytes()).decode()})
    # The next settled frame is the retry; SDK retries would hold up fresh observations behind an old image.
    resp = OpenAI(max_retries=0).responses.create(model=model, input=[{"role": "user", "content": content}], timeout=timeout)
    out = resp.output_text.strip()
    out = out[out.find("{"): out.rfind("}") + 1]                 # tolerate ```json fences
    return json.loads(out)


def camera_view(frame, board=None, max_w: int = 1280):
    """The raw camera frame, cropped to the board (generously) and shrunk, for the model to cross-check the grid."""
    import cv2
    import numpy as np
    img = frame
    if board is not None:
        pts = board.hole_cam
        x0, y0 = pts.min(axis=0)
        x1, y1 = pts.max(axis=0)
        pad = 0.25 * max(x1 - x0, y1 - y0)
        h, w = frame.shape[:2]
        img = frame[int(max(0, y0 - pad)):int(min(h, y1 + pad)), int(max(0, x0 - pad)):int(min(w, x1 + pad))]
    if img.shape[1] > max_w:
        img = cv2.resize(img, None, fx=max_w / img.shape[1], fy=max_w / img.shape[1], interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(img)


def step_rows(step: str) -> list[int]:
    """Rows mentioned in an instruction, for an extra close-up (never used as placement evidence)."""
    rows = set()
    for match in re.finditer(r"\brows?\s+(\d+)(?:\s*(?:and|to|[-–])\s*(\d+))?", step, re.I):
        rows.update(int(x) for x in match.groups() if x)
    return sorted(rows)


def camera_focus(frame, board, rows, pad_rows: int = 4):
    """A native-resolution crop around the requested rows, retaining both halves and the rails."""
    import numpy as np
    rows = [r for r in rows if isinstance(r, int) and 1 <= r <= board.rows]
    if not rows or frame is None:
        return None
    from calibrate import PITCH
    lo, hi = max(1, min(rows) - pad_rows), min(board.rows, max(rows) + pad_rows)
    x0 = board.hole_xy(lo, "a")[0] - PITCH
    x1 = board.hole_xy(hi, "a")[0] + PITCH
    pts = board.to_camera([(x0, 0), (x1, 0), (x1, board.size[1] - 1), (x0, board.size[1] - 1)])
    left, top = np.floor(pts.min(axis=0)).astype(int)
    right, bottom = np.ceil(pts.max(axis=0)).astype(int)
    height, width = frame.shape[:2]
    crop = frame[max(0, top):min(height, bottom + 1), max(0, left):min(width, right + 1)]
    return np.ascontiguousarray(crop) if crop.size else None


def judge(before_crop, after_crop, board: list | None = None, context: str | None = None,
          timeout: float = 45, cam_before=None, cam_after=None, task=None, focus=None) -> dict:
    """What was plugged in / pulled out between two labelled crops of the same area, the updated part list
    and a plain-English narration. board: the part list from the last judge() call. Raises on API errors."""
    known = json.dumps(_fresh_led_parts(board), separators=(",", ":")) if board else "(nothing yet)"
    images, names = [before_crop, after_crop], ["flattened BEFORE", "flattened AFTER"]
    if cam_before is not None and cam_after is not None:
        images, names = [cam_before, cam_after] + images, ["camera BEFORE", "camera AFTER"] + names
    if focus is not None:
        images.append(focus)
        names.append("camera AFTER detail around the current step's rows")
    return _ask(JUDGE_PROMPT.format(board=known, context=context or "(nothing)", images=", ".join(names),
                                   task=json.dumps(task or {})), images, timeout)


def validate_judgement(out, rows: int) -> dict:
    """Validate before changing live state. Malformed replies use the pixel fallback, never kill the watcher."""
    if not isinstance(out, dict):
        raise ValueError("vision reply must be an object")
    out = dict(out)
    if not {"problem", "fix", "severity", "grid"} <= out.keys():
        raise ValueError("incomplete wiring assessment")
    if out["severity"] not in ("wrong", "warning", None):
        raise ValueError("invalid severity")
    for field in ("changes", "board"):
        if not isinstance(out.get(field), list):
            raise ValueError(f"{field} must be a list")
        entries = []
        for part in out[field]:
            if not isinstance(part, dict) or part.get("part") not in ("wire", "radar", "resistor", "led", "other"):
                raise ValueError("invalid part")
            if field == "changes" and part.get("action") not in ("placed", "removed"):
                raise ValueError("invalid change action")
            if field == "board" and (not isinstance(part.get("id"), str) or not part["id"].strip()):
                raise ValueError("missing part id")
            if part.get("colour") is not None and not isinstance(part["colour"], str):
                raise ValueError("invalid colour")
            if not isinstance(part.get("holes"), list):
                raise ValueError("holes must be a list")
            holes = []
            for hole in part["holes"]:
                if not isinstance(hole, str):
                    raise ValueError("invalid hole")
                hole = hole.strip().lower()
                match = re.fullmatch(r"(?:[a-j]|[+-](?:top|bottom))([0-9]+)", hole)
                if not match or not 1 <= int(match[1]) <= rows:
                    raise ValueError(f"hole outside the board: {hole}")
                holes.append(hole)
            entries.append({**part, "holes": holes})
        out[field] = entries
    for field in ("problem", "fix", "summary", "narration"):
        value = out.get(field)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"invalid {field}")
        out[field] = value.strip() or None if value else None
    grid = out.get("grid", "aligned")
    if "grid misaligned" in (out["problem"] or "").lower():
        grid = "misaligned"                 # tolerate older model replies
    if grid not in ("aligned", "misaligned", "uncertain"):
        raise ValueError("invalid grid status")
    out["grid"] = grid
    severity = out["severity"]
    out["severity"] = ("wrong" if severity == "wrong" and out["fix"] and grid == "aligned"
                       else "warning") if out["problem"] else None
    if not out["problem"]:
        if out["fix"] or severity:
            raise ValueError("inconsistent wiring assessment")
        out["fix"] = None
    return out


VERIFY_PROMPT = """Photos of one breadboard: the camera view, then the same board flattened. The flattening uses a \
computed grid that can be off: trust the board's own printed numbers if they disagree. In the flattened image row numbers are printed above and below the holes; \
column letters a-e are the top half (a at the top) and f-j the bottom half. Power rails: "top" above column a, \
"bottom" below column j; red stripe +, blue stripe -.

Parts on the board (from earlier looks, may be incomplete): {board}

What was said at the bench (context: it tells you lead colours and what the user is doing; the photo decides):
{context}

The user was asked to do this step: "{step}"

Is the step done correctly, as far as the photo shows? Check the exact holes and rails. Breadboard rule: holes a-e \
of one row are connected; f-j of that row form a separate node across the centre gap. Separate top/bottom rails \
and visibly split rail segments need a jumper to connect them. A cable crossing is not a junction. The task in \
context gives the target circuit: fail for a clearly visible wiring error, even in an earlier step. Do not fail \
just because a future step is not built yet. Hidden LED polarity, resistor values, unknown lead identity and \
misaligned/occluded holes are unsure, never a guess. Give the exact observed and intended locations when wrong.
An optional final image is a native-resolution close-up of the requested rows, from the same camera frame. \
An unlit LED is still present: look for its small dome and thin metal legs, not emitted light. If its body is \
visible but its leg holes or polarity are hidden, say that explicitly and return unsure. Never say no LED is \
present just because you cannot verify its connections. Judge from the current images, not the earlier part list.
Follow bent LED legs to where they ENTER the plastic, never the position of the raised dome or a shadow. \
Return led_holes: the two directly visible entry holes, or [] if either is obscured. Read the holes afresh; \
earlier LED coordinates and spoken corrections may be wrong. If a separate blind LED reading is supplied, \
disagreement with your own reading means unsure, not a move instruction.

Reply JSON only: {{"status": "pass"|"fail"|"unsure", "detail": "<one or two short sentences to say out loud: what \
you see and, if wrong, exactly what to move where>", "led_holes": ["<visible entry holes, or empty>"]}}"""


def verify(image_bgr, step: str, board: list | None = None, context: str | None = None, timeout: float = 45,
           camera=None, focus=None) -> dict:
    """Does the board show this step done? -> {"status": pass|fail|unsure, "detail"}. Raises on API errors."""
    known = json.dumps(_fresh_led_parts(board), separators=(",", ":")) if board else "(nothing recorded yet)"
    images = [image_bgr] if camera is None else [camera, image_bgr]
    if focus is not None:
        images.append(focus)
    return _ask(VERIFY_PROMPT.format(board=known, context=context or "(nothing)", step=step), images, timeout)


def describe(image_bgr, question: str | None = None, timeout: float = 20, hint: str | None = None) -> dict:
    """Ask the vision model about one labelled board image. hint: what OpenCV saw. Raises on API errors."""
    text = PROMPT + (f"\n\nThe pixel tracker saw: {hint} (it can be wrong)." if hint else "") \
        + (f"\n\nAlso answer: {question}" if question else "")
    return _ask(text, [image_bgr], timeout)


def labelled_crop(board, warped, overlay=None, expect_rows=(), pad_rows: int = 6):
    """The flat board with every row numbered and the change outlined, cropped around the change."""
    import cv2
    import numpy as np
    from calibrate import PITCH, TOP_COL
    BOTTOM_COL = "a" if TOP_COL == "j" else "j"
    # Dot overlays obscured tiny metal legs and made adjacent-hole guesses look authoritative.
    # Keep all hole pixels intact; labels sit in the margins, without highlighting the target rows.
    img = warped.copy()
    for c in "abcdefghij":
        x, y = board.hole_xy(1, c)
        cv2.putText(img, c, (x - 28, y + 4), cv2.FONT_HERSHEY_SIMPLEX, .4, (60, 60, 60), 1, cv2.LINE_AA)
    for r in range(1, board.rows + 1):                      # number every row, not just every 5th
        x, y = board.hole_xy(r, TOP_COL)
        cv2.putText(img, str(r), (x - 7, y - int(1.6 * PITCH)), cv2.FONT_HERSHEY_SIMPLEX, 0.33, (60, 60, 60), 1, cv2.LINE_AA)
        xb, yb = board.hole_xy(r, BOTTOM_COL)
        cv2.putText(img, str(r), (xb - 7, yb + int(2.0 * PITCH)), cv2.FONT_HERSHEY_SIMPLEX, 0.33, (60, 60, 60), 1, cv2.LINE_AA)
    if overlay is not None and overlay.get("mask") is not None and overlay["mask"].any():
        xs = np.nonzero(overlay["mask"].any(axis=0))[0]
        x0 = max(0, int(xs.min() - pad_rows * PITCH))
        x1 = min(img.shape[1], int(xs.max() + pad_rows * PITCH))
        img = img[:, x0:x1]
    return cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)


LED_READING_PROMPT = """Independently locate the LED's two insertion holes in these CURRENT photos.
You have no target placement: report only visible evidence. The first photo is an unmarked overview; the
following panels show the same board with row/column rulers in the margins. No dots cover the holes.
An LED dome may lean several rows away from its legs. Trace BOTH thin metal legs to the holes where they
actually enter the plastic. Do not use the dome's centre, its shadow, the ends nearest the dome, or a nearby
resistor's leg. Count from visible neighbouring empty holes and cross-check the board's printed numbers.
If an entry point is blurred, hidden, between two possible holes, or the rulers disagree with printing, mark
entries_visible false. Do not guess a pair of adjacent holes just because that seems likely.
Return JSON: {"present": true|false|null, "entries_visible": true|false,
"holes": ["d12", "e14"], "grid": "aligned"|"misaligned"|"uncertain",
"evidence": "describe each metal leg's visible path and its entry point; say what prevents certainty"}.
The example coordinates describe the format only. holes must be [] unless both entry points are clear.
Do not infer LED polarity or whether the circuit is correct."""


def hole_detail(board, warped, rows):
    """Magnified half-board panels with rulers OUTSIDE the image, preserving every leg/entry pixel."""
    import cv2
    import numpy as np
    from calibrate import PITCH
    rows = [r for r in rows if 1 <= r <= board.rows]
    if not rows:
        rows = list(range(1, board.rows + 1))
    lo, hi = max(1, min(rows) - 5), min(board.rows, max(rows) + 5)
    x0 = board.hole_xy(lo, "a")[0] - PITCH // 2
    x1 = board.hole_xy(hi, "a")[0] + PITCH // 2
    panels = []
    for cols in ("abcde", "fghij"):
        y0 = board.hole_xy(lo, cols[0])[1] - PITCH // 2
        y1 = board.hole_xy(lo, cols[-1])[1] + PITCH // 2
        crop = cv2.resize(warped[y0:y1, x0:x1], None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        panel = cv2.copyMakeBorder(crop, 50, 50, 50, 50, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        for row in range(lo, hi + 1):
            x = round((board.hole_xy(row, cols[0])[0] + board.offsets[row][0] - x0) * 4 + 50)
            for y in (32, panel.shape[0] - 15):
                cv2.putText(panel, str(row), (x - 14, y), cv2.FONT_HERSHEY_SIMPLEX, .65, (0, 0, 0), 1, cv2.LINE_AA)
        for col in cols:
            y = (board.hole_xy(lo, col)[1] - y0) * 4 + 50
            for x in (15, panel.shape[1] - 30):
                cv2.putText(panel, col, (x, y + 7), cv2.FONT_HERSHEY_SIMPLEX, .7, (0, 0, 0), 1, cv2.LINE_AA)
        panels.append(panel)
    return np.vstack(panels)


def read_led(board, warped, rows, camera=None):
    """A second reading, blind to the desired placement, conversation and earlier model coordinates."""
    images = [warped if camera is None else camera, hole_detail(board, warped, rows)]
    out = _ask(LED_READING_PROMPT, images, timeout=30)
    if not isinstance(out, dict):
        raise ValueError("invalid LED evidence")
    holes = out.get("holes", [])
    if not isinstance(holes, list) or any(not isinstance(h, str) or not re.fullmatch(r"[a-j][1-9][0-9]*", h) for h in holes):
        raise ValueError("invalid LED holes")
    if any(int(h[1:]) > board.rows for h in holes):
        raise ValueError("LED hole outside board")
    out["certain"] = (out.get("present") is True and out.get("entries_visible") is True
                      and out.get("grid") == "aligned" and len(holes) == 2 and len(set(holes)) == 2)
    return out


def led_agrees(result, evidence):
    """No +/- one-row tolerance. Two independent, clear readings must name the same physical holes."""
    return bool(evidence and evidence.get("certain") and isinstance(result.get("led_holes"), list)
                and len(result["led_holes"]) == 2 and sorted(result["led_holes"]) == sorted(evidence["holes"]))


LED_UNCLEAR = ("I can't reliably distinguish the LED's two entry holes in this view. "
               "Leave it in place, clear your hands, and angle the camera so both legs entering the board are visible; "
               "then ask me to check again.")


def _fresh_led_parts(parts):
    # Retain identity/presence, but don't reinforce an earlier one-row error as established fact.
    return [{**part, "holes": []} if part.get("part") == "led" else part for part in (parts or [])]


def led_position_error(step, holes):
    """After independent visual agreement, enforce explicit LED row/half constraints in code."""
    if not re.search(r"\bled\b", step, re.I) or len(holes) != 2:
        return None
    expected = step_rows(step)
    if len(expected) != 2 or any(not re.fullmatch(r"[a-j]\d+", h) for h in holes):
        return None
    observed = sorted(int(h[1:]) for h in holes)
    split = (holes[0][0] <= "e") != (holes[1][0] <= "e")
    same_half = "same half" in step.lower()
    if observed != expected or (same_half and split):
        return (f"The LED's visible entry holes are {holes[0]} and {holes[1]}. "
                f"This step needs one leg in row {expected[0]} and one in row {expected[1]}"
                + (" on the same half of the board" if same_half else "")
                + ". Identify the long and short legs before reseating them as instructed.")
    return None


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
