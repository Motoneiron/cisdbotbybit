"""Рычаги 1h→4H без фильтров в детекте.

Один прогон: лимитка 8 ч, удержание 24 ч, тейк в симуляции 1.5R.
На сделке пишутся sweep/ATR, vol/SMA, касания, минута филла
и минуты первого касания стопа, +1R и +1.5R.
Дальше пороги, тейки и таймауты режутся по этим полям.

Запуск: python h1_4h_levers.py [workers]
Отчёт:  python h1_4h_levers.py report
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

OUT = r"D:/PYTHON/cisdbotbybit/RUNS/temp/h1_4h_levers"
REPORT = r"D:/PYTHON/cisdbotbybit/RUNS/temp/H1_4H_LEVERS_2026-09-25.md"
PAIRS = ["SOL", "DOGE", "KAS", "ADA", "LINK", "LTC"]
YEARS = {
    2023: ("2023-01-01", "2023-12-31"),
    2024: ("2024-01-01", "2024-12-31"),
    2025: ("2025-01-01", "2025-12-31"),
    2026: ("2026-01-01", "2026-06-23"),
}
FILT_OFF = {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}
PROFILE = "h1c"
MAKER = 0.00036
TAKER = 0.0010
ENTRY_H = (1, 2, 4, 8)
EXIT_H = (6, 12, 24)
A_GRID = (0.15, 0.25, 0.40, 0.60, 0.80, 1.00)
V_GRID = (1.0, 1.5, 2.0, 2.5, 3.5, 5.0)
D_GRID = (1, 3, 5, 8, 12)

import backtest.config as _cfg  # noqa: E402
import cisdbot as bot  # noqa: E402

_cfg.BOT_TF_PROFILES[PROFILE] = {
    "timeframe": "1h",
    "fill_timeframe": "1m",
    "htf_ratio": 240,
    "limit_h": 8,
    "position_h": 24,
    "label": "1h close -> 4H levers",
}
bot.CONFIG[PROFILE] = {
    "timeframe": "1h",
    "htf_ratio": 240,
    "limit_h": 8,
    "position_h": 24,
    "ohlcv": 500,
    "label": "1h close -> 4H levers",
}

import backtest.bot_aligned as ba  # noqa: E402

_ORIG_TRY = ba._try_accept_signal
_ORIG_OPEN = ba._open_position
_ORIG_POS = ba._process_positions_on_bar


def _install():
    if getattr(ba, "_levers_installed", False):
        return

    def try_tp(sim, sig, tf, bar_i, *a, **kw):
        try:
            e, s = float(sig["entry"]), float(sig["stop"])
            if e > 0 and s > 0 and e != s:
                sig = {**sig, "tp": e + 1.5 * (e - s)}
        except Exception:
            pass
        h = str(sig.get("hash") or "")
        df_win = a[3] if len(a) > 3 else kw.get("df_win")
        if h:
            ba._FEATS[h] = _features(sig, df_win)
        return _ORIG_TRY(sim, sig, tf, bar_i, *a, **kw)

    def open_timed(sim, pl, entry_bar, entry_px):
        _ORIG_OPEN(sim, pl, entry_bar, entry_px)
        pos = sim.positions[-1]
        touch = getattr(ba, "_CUR_TS", None)
        live = pl.fill_from_ts
        pos.entry_ts = None if touch is None else pd.Timestamp(touch)
        pos.live_from = None if live is None else pd.Timestamp(live)
        pos.t_sl = None
        pos.t_1r = None
        pos.t_15 = None
        pos.marks = {}

    def pos_timed(sim, df, bar_i, bar=None):
        b = bar if bar is not None else df.iloc[bar_i]
        ts = pd.Timestamp(getattr(b, "name", None) or df.index[bar_i])
        ba._CUR_TS = ts
        hi = float(b["high"])
        lo = float(b["low"])
        cl = float(b["close"])
        for pos in sim.positions:
            if pos.status != "open" or bar_i <= pos.entry_bar:
                continue
            if getattr(pos, "entry_ts", None) is None:
                continue
            elapsed = (ts - pos.entry_ts).total_seconds() / 60.0
            if elapsed < 0:
                continue
            e = float(pos.entry_price)
            st = float(pos.stop)
            risk = abs(e - st)
            if risk <= 0:
                continue
            if pos.direction == "LONG":
                hit_sl = lo <= st
                lvl1 = e + risk
                lvl15 = e + 1.5 * risk
                hit1 = hi >= lvl1
                hit15 = hi >= lvl15
            else:
                hit_sl = hi >= st
                lvl1 = e - risk
                lvl15 = e - 1.5 * risk
                hit1 = lo <= lvl1
                hit15 = lo <= lvl15
            if hit_sl and pos.t_sl is None:
                pos.t_sl = elapsed
            if hit1 and pos.t_1r is None and not (hit_sl and pos.t_sl == elapsed):
                pos.t_1r = elapsed
            if hit15 and pos.t_15 is None and not (hit_sl and pos.t_sl == elapsed):
                pos.t_15 = elapsed
            if pos.t_sl is None and pos.t_15 is None:
                for h in EXIT_H:
                    if elapsed >= h * 60 and h not in pos.marks:
                        pos.marks[h] = cl
        return _ORIG_POS(sim, df, bar_i, bar=bar)

    ba._FEATS = {}
    ba._try_accept_signal = try_tp
    ba._open_position = open_timed
    ba._process_positions_on_bar = pos_timed
    ba._levers_installed = True


def _features(sig, df_win):
    out = {"sw": None, "vol": None, "touches": None, "soft": None}
    if df_win is None or len(df_win) == 0:
        return out
    try:
        ti = int(sig.get("trigger_idx", -1))
        if ti < 0 or ti >= len(df_win):
            return out
        level = float(sig.get("htf_sweep_level") or 0)
        direction = str(sig.get("direction") or "")
        from backtest.sweep_atr_filter import compute_atr14, sweep_atr_ratio
        from backtest.touch_filter import atr14_ewm, is_soft_dow, prior_touches_at_trigger
        from backtest.volume_filter import volume_ratio_series

        atr = compute_atr14(df_win)
        out["sw"] = sweep_atr_ratio(
            df_win, ti, level, direction == "SHORT", atr14=atr,
        )
        ratios = volume_ratio_series(df_win, 20)
        if 0 <= ti < len(ratios) and pd.notna(ratios.iloc[ti]):
            out["vol"] = float(ratios.iloc[ti])
        out["soft"] = bool(is_soft_dow(df_win.index[ti]))
        out["touches"] = prior_touches_at_trigger(
            df_win,
            direction=direction,
            level=level,
            htf_time=sig.get("htf_time"),
            trigger_idx=ti,
            htf_minutes=240,
            atr14=atr14_ewm(df_win),
        )
    except Exception:
        pass
    return out


def _r_net(gross, sp, outcome):
    if sp is None or not np.isfinite(sp) or sp <= 0 or gross is None or not np.isfinite(gross):
        return None
    fee_x = MAKER if outcome == "tp" else TAKER
    return float(gross) - MAKER / sp - fee_x / sp


def one(task):
    sym, year = task
    dst = os.path.join(OUT, f"4H_{sym}_{year}.pkl")
    if os.path.exists(dst):
        return f"skip {sym} {year}"
    _install()
    ba._FEATS = {}
    since, until = YEARS[year]
    t0 = time.time()
    from backtest.bot_aligned import run_bot_aligned_backtest

    def on_close(trade, df=None, sim=None):
        h = str(trade.get("hash") or "")
        pos = None
        if sim is not None:
            for p in reversed(sim.positions):
                if str(p.sig_hash or "") == h:
                    pos = p
                    break
        extra = dict(ba._FEATS.get(h) or {})
        if pos is not None:
            live = getattr(pos, "live_from", None)
            touch = getattr(pos, "entry_ts", None)
            delay = None
            if live is not None and touch is not None:
                delay = (pd.Timestamp(touch) - pd.Timestamp(live)).total_seconds() / 60.0
            extra.update({
                "delay_min": delay,
                "t_sl": pos.t_sl,
                "t_1r": pos.t_1r,
                "t_15": pos.t_15,
                "marks": dict(getattr(pos, "marks", {}) or {}),
                "entry": float(pos.entry_price),
                "stop": float(pos.stop),
            })
        trade.update(extra)

    try:
        res = run_bot_aligned_backtest(
            since=since, until=until, profile=PROFILE, symbol=sym,
            limit_bars=8, pos_bars=24, htf_ratio=240,
            detect_filters=FILT_OFF, fee_model="bybit", max_positions=5,
            entry_kind_mode="limit_only", market_fill_mode="signal_ref",
            cancel_fib2=False, mss_on_ltf=False, save=False, quiet=True,
            hooks={"on_close": on_close},
        )
    except Exception as e:
        return f"FAIL {sym} {year}: {e!r}"
    rows = []
    for t in res.get("trades") or []:
        rows.append({
            "sym": sym,
            "year": year,
            "direction": t.get("direction"),
            "sp": t.get("sp"),
            "sw": t.get("sw"),
            "vol": t.get("vol"),
            "touches": t.get("touches"),
            "soft": t.get("soft"),
            "delay_min": t.get("delay_min"),
            "t_sl": t.get("t_sl"),
            "t_1r": t.get("t_1r"),
            "t_15": t.get("t_15"),
            "marks": t.get("marks") or {},
            "entry": t.get("entry"),
            "stop": t.get("stop"),
            "r_engine": float(t.get("r_net")),
            "outcome_engine": t.get("outcome"),
        })
    os.makedirs(OUT, exist_ok=True)
    payload = {"trades": rows, "n_placed": len(res.get("signals") or [])}
    with open(dst + ".tmp", "wb") as f:
        pickle.dump(payload, f)
    os.replace(dst + ".tmp", dst)
    return f"OK {sym} {year}: {len(rows)} sec={time.time() - t0:.0f}"


def _tstat(x):
    x = np.asarray(list(x), dtype=float)
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


def _fmtu(x, nd=2):
    if x is None or not np.isfinite(x):
        return "—"
    return f"{x:.{nd}f}".replace(".", ",")


def load_all() -> pd.DataFrame:
    rows = []
    for sym in PAIRS:
        for year in YEARS:
            p = os.path.join(OUT, f"4H_{sym}_{year}.pkl")
            if os.path.exists(p):
                rows.extend(pickle.load(open(p, "rb"))["trades"])
    return pd.DataFrame(rows)


def _outcome_r(row, tp_mult, exit_h):
    sp = row["sp"]
    t_sl = row["t_sl"]
    t_tp = row["t_1r"] if tp_mult == 1.0 else row["t_15"]
    H = exit_h * 60.0
    sl_in = t_sl is not None and np.isfinite(t_sl) and t_sl <= H
    tp_in = t_tp is not None and np.isfinite(t_tp) and t_tp <= H
    if sl_in and (not tp_in or t_sl <= t_tp):
        return _r_net(-1.0, sp, "sl")
    if tp_in:
        return _r_net(float(tp_mult), sp, "tp")
    marks = row["marks"] or {}
    px = marks.get(exit_h)
    if px is None or row["entry"] is None or row["stop"] is None:
        return None
    sd = abs(float(row["entry"]) - float(row["stop"]))
    if sd <= 0:
        return None
    if row["direction"] == "LONG":
        gross = (float(px) - float(row["entry"])) / sd
    else:
        gross = (float(row["entry"]) - float(px)) / sd
    return _r_net(gross, sp, "time")


def _attach(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for tp, eh in ((1.0, 6), (1.0, 12), (1.0, 24), (1.5, 6), (1.5, 12), (1.5, 24)):
        key = f"r_{tp}_{eh}"
        df[key] = [
            _outcome_r(r, tp, eh) for r in df.to_dict("records")
        ]
    return df


def _cell(g, col):
    x = g[col].dropna() if col in g.columns else g
    if len(x) == 0:
        return "0 | — | — | —"
    return f"{len(x)} | {_fmt(x.mean())} | {_fmt(x.sum(), 1)} | {_fmt(_tstat(x), 2)}"


def write_report(raw: pd.DataFrame) -> None:
    df = _attach(raw)
    base = df[df.delay_min.notna() & (df.delay_min <= 60) & (df.delay_min >= -0.05)]
    recent = base[base.year >= 2024]
    y23 = base[base.year == 2023]
    lines = [
        "# Рычаги 1h → 4H (25.09.2026)",
        "",
        "Детект без фильтров. Серия на часе, подтверждение — закрытие часовой свечи, старшее окно 4H.",
        "В прогоне лимитка живёт 8 часов, позиция до 24 часов, тейк симуляции 1,5R.",
        "Срезы ниже режут уже залитые сделки: час входа, час выхода, тейк 1R или 1,5R.",
        "Сделка, которая в этом прогоне заняла слот надолго, в коротком удержании могла бы освободить место. Это оговорка срезов.",
        "",
        "База для фильтров: вход не позже 1 часа, выход 12 часов, тейк 1R. "
        f"2024–26: {len(recent)} сделок, avg {_fmt(recent['r_1.0_12'].mean()) if len(recent) else '—'}.",
        "",
    ]

    def block(title, part):
        out = [f"## {title}", ""]
        sw = pd.to_numeric(part["sw"], errors="coerce")
        vol = pd.to_numeric(part["vol"], errors="coerce")
        out.append(
            f"sweep/ATR: медиана {_fmtu(sw.median())}, "
            f"квартили {_fmtu(sw.quantile(0.25))} / {_fmtu(sw.quantile(0.75))} "
            f"(известно {int(sw.notna().sum())} из {len(part)})."
        )
        out.append(
            f"vol/SMA20: медиана {_fmtu(vol.median())}, "
            f"квартили {_fmtu(vol.quantile(0.25))} / {_fmtu(vol.quantile(0.75))}."
        )
        soft = part[part.soft == True]  # noqa: E712
        out.append(f"Мягкие дни (пн/ср/пт): {len(soft)} из {len(part)}.")
        out.append("")
        out.append("### A, свип / ATR, оставить если не меньше порога")
        out.append("")
        out.append("| порог | 2024–26 n | avg | сумма | t | 2023 avg |")
        out.append("|---|---:|---:|---:|---:|---:|")
        for thr in A_GRID:
            g = part[sw >= thr]
            g3 = y23[pd.to_numeric(y23["sw"], errors="coerce") >= thr] if len(y23) else y23
            x = g["r_1.0_12"].dropna()
            x3 = g3["r_1.0_12"].dropna() if len(g3) else g3
            out.append(
                f"| ≥ {_fmtu(thr)} | {len(x)} | {_fmt(x.mean()) if len(x) else '—'} | "
                f"{_fmt(x.sum(), 1) if len(x) else '—'} | {_fmt(_tstat(x), 2)} | "
                f"{_fmt(x3.mean()) if len(x3) else '—'} |"
            )
        out.append("")
        out.append("### V, объём свипа / SMA20, оставить если не больше порога")
        out.append("")
        out.append("| порог | 2024–26 n | avg | сумма | t | 2023 avg |")
        out.append("|---|---:|---:|---:|---:|---:|")
        for thr in V_GRID:
            g = part[vol.notna() & (vol <= thr)]
            v23 = pd.to_numeric(y23["vol"], errors="coerce") if len(y23) else vol
            g3 = y23[v23.notna() & (v23 <= thr)] if len(y23) else y23
            x = g["r_1.0_12"].dropna()
            x3 = g3["r_1.0_12"].dropna() if len(g3) else g3
            out.append(
                f"| ≤ {_fmtu(thr)} | {len(x)} | {_fmt(x.mean()) if len(x) else '—'} | "
                f"{_fmt(x.sum(), 1) if len(x) else '—'} | {_fmt(_tstat(x), 2)} | "
                f"{_fmt(x3.mean()) if len(x3) else '—'} |"
            )
        out.append("")
        out.append("### D, касания уровня до свипа, только пн/ср/пт")
        out.append("")
        out.append("В остальные дни фильтр D сделку не трогает. Ниже — весь поток после этого правила.")
        out.append("")
        out.append("| касаний не меньше | 2024–26 n | avg | сумма | t | 2023 avg |")
        out.append("|---|---:|---:|---:|---:|---:|")
        touches = pd.to_numeric(part["touches"], errors="coerce")
        for thr in D_GRID:
            keep = (part.soft != True) | (touches >= thr)  # noqa: E712
            g = part[keep]
            if len(y23):
                t23 = pd.to_numeric(y23["touches"], errors="coerce")
                g3 = y23[(y23.soft != True) | (t23 >= thr)]  # noqa: E712
                x3 = g3["r_1.0_12"].dropna()
            else:
                x3 = []
            x = g["r_1.0_12"].dropna()
            out.append(
                f"| {thr} | {len(x)} | {_fmt(x.mean()) if len(x) else '—'} | "
                f"{_fmt(x.sum(), 1) if len(x) else '—'} | {_fmt(_tstat(x), 2)} | "
                f"{_fmt(np.mean(x3)) if len(x3) else '—'} |"
            )
        out.append("")
        return out

    lines.extend(block("Фильтры по отдельности, вход 1 ч, выход 12 ч, тейк 1R", recent))

    lines.append("## Тейк 1R и 1,5R")
    lines.append("")
    lines.append("Вход не позже 1 часа. Выход 6, 12 или 24 часа.")
    lines.append("")
    lines.append("| тейк | выход | 2024–26 n | avg | сумма | t | 2023 avg |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for tp, eh in ((1.0, 6), (1.0, 12), (1.0, 24), (1.5, 6), (1.5, 12), (1.5, 24)):
        col = f"r_{tp}_{eh}"
        x = recent[col].dropna()
        x3 = y23[col].dropna() if len(y23) else y23
        lines.append(
            f"| {str(tp).replace('.', ',')}R | {eh} ч | {len(x)} | {_fmt(x.mean()) if len(x) else '—'} | "
            f"{_fmt(x.sum(), 1) if len(x) else '—'} | {_fmt(_tstat(x), 2)} | "
            f"{_fmt(x3.mean()) if len(x3) else '—'} |"
        )
    lines.append("")

    lines.append("## Таймаут входа")
    lines.append("")
    lines.append("Выход 12 часов. Минута филла — от закрытия часовой свечи до касания лимитки.")
    lines.append("")
    lines.append("| тейк | окно входа | n | avg | сумма | t |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    dly = df["delay_min"]
    book = df[df.year >= 2024]
    for tp in (1.0, 1.5):
        col = f"r_{tp}_12"
        for h in ENTRY_H:
            g = book[dly.notna() & (dly >= -0.05) & (dly <= h * 60)]
            x = g[col].dropna()
            lines.append(
                f"| {str(tp).replace('.', ',')}R | {h} ч | {len(x)} | "
                f"{_fmt(x.mean()) if len(x) else '—'} | {_fmt(x.sum(), 1) if len(x) else '—'} | "
                f"{_fmt(_tstat(x), 2)} |"
            )
    lines.append("")

    lines.append("## Таймаут выхода")
    lines.append("")
    lines.append("Вход не позже 1 часа.")
    lines.append("")
    lines.append("| тейк | удержание | n | avg | сумма | t |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    entered = book[dly.notna() & (dly >= -0.05) & (dly <= 60)]
    for tp in (1.0, 1.5):
        for eh in EXIT_H:
            col = f"r_{tp}_{eh}"
            x = entered[col].dropna()
            lines.append(
                f"| {str(tp).replace('.', ',')}R | {eh} ч | {len(x)} | "
                f"{_fmt(x.mean()) if len(x) else '—'} | {_fmt(x.sum(), 1) if len(x) else '—'} | "
                f"{_fmt(_tstat(x), 2)} |"
            )
    lines.append("")
    text = "\n".join(lines) + "\n"
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    args = sys.argv[1:]
    if args and args[0] == "report":
        write_report(load_all())
        print(REPORT, flush=True)
    else:
        nw = int(args[0]) if args else 8
        tasks = [(s, y) for s in PAIRS for y in YEARS]
        print(f"levers 1h-4h | tasks: {len(tasks)} | workers: {nw}", flush=True)
        from multiprocessing import Pool

        t0 = time.time()
        with Pool(nw) as pool:
            for msg in pool.imap_unordered(one, tasks):
                print(msg, flush=True)
        print(f"done in {time.time() - t0:.0f}s", flush=True)
        write_report(load_all())
        print(REPORT, flush=True)
