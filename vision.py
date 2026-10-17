"""Placement checks on the warped board. Owner: V."""
from contracts import CheckResult, Snapshot


class Vision:
    def __init__(self, camera):
        import calibrate
        self.camera = camera
        self.corners = calibrate.load()

    def snapshot(self) -> Snapshot:
        """Stable warped board image, saved to frames/."""
        raise NotImplementedError("TODO(V): wait for 1 s of no motion, warp, save")

    def check_placement(self, before: Snapshot, expect_rows: list[int], wire_colour: str | None) -> CheckResult:
        raise NotImplementedError(
            "TODO(V): two snapshots 1 s apart; diff each against `before`; changed holes -> rows; "
            "HSV colour at expected holes; pass/fail only if both agree, else unsure")


class FakeVision:
    """Fails the first check one row off, then passes, to exercise the retry path."""

    def __init__(self):
        self.calls = 0

    def snapshot(self) -> Snapshot:
        return Snapshot(image=None)

    def check_placement(self, before: Snapshot, expect_rows: list[int], wire_colour: str | None) -> CheckResult:
        self.calls += 1
        row = expect_rows[0]
        if self.calls == 1:
            return CheckResult("fail", f"That went into row {row + 1}, it should be row {row}.", [row + 1])
        return CheckResult("pass", f"Row {row}, {wire_colour or 'wire'} in place. Looks good.", [row])
