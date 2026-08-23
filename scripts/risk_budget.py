"""Carry-deploy sizing: position notional from stop-loss + risk fraction; tilt slot sizing; DD halt."""
from __future__ import annotations


def position_size(capital: float, stop_fill_est: float, risk_fraction: float, leverage_cap: int) -> float:
    """Perp notional sized so a basis-stop fill at stop_fill_est loses risk_fraction*capital.
    Capped at leverage_cap*capital (isolated margin)."""
    if stop_fill_est <= 0:
        raise ValueError("stop_fill_est must be > 0")
    wanted = capital * risk_fraction / stop_fill_est
    capped = min(wanted, leverage_cap * capital)
    return capped


def tilt_size(capital: float, conviction: float, risk_fraction: float, leverage_cap: int) -> float:
    """Naked directional tilt notional: conviction in [0,1] scales the risk_fraction budget.
    Capped at 20% of the equivalent carry position notional (tilt slot limit)."""
    c = max(0.0, min(1.0, conviction))
    base = position_size(capital, 0.02, risk_fraction, leverage_cap)  # same stop assumption
    return c * 0.20 * base


def max_dd_halt(equity: float, peak: float, max_dd: float) -> bool:
    """True when drawdown from peak exceeds max_dd (e.g. 0.25)."""
    if peak <= 0:
        return False
    return (peak - equity) / peak >= max_dd


def demo() -> None:
    # 100k capital, basis-stop fills at 2%, risk 5% of capital per position
    sz = position_size(100_000.0, 0.02, 0.05, leverage_cap=5)
    # notional = capital * risk_fraction / stop_fill_est = 100k * 0.05/0.02 = 250k
    # but capped by leverage_cap * capital = 500k -> 250k ok
    assert abs(sz - 250_000.0) < 1e-6, sz
    # leverage cap binds: risk 20%, stop 2% -> 1000k notional wanted, capped at 5*100k=500k
    sz2 = position_size(100_000.0, 0.02, 0.20, leverage_cap=5)
    assert abs(sz2 - 500_000.0) < 1e-6, sz2
    # tilt: smaller, conviction-scaled, capped at 20% of perp notional budget
    t = tilt_size(100_000.0, conviction=0.5, risk_fraction=0.05, leverage_cap=5)
    assert 0 < t <= 0.20 * position_size(100_000.0, 0.02, 0.05, 5), t
    # DD halt: equity 78k, peak 100k, max_dd 0.25 -> dd=0.22 ok; 77k -> 0.23 ok; 75k -> 0.25 halt
    assert max_dd_halt(78_000.0, 100_000.0, 0.25) is False
    assert max_dd_halt(75_000.0, 100_000.0, 0.25) is True
    print("risk_budget OK")


if __name__ == "__main__":
    demo()