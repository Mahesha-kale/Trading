import { useEffect, useRef, useState } from "react";
import { createChart, type UTCTimestamp } from "lightweight-charts";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, fmt, type Metrics, type Signal, type StrategyInfo, type Trade } from "./api";

// ponytail: single-file SPA, inline components. Split when a tab grows past ~150 lines.

const TABS = ["Dashboard", "Positions", "Trades", "Signals", "Strategies", "Backtest", "Optimize"] as const;
type Tab = (typeof TABS)[number];

export default function App() {
  const [tab, setTab] = useState<Tab>("Dashboard");
  const [mode, setMode] = useState("…");
  const [trades, setTrades] = useState<Trade[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [positions, setPositions] = useState<any>(null);
  const [bal, setBal] = useState<{ mode: string; equity: number | null; initial_capital: number; wallets?: any } | null>(null);
  const [eng, setEng] = useState<any>(null);
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [quote, setQuote] = useState<any>(null);

  useEffect(() => {
    api.health().then((h) => setMode(h.status)).catch(() => setMode("down"));
    api.strategies().then(setStrategies).catch(() => {});
    const poll = () => {
      api.trades(100).then(setTrades).catch(() => {});
      api.signals(50).then(setSignals).catch(() => {});
      api.positions().then(setPositions).catch(() => {});
      api.balance().then(setBal).catch(() => {});
      api.engine().then(setEng).catch(() => {});
      api.quote().then(setQuote).catch(() => {});
    };
    poll();
    const id = setInterval(poll, 5000);
    return () => clearInterval(id);
  }, []);

  const applyMode = async (m: string, confirm: boolean) => {
    try {
      await api.setMode(m, confirm);
      api.balance().then(setBal).catch(() => {});
      if (m === "live") setTimeout(() => window.location.reload(), 600);
    } catch (e: any) {
      alert(`Mode switch failed: ${e.message}`);
    }
  };

  const kill = async () => {
    if (!window.confirm("Engage kill switch? Engine halts ALL new entries. Open position is NOT closed.")) return;
    try {
      const r = await api.kill(true);
      alert(`Kill switch engaged. Equity: ${r.equity}`);
    } catch (e: any) {
      alert(`Kill failed: ${e.message}`);
    }
  };

  const trade = async (body: any) => {
    const live = bal?.mode === "live";
    const verb = body.action === "close" ? "CLOSE position" : `${body.action.toUpperCase()} ${body.margin ? `margin=${body.margin}INR ` : ""}lev=${body.leverage ?? 10}`;
    if (!window.confirm(`${verb}? ${live ? "REAL money order on CoinDCX." : "paper sim."}`)) return;
    try {
      const r = await api.trade(body);
      alert(body.action === "close" ? "Position closed." : `Opened ${body.action}: qty=${r.qty} @ ${r.price} stop=${r.stop} lev=${r.leverage} fx=${r.fx} · cost ${r.cost_inr?.toFixed(1)} INR (fee ${r.fee_inr?.toFixed(1)} slip ${r.slippage_inr?.toFixed(1)})`);
      api.positions().then(setPositions).catch(() => {});
      api.balance().then(setBal).catch(() => {});
      api.trades(100).then(setTrades).catch(() => {});
      api.engine().then(setEng).catch(() => {});
    } catch (e: any) {
      alert(`Trade failed: ${e.message}`);
    }
  };

  const toggleAuto = async () => {
    const on = !(eng?.auto);
    try { await api.setAuto(on); api.engine().then(setEng).catch(() => {}); }
    catch (e: any) { alert(`Auto toggle failed: ${e.message}`); }
  };

  const pickStrategy = async (name: string) => {
    try { await api.setStrategy(name); api.engine().then(setEng).catch(() => {}); }
    catch (e: any) { alert(`Strategy switch failed: ${e.message}`); }
  };

  return (
    <div className="min-h-screen bg-[#0d1117] text-[#c9d1d9]">
      <Header mode={mode} trades={trades} bal={bal} onMode={applyMode} onKill={kill} />
      <Nav tab={tab} setTab={setTab} />
      <ControlBar eng={eng} strategies={strategies} onTrade={trade} onToggleAuto={toggleAuto} onPickStrategy={pickStrategy} mode={bal?.mode} quote={quote} />
      <main className="p-6 max-w-7xl mx-auto">
        {tab === "Dashboard" && <Dashboard trades={trades} signals={signals} />}
        {tab === "Positions" && <Positions data={positions} />}
        {tab === "Trades" && <TradesTable trades={trades} />}
        {tab === "Signals" && <SignalsList signals={signals} />}
        {tab === "Strategies" && <Strategies />}
        {tab === "Backtest" && <Backtest quote={quote} />}
        {tab === "Optimize" && <Optimize />}
      </main>
    </div>
  );
}

function Header({ mode, trades, bal, onMode, onKill }: { mode: string; trades: Trade[]; bal: any; onMode: (m: string, c: boolean) => void; onKill: () => void }) {
  const pnl = trades.reduce((s, t) => s + (t.pnl || 0), 0);
  const eq = bal?.equity ?? bal?.initial_capital ?? null;
  const wallets: any[] = Array.isArray(bal?.wallets) ? bal.wallets : [];
  return (
    <header className="flex items-center justify-between px-6 py-3 border-b border-[#30363d]">
      <h1 className="text-sm font-semibold text-[#58a6ff]">CoinDCX BTC/USDT Perp · Trader</h1>
      <div className="flex gap-4 items-center text-xs text-[#8b949e]">
        <span>API: <b className="text-[#c9d1d9]">{mode}</b></span>
        <ModeControl current={bal?.mode} onMode={onMode} />
        <span>Equity: <b className={eq == null ? "text-[#8b949e]" : (eq >= (bal?.initial_capital ?? 10000) ? "text-[#3fb950]" : "text-[#f85149]")}>{eq == null ? "—" : fmt(eq)}</b></span>
        {wallets.map((w, i) => (
          <span key={i}>{w.currency_short_name ?? w.asset ?? "?"}: <b className="text-[#c9d1d9]">{fmt(Number(w.balance ?? 0))}</b>{Number(w.locked_balance) > 0 && <span className="text-[#8b949e]"> ({fmt(Number(w.locked_balance))} locked)</span>}</span>
        ))}
        <span>Realized PnL: <b className={pnl >= 0 ? "text-[#3fb950]" : "text-[#f85149]"}>{fmt(pnl)}</b></span>
        <button onClick={onKill} className="bg-[#f85149] text-white px-3 py-1 rounded">KILL SWITCH</button>
      </div>
    </header>
  );
}

function ModeControl({ current, onMode }: { current: string | undefined; onMode: (m: string, c: boolean) => void }) {
  const [m, setM] = useState<string>(current ?? "paper");
  useEffect(() => { if (current) setM(current); }, [current]);
  const apply = () => {
    if (m === "live" && !window.confirm("LIVE MODE: real money orders will be placed on CoinDCX with your API keys. Continue?")) return;
    onMode(m, m === "live");
  };
  return (
    <span className="flex items-center gap-1">
      Mode:
      <select value={m} onChange={(e) => setM(e.target.value)}
        className={`bg-[#0d1117] border rounded px-1 py-0.5 ${m === "live" ? "border-[#f85149] text-[#f85149]" : "border-[#30363d] text-[#c9d1d9]"}`}>
        <option value="test">test</option>
        <option value="paper">paper</option>
        <option value="live">live</option>
      </select>
      <button onClick={apply} className="bg-[#238636] text-white px-2 py-0.5 rounded">Apply</button>
    </span>
  );
}

function Nav({ tab, setTab }: { tab: Tab; setTab: (t: Tab) => void }) {
  return (
    <nav className="flex gap-1 px-6 py-2 border-b border-[#30363d] flex-wrap">
      {TABS.map((t) => (
        <button key={t} onClick={() => setTab(t)}
          className={`px-3 py-1.5 rounded text-sm ${tab === t ? "bg-[#161b22] text-white" : "text-[#8b949e]"}`}>
          {t}
        </button>
      ))}
    </nav>
  );
}

function ControlBar({ eng, strategies, onTrade, onToggleAuto, onPickStrategy, mode, quote }: {
  eng: any; strategies: StrategyInfo[]; onTrade: (b: any) => void; onToggleAuto: () => void; onPickStrategy: (n: string) => void; mode?: string; quote: any;
}) {
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [lev, setLev] = useState(10);
  const [margin, setMargin] = useState("");
  const [qty, setQty] = useState("");
  const [tp, setTp] = useState("");
  const [sl, setSl] = useState("");
  const [showRisk, setShowRisk] = useState(false);
  const running = eng?.running;
  const auto = eng?.auto;
  const live = mode === "live";
  const inputCls = "w-24 bg-[#0d1117] border border-[#30363d] rounded px-2 py-1 text-sm";

  // min tradeable qty/margin at current leverage from instrument constraints.
  const fx = quote?.fx ?? 1;
  const price = quote?.price ?? 0;
  const step = quote?.quantity_increment ?? 0.001;
  const minQ = quote?.min_quantity ?? 0;
  const minN = quote?.min_notional ?? 0;
  const eq = quote?.equity ?? 0;
  const minQty = Math.max(minQ, Math.ceil((minN / (price || 1)) / step) * step);
  const minMargin = price > 0 ? (minQty * price * fx) / lev : 0;

  // autofill min margin when quote first arrives or leverage changes (only
  // if user hasn't typed a custom margin).
  useEffect(() => {
    if (price > 0 && margin === "") setMargin(minMargin.toFixed(2));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [price, fx]);
  useEffect(() => {
    if (price > 0) setMargin(minMargin.toFixed(2));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lev]);

  // resolve qty from inputs (mirror backend manual_trade logic)
  const q = qty ? Number(qty)
    : margin ? (Number(margin) * lev) / ((price || 1) * fx)
    : 0;
  const qStep = Math.floor(q / step) * step;
  const valid = qStep > 0 && qStep >= minQ && qStep * price >= minN;
  const notionalInr = qStep * price * fx;
  const marginInr = notionalInr / lev;
  const feeInr = notionalInr * (quote?.taker_fee ?? 0.0006) * 2; // entry + exit
  const slipInr = notionalInr * ((quote?.slippage_bps ?? 2) / 10000) * 2; // both sides
  const costInr = feeInr + slipInr;
  const slNum = sl ? Number(sl) : 0;
  const riskInr = slNum > 0 ? qStep * Math.abs(price - slNum) * fx + costInr : 0;
  const riskPct = eq > 0 ? (riskInr / eq) * 100 : 0;
  const liqPct = lev * (1 / lev + 0.005); // approx isolated liq distance from entry

  const submit = (action: string) => {
    const body: any = { action, leverage: lev };
    if (margin) body.margin = Number(margin);
    if (qty) body.qty = Number(qty);
    if (tp) body.take_profit = Number(tp);
    if (sl) body.stop_loss = Number(sl);
    onTrade(body);
  };
  if (!running) {
    return <div className="px-6 py-2 border-b border-[#30363d] text-xs text-[#8b949e]">Engine not running (test mode). Start server in paper/live to trade.</div>;
  }
  return (
    <div className="px-6 py-3 border-b border-[#30363d] text-sm">
      <div className="flex flex-wrap gap-4 items-center">
        <span className="flex items-center gap-2">
          <button onClick={onToggleAuto}
            className={`px-3 py-1 rounded text-white ${auto ? "bg-[#238636]" : "bg-[#6e7681]"}`}>
            {auto ? "AUTO ON" : "AUTO OFF"}
          </button>
          <span className="text-xs text-[#8b949e]">{auto ? "signal trading" : "manual only"}</span>
        </span>
        <span className="flex items-center gap-1">
          Strategy:
          <select value={eng?.strategy ?? ""} onChange={(e) => onPickStrategy(e.target.value)}
            className="bg-[#0d1117] border border-[#30363d] rounded px-2 py-1">
            {strategies.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
          </select>
        </span>
        <span className="text-[#8b949e]">|</span>
        <span className="flex items-center gap-1">
          <select value={side} onChange={(e) => setSide(e.target.value as "buy" | "sell")} className={inputCls}>
            <option value="buy">BUY/long</option>
            <option value="sell">SELL/short</option>
          </select>
          <input type="number" value={lev} onChange={(e) => setLev(+e.target.value)} min={1} max={20} title="leverage" className={`${inputCls} w-16`} />
          <input type="number" value={margin} onChange={(e) => setMargin(e.target.value)} placeholder="margin INR" className={`${inputCls} w-28`} />
          <button onClick={() => setMargin(minMargin.toFixed(2))} title="min tradeable margin at this leverage" className="px-2 py-1 rounded bg-[#161b22] border border-[#30363d] text-[#8b949e]">Min</button>
          <input type="number" value={qty} onChange={(e) => setQty(e.target.value)} placeholder="qty BTC" className={`${inputCls} w-24`} />
          <input type="number" value={tp} onChange={(e) => setTp(e.target.value)} placeholder="TP" className={inputCls} />
          <input type="number" value={sl} onChange={(e) => setSl(e.target.value)} placeholder="SL" className={inputCls} />
        </span>
        <button onClick={() => submit(side)} disabled={!valid}
          className={`px-3 py-1 rounded text-white ${side === "buy" ? "bg-[#238636]" : "bg-[#f85149]"} ${!valid ? "opacity-50" : ""}`}>
          {side.toUpperCase()}
        </button>
        <button onClick={() => submit("close")} className="px-3 py-1 rounded bg-[#30363d] text-[#c9d1d9]">CLOSE</button>
        <button onClick={() => setShowRisk((v) => !v)} className="px-3 py-1 rounded bg-[#161b22] border border-[#30363d] text-[#8b949e]">Show Risk</button>
        {eng?.has_position && <span className="text-xs text-[#d29922]">position open</span>}
        {eng?.kill && <span className="text-xs text-[#f85149]">KILL ENGAGED</span>}
        {live && <span className="text-xs text-[#f85149]">LIVE · real money</span>}
      </div>
      <div className="mt-2 text-xs text-[#8b949e] flex flex-wrap gap-x-5 gap-y-1">
        <span>BTC: <b className="text-[#c9d1d9]">{price ? price.toFixed(1) : "—"}</b></span>
        <span>FX: <b className="text-[#c9d1d9]">{fx.toFixed(2)}</b></span>
        <span>min qty: <b className="text-[#c9d1d9]">{minQty}</b> · min margin@{lev}x: <b className="text-[#c9d1d9]">{minMargin.toFixed(2)} INR</b></span>
        <span className={valid ? "text-[#3fb950]" : "text-[#f85149]"}>order qty: <b>{qStep || 0}</b> {valid ? "✓" : "(below min)"}</span>
        {showRisk && (
          <span className="text-[#c9d1d9]">
            · notional {notionalInr.toFixed(0)} INR · margin {marginInr.toFixed(0)} INR
            {` · fee≈${feeInr.toFixed(2)} · slip≈${slipInr.toFixed(2)} · round-trip cost ${costInr.toFixed(2)} INR`}
            {slNum > 0 ? ` · risk@SL ${riskInr.toFixed(2)} INR (${riskPct.toFixed(1)}% eq)` : " · no SL → risk unbounded to liq"}
            {` · liq≈${liqPct.toFixed(1)}% from entry`}
          </span>
        )}
      </div>
    </div>
  );
}

function Card({ title, children, className = "" }: { title?: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-[#161b22] border border-[#30363d] rounded-xl p-4 ${className}`}>
      {title && <h3 className="text-sm font-medium mb-2">{title}</h3>}
      {children}
    </div>
  );
}

function Dashboard({ trades, signals }: { trades: Trade[]; signals: Signal[] }) {
  const wins = trades.filter((t) => t.pnl > 0);
  const grossP = wins.reduce((s, t) => s + t.pnl, 0);
  const grossL = -trades.filter((t) => t.pnl < 0).reduce((s, t) => s + t.pnl, 0);
  const pf = grossL > 0 ? grossP / grossL : grossP > 0 ? Infinity : 0;
  const wr = trades.length ? (wins.length / trades.length) * 100 : 0;
  const cum = trades.slice().reverse().reduce<{ eq: number; pts: { t: number; v: number }[] }>(
    (a, t, i) => ({ eq: a.eq + t.pnl, pts: [...a.pts, { t: i, v: a.eq + t.pnl }] }),
    { eq: 10000, pts: [] }
  );
  return (
    <div className="grid grid-cols-4 gap-4">
      <KPI label="Realized PnL" value={fmt(cum.eq - 10000)} pos={cum.eq - 10000 >= 0} />
      <KPI label="Win Rate" value={`${wr.toFixed(1)}%`} />
      <KPI label="Profit Factor" value={isFinite(pf) ? fmt(pf) : "∞"} />
      <KPI label="Trades" value={String(trades.length)} />
      <Card title="Equity Curve" className="col-span-4">
        <EquityChart points={cum.pts.length ? cum.pts : [{ t: 0, v: 10000 }]} />
      </Card>
      <Card title="PnL per Trade" className="col-span-4">
        <PnLArea trades={trades} />
      </Card>
      <Card title="Recent Signals" className="col-span-2">
        <table className="w-full text-xs">
          <tbody>{signals.slice(0, 8).map((s, i) => (
            <tr key={i} className="border-b border-[#30363d]">
              <td className="py-1">{s.ts.slice(0, 19)}</td>
              <td className="text-[#8b949e]">{s.strategy}</td>
              <td className={s.side === "buy" ? "text-[#3fb950]" : "text-[#f85149]"}>{s.side}</td>
              <td className="text-right">{fmt(s.price)}</td>
            </tr>
          ))}</tbody>
        </table>
      </Card>
      <Card title="Recent Trades" className="col-span-2">
        <table className="w-full text-xs">
          <tbody>{trades.slice(0, 8).map((t, i) => (
            <tr key={i} className="border-b border-[#30363d]">
              <td className="py-1 text-[#8b949e]">{t.strategy}</td>
              <td className="text-right">{fmt(t.entry_price)}</td>
              <td className="text-right">{t.exit_price ? fmt(t.exit_price) : "—"}</td>
              <td className={`text-right ${t.pnl >= 0 ? "text-[#3fb950]" : "text-[#f85149]"}`}>{fmt(t.pnl)}</td>
            </tr>
          ))}</tbody>
        </table>
      </Card>
    </div>
  );
}

function KPI({ label, value, pos }: { label: string; value: string; pos?: boolean }) {
  return (
    <Card>
      <div className={`text-2xl font-semibold ${pos === true ? "text-[#3fb950]" : pos === false ? "text-[#f85149]" : ""}`}>{value}</div>
      <div className="text-xs text-[#8b949e] mt-1">{label}</div>
    </Card>
  );
}

function EquityChart({ points }: { points: { t: number; v: number }[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      height: 220, autoSize: true,
      layout: { background: { color: "#161b22" }, textColor: "#8b949e" },
      grid: { vertLines: { color: "#21262d" }, horzLines: { color: "#21262d" } },
      rightPriceScale: { borderColor: "#30363d" }, timeScale: { borderColor: "#30363d" },
    });
    const series = chart.addLineSeries({ color: "#58a6ff", lineWidth: 2 });
    series.setData(points.map((p) => ({ time: p.t as UTCTimestamp, value: p.v })));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [points]);
  return <div ref={ref} className="w-full h-[220px]" />;
}

function PnLArea({ trades }: { trades: Trade[] }) {
  const data = trades.slice().reverse().map((t, i) => ({ i, pnl: t.pnl }));
  return (
    <ResponsiveContainer width="100%" height={180}>
      <AreaChart data={data}>
        <defs><linearGradient id="pnl" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#58a6ff" stopOpacity={0.4} />
          <stop offset="100%" stopColor="#58a6ff" stopOpacity={0} />
        </linearGradient></defs>
        <XAxis dataKey="i" stroke="#8b949e" tick={{ fontSize: 11 }} />
        <YAxis stroke="#8b949e" tick={{ fontSize: 11 }} />
        <Tooltip contentStyle={{ background: "#161b22", border: "1px solid #30363d" }} />
        <Area type="monotone" dataKey="pnl" stroke="#58a6ff" fill="url(#pnl)" />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function Positions({ data }: { data: any }) {
  const pos = Array.isArray(data) ? data : (data?.positions ?? []);
  return (
    <Card title="Open Positions">
      <table className="w-full text-sm">
        <thead><tr className="text-[#8b949e] text-left">
          <th className="py-1">Symbol</th><th>Side</th><th>Size</th><th>Entry</th><th>Liq</th><th>PnL</th>
        </tr></thead>
        <tbody>
          {pos.length === 0 && <tr><td colSpan={6} className="text-[#8b949e] py-4">No open positions ({data?.mode ?? ""}).</td></tr>}
          {pos.map((p: any, i: number) => (
            <tr key={i} className="border-b border-[#30363d]">
              <td className="py-1">{p.pair ?? p.symbol ?? "—"}</td>
              <td className={Number(p.position_size) >= 0 ? "text-[#3fb950]" : "text-[#f85149]"}>{Number(p.position_size) >= 0 ? "LONG" : "SHORT"}</td>
              <td>{fmt(Math.abs(Number(p.position_size ?? p.size ?? 0)), 4)}</td>
              <td>{fmt(Number(p.avg_entry_price ?? p.entry_price ?? 0))}</td>
              <td>{p.liquidation_price ? fmt(Number(p.liquidation_price)) : "—"}</td>
              <td className={Number(p.unrealised_pnl ?? p.pnl ?? 0) >= 0 ? "text-[#3fb950]" : "text-[#f85149]"}>{fmt(Number(p.unrealised_pnl ?? p.pnl ?? 0))}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function TradesTable({ trades }: { trades: Trade[] }) {
  return (
    <Card title="Trade History">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="text-[#8b949e] text-left">
            <th className="py-1">Exit Time</th><th>Strategy</th><th>Side</th><th>Entry</th><th>Exit</th><th>Qty</th><th>PnL</th><th>Fees</th><th>Reason</th>
          </tr></thead>
          <tbody>{trades.map((t, i) => (
            <tr key={i} className="border-b border-[#30363d]">
              <td className="py-1">{t.exit_ts ? t.exit_ts.slice(0, 19) : "open"}</td>
              <td className="text-[#8b949e]">{t.strategy}</td>
              <td>{t.side}</td>
              <td>{fmt(t.entry_price)}</td>
              <td>{t.exit_price ? fmt(t.exit_price) : "—"}</td>
              <td>{fmt(t.quantity, 4)}</td>
              <td className={t.pnl >= 0 ? "text-[#3fb950]" : "text-[#f85149]"}>{fmt(t.pnl)}</td>
              <td className="text-[#8b949e]">{fmt(Number(t.fees ?? 0))}</td>
              <td className="text-[#8b949e]">{t.exit_reason}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </Card>
  );
}

function SignalsList({ signals }: { signals: Signal[] }) {
  return (
    <Card title="Signals">
      <table className="w-full text-sm">
        <thead><tr className="text-[#8b949e] text-left"><th className="py-1">Time</th><th>Strategy</th><th>Side</th><th>Price</th><th>Reason</th></tr></thead>
        <tbody>{signals.map((s, i) => (
          <tr key={i} className="border-b border-[#30363d]">
            <td className="py-1">{s.ts.slice(0, 19)}</td>
            <td className="text-[#8b949e]">{s.strategy}</td>
            <td className={s.side === "buy" ? "text-[#3fb950]" : "text-[#f85149]"}>{s.side}</td>
            <td>{fmt(s.price)}</td>
            <td className="text-[#8b949e]">{s.reason}</td>
          </tr>
        ))}</tbody>
      </table>
    </Card>
  );
}

function Strategies() {
  const [list, setList] = useState<StrategyInfo[]>([]);
  useEffect(() => { api.strategies().then(setList).catch(() => {}); }, []);
  return (
    <div className="grid grid-cols-3 gap-4">
      {list.map((s) => (
        <Card key={s.name} title={s.name}>
          <div className="text-xs text-[#8b949e]">timeframe: {s.timeframe}</div>
          <pre className="mt-2 text-xs bg-[#0d1117] p-2 rounded overflow-x-auto">{JSON.stringify(s.params, null, 2)}</pre>
        </Card>
      ))}
    </div>
  );
}

function Backtest({ quote }: { quote: any }) {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [name, setName] = useState("");
  const [days, setDays] = useState(180);
  const [leverage, setLeverage] = useState(3);
  const [result, setResult] = useState<{ metrics: Metrics; report: string; num_trades: number } | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.strategies().then(setStrategies).catch(() => {}); }, []);
  useEffect(() => { if (strategies.length && !name) setName(strategies[0].name); }, [strategies, name]);

  const run = async () => {
    setBusy(true); setErr("");
    try { setResult(await api.backtest({ strategy: name, days, leverage, timeframe: "15m" })); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <div className="grid grid-cols-3 gap-4">
      <Card title="Run Backtest" className="col-span-1">
        <label className="block text-xs text-[#8b949e] mt-2">Strategy</label>
        <select value={name} onChange={(e) => setName(e.target.value)} className="w-full bg-[#0d1117] border border-[#30363d] rounded p-2 mt-1">
          {strategies.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
        </select>
        <label className="block text-xs text-[#8b949e] mt-2">Days</label>
        <input type="number" value={days} onChange={(e) => setDays(+e.target.value)} className="w-full bg-[#0d1117] border border-[#30363d] rounded p-2 mt-1" />
        <label className="block text-xs text-[#8b949e] mt-2">Leverage</label>
        <input type="number" value={leverage} onChange={(e) => setLeverage(+e.target.value)} className="w-full bg-[#0d1117] border border-[#30363d] rounded p-2 mt-1" />
        <button onClick={run} disabled={busy} className="w-full mt-3 bg-[#238636] text-white rounded p-2 disabled:opacity-50">{busy ? "Running…" : "Run"}</button>
        {err && <div className="text-[#f85149] text-xs mt-2">{err}</div>}
      </Card>
      <Card title="Results" className="col-span-2">
        {result ? (
          <div>
            <div className="grid grid-cols-4 gap-2">
              {Object.entries(result.metrics).map(([k, v]) => (
                <div key={k} className="bg-[#0d1117] rounded p-2">
                  <div className="text-lg font-semibold">{typeof v === "number" ? fmt(v, 4) : v}</div>
                  <div className="text-xs text-[#8b949e]">{k}</div>
                </div>
              ))}
            </div>
            <div className="mt-3 text-xs text-[#8b949e]">{result.num_trades} trades · report: <code>{result.report}</code></div>
            <div className="mt-1 text-xs text-[#8b949e]">
              costs modeled: taker {((quote?.taker_fee ?? 0.0006) * 100).toFixed(3)}% · maker {((quote?.maker_fee ?? 0.00025) * 100).toFixed(3)}% · slippage {quote?.slippage_bps ?? 2}bps
            </div>
          </div>
        ) : <div className="text-[#8b949e]">No run yet.</div>}
      </Card>
    </div>
  );
}

function Optimize() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [name, setName] = useState("");
  const [gridText, setGridText] = useState('{"fast":[5,10,20],"slow":[40,50,100]}');
  const [wf, setWf] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.strategies().then(setStrategies).catch(() => {}); }, []);
  useEffect(() => { if (strategies.length && !name) setName(strategies[0].name); }, [strategies, name]);

  const run = async () => {
    setBusy(true); setErr("");
    try {
      const grid = JSON.parse(gridText);
      setResult(await api.optimize({ strategy: name, grid, walk_forward: wf, n_splits: 5, days: 180 }));
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <div className="grid grid-cols-3 gap-4">
      <Card title="Optimize" className="col-span-1">
        <label className="block text-xs text-[#8b949e]">Strategy</label>
        <select value={name} onChange={(e) => setName(e.target.value)} className="w-full bg-[#0d1117] border border-[#30363d] rounded p-2 mt-1">
          {strategies.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
        </select>
        <label className="block text-xs text-[#8b949e] mt-2">Grid (JSON)</label>
        <textarea value={gridText} onChange={(e) => setGridText(e.target.value)} rows={5}
          className="w-full bg-[#0d1117] border border-[#30363d] rounded p-2 mt-1 text-xs font-mono" />
        <label className="flex items-center gap-2 mt-2 text-sm"><input type="checkbox" checked={wf} onChange={(e) => setWf(e.target.checked)} /> Walk-forward</label>
        <button onClick={run} disabled={busy} className="w-full mt-3 bg-[#238636] text-white rounded p-2 disabled:opacity-50">{busy ? "Running…" : "Optimize"}</button>
        {err && <div className="text-[#f85149] text-xs mt-2">{err}</div>}
      </Card>
      <Card title="Results" className="col-span-2">
        {result ? (
          <pre className="text-xs bg-[#0d1117] p-2 rounded overflow-x-auto">{JSON.stringify(result, null, 2)}</pre>
        ) : <div className="text-[#8b949e]">No run yet.</div>}
      </Card>
    </div>
  );
}