"""Python side of the Arduino serial protocol (see PLAN.md). Owner: H."""
import time


class BenchError(RuntimeError):
    pass


class Bench:
    def __init__(self, port: str, baud: int = 115200):
        import serial
        self.ser = serial.Serial(port, baud, timeout=2)
        time.sleep(2)                    # opening the port resets the Uno
        self.ser.reset_input_buffer()
        if not self.ping():
            raise BenchError(f"no PING reply on {port}")

    def _cmd(self, line: str, wait: float = 2.0) -> list[str]:
        """Send one command, return the words after OK. One retry on silence; raises on ERR."""
        self.ser.timeout = wait
        reply = ""
        for _ in range(2):
            self.ser.reset_input_buffer()
            self.ser.write((line + "\n").encode())
            reply = self.ser.readline().decode(errors="replace").strip()
            if reply:
                break
        if not reply:
            raise BenchError(f"no reply to {line!r}")
        if reply != "OK" and not reply.startswith("OK "):
            raise BenchError(f"{line!r} -> {reply!r}")
        return reply.split()[1:]

    def ping(self) -> bool:
        return self._cmd("PING") == []

    def read(self, pin: str) -> int:
        """Millivolts."""
        return int(self._cmd(f"READ {pin}")[0])

    def sample(self, pin: str, ms: int) -> tuple[int, int, int]:
        """Min, max, mean millivolts over ms."""
        lo, hi, mean = map(int, self._cmd(f"SAMPLE {pin} {ms}", wait=ms / 1000 + 2))
        return lo, hi, mean

    def freq(self, ms: int = 4000) -> float:
        """Hz on D2, from the time between rising edges."""
        return float(self._cmd(f"FREQ {ms}", wait=ms / 1000 + 2)[0])


class FakeBench:
    """Scripted circuit for --fake runs that follows the demo: healthy until the first
    frequency measurement, then the reset jumper is "pulled" (if fault="reset"), then
    "reconnected" once debug has read it."""

    def __init__(self, fault: str | None = "reset"):
        self.fault = fault
        self.armed = False
        self.pulled = False

    def ping(self) -> bool:
        return True

    def read(self, pin: str) -> int:
        if pin == "A2" and self.pulled:
            self.pulled = False          # debug has seen it; the user reconnects the wire
            return 20
        return {"A0": 4980, "A2": 4970}.get(pin, 0)

    def sample(self, pin: str, ms: int) -> tuple[int, int, int]:
        if pin == "A1" and not self.pulled:
            return 1690, 3310, 2510
        return 10, 30, 20

    def freq(self, ms: int = 4000) -> float:
        if self.pulled:
            return 0.0
        if self.fault and not self.armed:
            self.armed = True
            self.pulled = True           # takes effect after this healthy reading
        return 0.97
