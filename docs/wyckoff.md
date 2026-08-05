# Wyckoff Method — research summary & implementation

## The method (Richard Wyckoff, ~1930s)

Wyckoff reads **supply vs demand** from three things: price structure, price
spreads (range of bars), and volume. It is not an indicator system — it is a
schematic for where smart money accumulates/distributes before a big move.

### Accumulation schematic (the long side we trade)

Phases, in order, after a downtrend:

- **PS** — Preliminary Support: selling slows, volume picks up.
- **SC** — Selling Climax: wide-down bar, panic volume, capitulation.
- **AR** — Automatic Rally: natural rebound; its **high defines the "creek"**
  (resistance line at the top of the range).
- **ST** — Secondary Test: retests the SC low on *lower* volume.
- **Phase C — Spring:** a brief dip *below* the range low that snaps back.
  This is the low-risk entry probe — it shakes out the last weak holders and
  confirms supply is exhausted. (Inverse: **Upthrust / UTAD** for distribution.)
- **Phase D — SOS (Sign of Strength):** a close *above the creek* on
  *expanded* volume. Demand has taken control; the markup begins.
- **Phase E — Markup:** trending up; pullbacks to the creek (LPS, Last Point
  of Support) are continuation buys.

### Wyckoff's three laws used here

1. **Supply & Demand** — a spring below support that *recovers* = demand
   absorbed the supply (price fell but closed back up = buyers won).
2. **Cause & Effect** — the accumulation range (cause) projects into a
   markup (effect). Range height ~ markup potential.
3. **Effort vs Result** — volume is the effort, spread is the result. Light
   volume on a down-bar that doesn't make a new low = no result = supply gone
   (spring). Heavy volume on a bar that breaks the creek = result confirms
   effort (SOS).

## Quantitative encoding (`app/strategy/wyckoff.py`)

Long-only, 15m BTC/USDT perp. The whole schematic is a stateful scan:

| Wyckoff event | Quant rule |
|---|---|
| Range / creek | `rh = rolling max(high, N)` (excl. current bar, no look-ahead); `rl = rolling min(low, N)` |
| Accumulation context | slow EMA (50) flat or falling over `trend_slope` bars (came from above, not an uptrend breakout) |
| **Spring** | `low < rl*(1-spring_pen)` AND `close > rl` (recover above support) AND close in upper `rejection_frac` of the bar (a rejection wick) |
| **SOS (entry)** | within `sos_window` bars of a spring, `close > rh` (creek break) on volume > `vol_expand` * avg |
| **Exit** | rising trailing stop `max(prev, high_water - atr_mult*ATR)`; close below it → flat |
| Optional TP | `entry + tp_multiple * range` (default off — let winners run on the trail) |

**Volume** gates the SOS (demand confirmation) but NOT the spring — on 15m the
spring-bar volume is noisy vs a 50-bar mean and the rejection-wick is the
cleaner signal (validated on the data: volume-contraction filtered ~all real
springs out). `use_volume=False` drops the SOS volume gate too.

### Signal contract

Emits **+1 every bar while long** (held), **0 to exit**. The live/paper engine
holds on `1` and closes on `0` — so persistent `+1` is required for the engine
to hold the position. The backtest engine opens on the first `+1` and exits
via its own ATR trailing stop (which mirrors `atr_mult`); the strategy's own
trail is the paper exit. Both are ATR-trailing, close but not identical (backtest
uses entry-time ATR; paper uses current ATR).

## Findings / honest notes

- Selective: ~14 entries/year on BTC 15m. A spring+creek-break is a rare,
  high-conviction setup, not a frequent signal. Paper may wait weeks for a
  trade — expected for Wyckoff, not a bug.
- The creek-break entry is a *confirmation* entry (after the move has begun),
  so it can enter extended. The classic Wyckoff *low-risk* entry is the Spring
  itself or the LPS pullback; both need a confirmed range and are harder to
  encode deterministically — left as the trailing stop's job here.
- Backtest result and chosen params are written to `reports/wyckoff.html`.

## Tunable params (defaults)

`range_period=60, trend_ema=50, spring_pen=0.003, rejection_frac=0.5,
vol_expand=1.3, sos_window=60, atr_period=14, atr_mult=3.0, trend_slope=10,
tp_multiple=None, use_volume=True`