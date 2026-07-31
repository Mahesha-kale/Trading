"""HTML backtest report. Self-contained, no external deps. Embedded equity SVG sparkline."""
from __future__ import annotations

import html
import os
from pathlib import Path

import pandas as pd


def render_report(metrics: dict, equity: pd.Series, trades: list[dict],
                  strategy: str, params: dict, out_path: str) -> str:
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    rows = "".join(
        f"<tr><td>{t['exit_ts']}</td><td>{t['entry_price']:.2f}</td><td>{t['exit_price']:.2f}"
        f"<td>{t['quantity']:.6f}</td><td>{t['pnl']:.2f}</td><td>{t['exit_reason']}</td></tr>"
        for t in trades[-200:]
    )
    svg = _sparkline(equity)
    m = metrics
    body = f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<title>Backtest {html.escape(strategy)}</title>
<style>
body{{font-family:system-ui,sans-serif;background:#0d1117;color:#c9d1d9;margin:2rem;max-width:1100px}}
h1,h2{{color:#58a6ff}} table{{border-collapse:collapse;width:100%;margin-top:1rem}}
td,th{{border:1px solid #30363d;padding:6px 10px;text-align:right}}
th{{background:#161b22}} .pos{{color:#3fb950}} .neg{{color:#f85149}}
.kpi{{display:flex;flex-wrap:wrap;gap:1rem}} .card{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:1rem 1.5rem}}
.card .v{{font-size:1.6rem;font-weight:600}} .card .l{{color:#8b949e;font-size:.8rem}}
</style></head><body>
<h1>Backtest Report — {html.escape(strategy)}</h1>
<p>Params: <code>{html.escape(str(params))}</code></p>
<div class=kpi>
{_card("Net Profit", f"{m.get('net_profit',0):.2f}", m.get('net_profit',0)>=0)}
{_card("Win Rate", f"{m.get('win_rate',0)*100:.1f}%")}
{_card("Profit Factor", f"{m.get('profit_factor',0):.2f}")}
{_card("Max Drawdown", f"{m.get('max_drawdown',0)*100:.1f}%")}
{_card("Sharpe", f"{m.get('sharpe',0):.2f}")}
{_card("Sortino", f"{m.get('sortino',0):.2f}")}
{_card("Expectancy", f"{m.get('expectancy',0):.2f}")}
{_card("Trades", f"{m.get('num_trades',0)}")}
</div>
<h2>Equity Curve</h2>{svg}
<h2>Trade Log (last 200)</h2>
<table><tr><th>Exit Time</th><th>Entry</th><th>Exit</th><th>Qty</th><th>PnL</th><th>Reason</th></tr>
{rows}</table>
</body></html>"""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(body)
    return os.path.abspath(out_path)


def _card(label: str, value: str, positive: bool | None = None) -> str:
    cls = "pos" if positive else ("neg" if positive is False else "")
    return f'<div class=card><div class="v {cls}">{value}</div><div class=l>{label}</div></div>'


def _sparkline(equity: pd.Series, w: int = 1000, h: int = 220) -> str:
    if equity.empty:
        return "<p>no data</p>"
    vals = equity.values
    lo, hi = float(min(vals)), float(max(vals))
    rng = (hi - lo) or 1.0
    pts = " ".join(f"{i/(len(vals)-1)*w:.1f},{h-(v-lo)/rng*h:.1f}" for i, v in enumerate(vals))
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<polyline fill="none" stroke="#58a6ff" stroke-width="2" points="{pts}"/></svg>')