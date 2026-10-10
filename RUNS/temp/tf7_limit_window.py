"""Наполнение лимитки tf7-канона. Только Bybit.

Канон (MSS 5m, A+V+D, TP=1R), но окно лимитки 60 минут.
На каждой сделке пишется, через сколько минут после активации лимитки
цена коснулась уровня. Дальше окно режется: 10, 15, 20, 30, 45, 60.
Комиссии MEXC не считаются.

Запуск: python tf7_limit_window.py [workers]
Повтор отчёта без прогона: python tf7_limit_window.py report
"""
from __future__ import annotations

import os
import pickle
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

OUT = r"D:/PYTHON/cisdbotbybit/RUNS/temp/tf7_limit_win"
REPORT = r"D:/PYTHON/cisdbotbybit/RUNS/temp/TF7_LIMIT_WINDOW_2026-09-24.md"
PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]
CORE = ["SOL", "LINK", "ADA", "KAS", "DOGE", "LTC"]
YEARS = {
    2023: ("2023-01-01", "2023-12-31"),
    2024: ("2024-01-01", "2024-12-31"),
    2025: ("2025-01-01", "2025-12-31"),
    2026: ("2026-01-01", "2026-06-23"),
}
AVD = {"atr_enabled": True, "vol_enabled": True, "d_enabled": True}
LIMIT_BARS = 12  # 60 минут на 5m

import backtest.config as _cfg  # noqa: E402

_tf7 = dict(_cfg.BOT_TF_PROFILES["tf7"])
_tf7_main = {k: v for k, v in _tf7.items() if k != "confirm_timeframe"}
_tf7_main["fill_timeframe"] = "1m"
_tf7_main["label"] = "5m -> 4H main-mss"
_cfg.BOT_TF_PROFILES["tf7_main"] = _tf7_main

import backtest.bot_aligned as ba  # noqa: E402


def _install_timing():
    if getattr(ba, "_timing_installed", False):
        return
    orig_open = ba._open_position

    def open_timed(sim, pl, entry_bar, entry_px):
        orig_open(sim, pl, entry_bar, entry_px)
        pos = sim.positions[-1]
        touch = getattr(ba, "_CUR_TS", None)
        live = pl.fill_from_ts
        pos.touch_ts = touch
        pos.live_from = live
        h = str(pl.sig_hash or "")
        delay = None
        if live is not None and touch is not None:
            delay = (pd.Timestamp(touch) - pd.Timestamp(live)).total_seconds() / 60.0
        if h:
            ba._TOUCHES[h] = {
                "live_from": None if live is None else str(pd.Timestamp(live)),
                "touch_ts": None if touch is None else str(pd.Timestamp(touch)),
                "delay_min": delay,
            }

    def ltf_timed(sim, df_main, df_ltf, *, t_after, t_through, main_tf_min, ltf_min):
        if df_ltf is None or len(df_ltf) == 0:
            return
        sl = df_ltf.loc[(df_ltf.index > t_after) & (df_ltf.index <= t_through)]
        for ts in sl.index:
            ba._CUR_TS = pd.Timestamp(ts)
            bar = sl.loc[ts]
            if isinstance(bar, pd.DataFrame):
                bar = bar.iloc[-1]
            bar_i = ba._ts_to_main_bar_i(df_main, pd.Timestamp(ts))
            ba._process_positions_on_bar(sim, df_main, bar_i, bar=bar)
            ba._process_pending_on_bar(
                sim, df_main, bar_i, bar=bar, ltf_min=ltf_min, main_tf_min=main_tf_min,
            )

    ba._TOUCHES = {}
    ba._open_position = open_timed
    ba._process_ltf_step = ltf_timed
    ba._timing_installed = True


def _stamp_close(trade, df=None, sim=None):
    try:
        if df is not None and trade.get("exit_bar") is not None:
            trade["exit_ts"] = str(df.index[int(trade["exit_bar"])])
    except Exception:
        pass


def one(task):
    sym, year = task
    dst = os.path.join(OUT, f"WIN60_{sym}_{year}.pkl")
    if os.path.exists(dst):
        return f"skip {sym} {year}"
    _install_timing()
    ba._TOUCHES = {}

    def on_close(trade, df=None, sim=None):
        _stamp_close(trade, df=df, sim=sim)
        h = str(trade.get("hash") or "")
        extra = ba._TOUCHES.get(h)
        if extra:
            trade.update(extra)

    since, until = YEARS[year]
    t0 = time.time()
    from backtest.bot_aligned import run_bot_aligned_backtest

    try:
        res = run_bot_aligned_backtest(
            since=since, until=until, profile="tf7_main", symbol=sym,
            limit_bars=LIMIT_BARS, pos_bars=144, htf_ratio=None,
            detect_filters=AVD, fee_model="bybit", max_positions=5,
            entry_kind_mode="limit_only", market_fill_mode="signal_ref",
            cancel_fib2=False, save=False, quiet=True,
            hooks={"on_close": on_close},
        )
    except Exception as e:
        return f"FAIL {sym} {year}: {e!r}"
    rows = []
    for t in res.get("trades") or []:
        rows.append({
            "sym": sym,
            "year": year,
            "outcome": t.get("outcome"),
            "direction": t.get("direction"),
            "entry_kind": t.get("entry_kind"),
            "sp": t.get("sp"),
            "htf_time": t.get("htf_time"),
            "delay_min": t.get("delay_min"),
            "r_byb": float(t.get("r_net")),
        })
    payload = {
        "trades": rows,
        "n_placed": len(res.get("signals") or []),
        "n_filled": len(rows),
    }
    os.makedirs(OUT, exist_ok=True)
    with open(dst + ".tmp", "wb") as f:
        pickle.dump(payload, f)
    os.replace(dst + ".tmp", dst)
    known = sum(1 for r in rows if r["delay_min"] is not None)
    return f"OK {sym} {year}: placed={payload['n_placed']} fill={len(rows)} delay={known} sec={time.time()-t0:.0f}"


def _tstat(x):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = int(x.size)
    if n < 3:
        return float("nan")
    s = float(x.std(ddof=1))
    if s == 0:
        return float("nan")
    return float(x.mean() / (s / np.sqrt(n)))


def _fmt(x, nd=3):
    if x is None or not np.isfinite(x):
        return "—"
    return f"{x:+.{nd}f}".replace(".", ",")


def _fmtu(x, nd=1):
    if x is None or not np.isfinite(x):
        return "—"
    return f"{x:.{nd}f}".replace(".", ",")


def load_all():
    trades = []
    placed = []
    for sym in PAIRS:
        for year in YEARS:
            p = os.path.join(OUT, f"WIN60_{sym}_{year}.pkl")
            if not os.path.exists(p):
                continue
            payload = pickle.load(open(p, "rb"))
            trades.extend(payload["trades"])
            placed.append({"sym": sym, "year": year, "n_placed": payload["n_placed"], "n_filled": payload["n_filled"]})
    return pd.DataFrame(trades), pd.DataFrame(placed)


def write_report(tr: pd.DataFrame, placed: pd.DataFrame) -> None:
    lines = [
        "# Окно лимитки tf7-канона, только Bybit (24.09.2026)",
        "",
        "Сборка канона: MSS на 5m, фильтры A+V+D, лимит на CISD, TP=1R, удержание 12 ч. "
        "Комиссия Bybit (мейкер 0,036% на вход и на тейк, тейкер 0,10% на стоп и таймаут). "
        "MEXC в этом прогоне нет.",
        "",
        "Лимитка в прогоне живёт 60 минут. Минута филла — от момента, когда лимит стал активен "
        "(close бара подтверждения), до первой 1m-свечи, которая коснулась уровня. "
        "Срез «до 10 минут» — это текущее окно бота.",
        "",
    ]
    known = tr["delay_min"].notna().sum()
    lines.append(f"Сделок с известной минутой филла: {int(known)} из {len(tr)}.")
    lines.append(f"Поставлено лимиток: {int(placed.n_placed.sum())}, залито за 60 минут: {int(placed.n_filled.sum())}.")
    lines.append("")

    def block(title, part_tr, part_pl):
        out = [f"## {title}", ""]
        placed_n = int(part_pl.n_placed.sum()) if len(part_pl) else 0
        out.append("| окно | залито | доля поставленных | avg R | сумма R | t |")
        out.append("|---|---:|---:|---:|---:|---:|")
        dly = part_tr["delay_min"]
        for cutoff, name in (
            (10, "10 мин (сейчас)"),
            (15, "15 мин"),
            (20, "20 мин"),
            (30, "30 мин"),
            (45, "45 мин"),
            (60, "60 мин"),
        ):
            g = part_tr[dly.notna() & (dly <= cutoff) & (dly >= -0.05)]
            rate = 100.0 * len(g) / placed_n if placed_n else float("nan")
            out.append(
                f"| {name} | {len(g)} | {_fmtu(rate, 1)}% | {_fmt(g.r_byb.mean()) if len(g) else '—'} | "
                f"{_fmt(g.r_byb.sum(), 1)} | {_fmt(_tstat(g.r_byb), 2)} |"
            )
        out.append("")
        out.append("Откуда приходят новые сделки, если окно длиннее 10 минут:")
        out.append("")
        out.append("| кусок | n | доля поставленных | avg R | сумма R |")
        out.append("|---|---:|---:|---:|---:|")
        edges = [(0, 1, "0–1 мин"), (1, 10, "1–10 мин"), (10, 15, "10–15"), (15, 20, "15–20"),
                 (20, 30, "20–30"), (30, 45, "30–45"), (45, 60.01, "45–60")]
        for a, b, name in edges:
            g = part_tr[dly.notna() & (dly > a) & (dly <= b)]
            if a == 0:
                g = part_tr[dly.notna() & (dly >= -0.05) & (dly <= b)]
            rate = 100.0 * len(g) / placed_n if placed_n else float("nan")
            out.append(
                f"| {name} | {len(g)} | {_fmtu(rate, 1)}% | {_fmt(g.r_byb.mean()) if len(g) else '—'} | "
                f"{_fmt(g.r_byb.sum(), 1)} |"
            )
        unfilled = placed_n - int(part_tr.shape[0])
        rate_u = 100.0 * unfilled / placed_n if placed_n else float("nan")
        out.append(f"| не залито и за 60 мин | {unfilled} | {_fmtu(rate_u, 1)}% | — | — |")
        out.append("")
        return out

    y24 = tr.year.astype(int) >= 2024
    lines += block("Все 10 пар, 2024–26", tr[y24], placed[placed.year.astype(int) >= 2024])
    lines += block("Ядро-6, 2024–26", tr[y24 & tr.sym.isin(CORE)], placed[(placed.year.astype(int) >= 2024) & placed.sym.isin(CORE)])
    lines += block("Все 10 пар, 2023", tr[tr.year.astype(int) == 2023], placed[placed.year.astype(int) == 2023])
    lines += block("Все 10 пар, H1 2026", tr[tr.year.astype(int) == 2026], placed[placed.year.astype(int) == 2026])

    lines.append("## По годам, окно 10 мин против 30 мин")
    lines.append("")
    lines.append("| срез | год | n 10м | avg 10м | сумма 10м | n 30м | avg 30м | сумма 30м |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for name, mask in (("все 10", pd.Series(True, index=tr.index)), ("ядро-6", tr.sym.isin(CORE))):
        for y in (2023, 2024, 2025, 2026):
            q = tr[mask & (tr.year.astype(int) == y)]
            dly = q.delay_min
            a = q[dly.notna() & (dly <= 10) & (dly >= -0.05)]
            b = q[dly.notna() & (dly <= 30) & (dly >= -0.05)]
            lines.append(
                f"| {name} | {y}{' H1' if y == 2026 else ''} | {len(a)} | {_fmt(a.r_byb.mean()) if len(a) else '—'} | "
                f"{_fmt(a.r_byb.sum(), 1)} | {len(b)} | {_fmt(b.r_byb.mean()) if len(b) else '—'} | {_fmt(b.r_byb.sum(), 1)} |"
            )
    lines.append("")
    text = "\n".join(lines) + "\n"
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(text)
    print("WROTE", REPORT, flush=True)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        tr, placed = load_all()
        print(f"rows {len(tr)} placed_files {len(placed)}", flush=True)
        write_report(tr, placed)
        return
    nw = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    os.makedirs(OUT, exist_ok=True)
    tasks = [(s, y) for s in PAIRS for y in YEARS]
    print(f"tasks {len(tasks)} workers {nw}", flush=True)
    from multiprocessing import Pool

    t0 = time.time()
    with Pool(nw) as pool:
        for i, msg in enumerate(pool.imap_unordered(one, tasks), 1):
            print(f"[{i}/{len(tasks)}] +{time.time()-t0:.0f}s {msg}", flush=True)
    print(f"RUN DONE {time.time()-t0:.0f}s", flush=True)
    tr, placed = load_all()
    write_report(tr, placed)


if __name__ == "__main__":
    main()
