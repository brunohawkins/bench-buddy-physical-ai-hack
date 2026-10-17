"""Shared data types passed between modules. Changing one affects all three owners, so tell the team."""
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class Snapshot:
    """A stable, top-down (warped) image of the board."""
    image: Any          # numpy BGR array; None in fake mode
    path: str = ""      # where it was saved under frames/


@dataclass
class CheckResult:
    status: Literal["pass", "fail", "unsure"]
    detail: str                                   # spoken and logged, e.g. "That went into row 14, it should be row 13."
    rows_found: list[int] = field(default_factory=list)
    frame: str = ""                               # path to the annotated jpg


IntentKind = Literal["PARTS", "DONE", "NOT_WORKING", "QUESTION", "REPEAT", "OTHER"]


@dataclass
class Intent:
    kind: IntentKind
    question: str | None = None                   # set when kind == "QUESTION"


@dataclass
class ProbeResult:
    ok: bool
    failed_node: str | None                       # e.g. "RESET (pin 4)"
    reading: str                                  # spoken, e.g. "pin 4 is at 0.02 volts"
    hint: str                                     # one sentence telling the user what to fix
