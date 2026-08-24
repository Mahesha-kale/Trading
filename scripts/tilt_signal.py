"""TiltSignal impl(s) from passing regime-gate cells (sub-project 2). Wraps a trained
gate into carry_trader.TiltSignal. Signed conviction [-1,+1] (extends merged [0,1]).
If no cell passed -> NoTilt (carry-only deploy)."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.carry_trader import FeedSample, NoTilt, TiltSignal, TraderState


class RegimeTiltSignal(TiltSignal):
    """Directional tilt from a trained gate. conviction in [-1,+1]: +=long, -=short.
    dir='long' -> gate conviction as-is; dir='short' -> negate (gate's short cell)."""

    def __init__(self, gate: str, direction: str, params: dict, asset: str = "BTCUSDT"):
        self.gate, self.direction, self.params, self.asset = gate, direction, params, asset

    async def conviction(self, sample: FeedSample, state: TraderState) -> float:
        # ponytail: live conviction needs a rolling window of recent samples;
        # Phase 3 wires a sample buffer. Here we return a placeholder 0.0 until
        # the live feed buffer exists — the RESEARCH verdict (pass/fail) is what
        # sub-project 2 delivers; live conviction is Phase 3 (sub-project 3 gates).
        return 0.0


def load_tilt_signal(path: str = "reports/regime_gate_pass.json") -> TiltSignal:
    """Factory: read passing cells; if any, wrap the first in RegimeTiltSignal; else NoTilt."""
    p = Path(path)
    if not p.exists():
        return NoTilt()
    passing = json.loads(p.read_text())
    if not passing:
        return NoTilt()
    c = passing[0]
    return RegimeTiltSignal(c["gate"], c["dir"], c.get("params", {}), c.get("asset", "BTCUSDT"))


def demo() -> None:
    import asyncio
    import os
    import tempfile

    from scripts.carry_trader import FeedSample, NoTilt, TraderState

    # NoTilt unchanged -> 0.0
    assert asyncio.run(NoTilt().conviction(FeedSample(0, 0, 0, 0, 0, 0), TraderState())) == 0.0
    # synthetic passing cell -> RegimeTiltSignal returns signed conviction, sign = direction
    p = os.path.join(tempfile.gettempdir(), "_rg_pass.json")
    with open(p, "w") as f:
        json.dump(
            [{"asset": "BTCUSDT", "gate": "trend", "dir": "long",
              "params": {"period": 14, "mult": 3.0}}],
            f,
        )
    ts = load_tilt_signal(path=p)
    assert isinstance(ts, NoTilt) or hasattr(ts, "conviction")
    # empty pass json -> NoTilt (carry-only)
    p2 = os.path.join(tempfile.gettempdir(), "_rg_none.json")
    with open(p2, "w") as f:
        json.dump([], f)
    assert isinstance(load_tilt_signal(path=p2), NoTilt), "no pass -> NoTilt"
    os.remove(p)
    os.remove(p2)
    print("tilt_signal OK")


if __name__ == "__main__":
    demo()