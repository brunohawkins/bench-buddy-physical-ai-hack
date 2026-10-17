"""555 astable maths. Owner: H."""


def predict(r1: float, r2: float, c: float) -> tuple[float, float]:
    """Predicted frequency (Hz) and duty cycle (0-1)."""
    f = 1.44 / ((r1 + 2 * r2) * c)
    duty = (r1 + r2) / (r1 + 2 * r2)
    return f, duty


def within(measured: float, predicted: float, tol: float = 0.25) -> bool:
    """±25% by default, because electrolytic caps are often ±20%."""
    return abs(measured - predicted) <= tol * predicted
