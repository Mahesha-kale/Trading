# Architecture

Mermaid diagrams. Rendered by GitHub. Text arch also in `../README.md`.

## System context

```mermaid
flowchart LR
    subgraph External
        REST[CoinDCX REST<br/>api.coindcx.com]
        WS[CoinDCX WS<br/>stream.coindcx.com]
    end
    subgraph App
        DL[app.data.downloader<br/>OHLCV fetch] --> DB[(PostgreSQL)]
        WSC[app.exchange.ws<br/>feed + reconnect] --> ENG[app.live.engine<br/>TradingEngine]
        ENG --> STR[app.strategy<br/>BaseStrategy + registry]
        ENG --> RISK[app.risk.manager<br/>sizing + kill switch]
        ENG --> EXC[app.exchange.coindcx<br/>signed orders]
        BT[app.backtest.engine] --> STR
        BT --> DB
        OPT[app.backtest.optimize<br/>grid + walk-forward] --> BT
        API[app.api.routes<br/>FastAPI] --> DB
        API --> BT
        API --> OPT
        API --> DL
        EXC --> REST
        DL --> REST
        WSC --> WS
        EXC --> REST
    end
    UI[frontend<br/>React + Vite] --> API
    REDIS[(Redis)] -.cache.-> API
```

## Signal flow (live / paper)

```mermaid
sequenceDiagram
    participant WS as CoinDCX WS
    participant ENG as TradingEngine
    participant STR as Strategy
    participant RISK as RiskManager
    participant EXC as CoinDCX REST
    participant DB as PostgreSQL
    WS->>ENG: on_candle(bar)
    ENG->>ENG: buffer bar (capped warmup+5)
    ENG->>STR: generate_signals(df)
    STR-->>ENG: signal +1/0/-1
    alt long entry & no position
        ENG->>RISK: can_open() + position_size()
        RISK-->>ENG: qty, leverage
        ENG->>DB: persist Order (client_order_id)
        alt live
            ENG->>EXC: create_order (idempotent)
            EXC-->>ENG: exchange_order_id
        else paper
            ENG->>ENG: simulated fill
        end
        ENG->>DB: persist Signal
    else signal flat & position open
        ENG->>EXC: reduce_only market exit (live) / simulated (paper)
        ENG->>RISK: record_realized(pnl)
    end
```

## Crash recovery (reconcile)

```mermaid
sequenceDiagram
    participant ENG as TradingEngine
    participant EXC as CoinDCX REST
    participant DB as PostgreSQL
    Note over ENG: startup (live mode only)
    ENG->>DB: load open Order rows
    ENG->>EXC: get_positions(symbol)
    EXC-->>ENG: real position (qty, entry, stop)
    ENG->>ENG: restore self.pos from exchange truth
    ENG->>RISK: open_positions = 1
```

## Data model

```mermaid
erDiagram
    candle ||--o{ signal : "feeds strategy"
    signal }o--|| order : "becomes"
    order ||--o| trade : "fills into"
    backtest_result }o--o| strategy_config : "tuned from"
    candle {
        int id PK
        string symbol
        string timeframe
        datetime ts
        decimal open
        decimal close
        decimal volume
    }
    signal {
        int id PK
        datetime ts
        string strategy
        string side
        decimal price
        string reason
    }
    order {
        int id PK
        string client_order_id UK
        string exchange_order_id
        string status
        decimal quantity
        decimal filled_qty
    }
    trade {
        int id PK
        string strategy
        datetime entry_ts
        datetime exit_ts
        decimal pnl
        decimal fees
        string source
    }
    backtest_result {
        int id PK
        string strategy
        decimal net_profit
        decimal sharpe
        int num_trades
    }
    strategy_config {
        int id PK
        string name UK
        string class_name
        bool enabled
    }
```

## Module dependency

```mermaid
flowchart TD
    main[app.main] --> api[app.api.routes]
    main --> eng[app.live.engine]
    main --> risk[app.risk.manager]
    eng --> str[app.strategy.registry]
    eng --> ex[app.exchange.coindcx]
    eng --> ws[app.exchange.ws]
    eng --> risk
    api --> bt[app.backtest.engine]
    api --> opt[app.backtest.optimize]
    api --> dl[app.data.downloader]
    bt --> str
    opt --> bt
    str --> ind[app.strategy.indicators]
    dl --> ex
```