"""Один прогон ядра-6 на широких порогах A/V/D с сохранением признаков.

Широкие пороги: sweep/ATR ≥ 0,32, vol/SMA ≤ 3,0, касания ≥ 4.
Это ровно ±20% от канона (0,40 / 2,5 / 5). Более узкие пороги потом
режутся по сохранённым признакам, без повторного детекта.

Оговорка: слоты и пересвип при широком фильтре чуть другие, чем при узком.
Проверка — сравнить срез «0,40 / 2,5 / 5» с уже посчитанным ABL_MSS_MAIN.

Запуск: python tf7_loose_feat.py [workers]
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

OUT = r"D:/PYTHON/cisdbotbybit/RUNS/temp/tf7_loose"
CANON = r"D:/PYTHON/cisdbotbybit/RUNS/temp/tf7_abl"
REPORT = r"D:/PYTHON/cisdbotbybit/RUNS/temp/TF7_PERTURB_2026-09-23.md"
PAIRS = ["SOL", "LINK", "ADA", "DOGE", "KAS", "LTC"]
YEARS = {
    2023: ("2023-01-01", "2023-12-31"),
    2024: ("2024-01-01", "2024-12-31"),
    2025: ("2025-01-01", "2025-12-31"),
    2026: ("2026-01-01", "2026-06-23"),
}
LOOSE = (0.32, 3.0, 4)
AVD = {"atr_enabled": True, "vol_enabled": True, "d_enabled": True}

import backtest.config as _cfg  # noqa: E402

_tf7 = dict(_cfg.BOT_TF_PROFILES["tf7"])
_tf7_main = {k: v for k, v in _tf7.items() if k != "confirm_timeframe"}
_tf7_main["fill_timeframe"] = "1m"
_tf7_main["label"] = "5m -> 4H main-mss"
_cfg.BOT_TF_PROFILES["tf7_main"] = _tf7_main

import cisdbot as bot  # noqa: E402
import backtest.touch_filter as touch_filter  # noqa: E402
from backtest.sweep_atr_filter import compute_atr14, sweep_atr_ratio  # noqa: E402
from backtest.volume_filter import volume_ratio_series  # noqa: E402


def _stamp(trade, df=None, sim=None):
    try:
        if df is not None:
            for k, ik in (("created_ts", "created_bar"), ("entry_ts", "entry_bar"), ("exit_ts", "exit_bar")):
                ib = trade.get(ik)
                if ib is not None:
                    trade[k] = str(df.index[int(ib)])
    except Exception:
        pass


def _features(sig, df_win):
    ti = int(sig.get("trigger_idx") or -1)
    level = float(sig.get("htf_sweep_level") or 0)
    is_bear = str(sig.get("direction")) == "SHORT"
    atr_ratio = None
    vol_ratio = None
    try:
        if df_win is not None and 0 <= ti < len(df_win) and level > 0:
            atr = compute_atr14(df_win)
            atr_ratio = sweep_atr_ratio(df_win, ti, level, is_bear, atr14=atr)
            ratios = volume_ratio_series(df_win, 20)
            raw = ratios.iloc[ti]
            if raw is not None and not pd.isna(raw):
                vol_ratio = float(raw)
    except Exception:
        pass
    touches = sig.get("prior_touches")
    try:
        touches = None if touches is None else int(touches)
    except (TypeError, ValueError):
        touches = None
    soft = sig.get("soft_dow")
    soft = None if soft is None else bool(soft)
    return {
        "atr_ratio": None if atr_ratio is None else float(atr_ratio),
        "vol_ratio": vol_ratio,
        "touches": touches,
        "soft_dow": soft,
    }


def one(task):
    sym, year = task
    dst = f"{OUT}/LOOSE_{sym}_{year}.pkl"
    if os.path.exists(dst):
        return f"skip {sym} {year}"
    bot.SWEEP_ATR_FILTER["min_atr"] = LOOSE[0]
    bot.TRIGGER_VOL_FILTER["max_ratio"] = LOOSE[1]
    touch_filter.TOUCH_MIN = LOOSE[2]
    stash: dict = {}

    def accept_gate(sig, bar_i=None, df=None, df_win=None, sim=None):
        h = str(sig.get("hash") or "")
        if h:
            stash[h] = _features(sig, df_win)
        return True

    def on_close(trade, df=None, sim=None):
        _stamp(trade, df=df, sim=sim)
        extra = stash.get(str(trade.get("hash") or ""))
        if extra:
            trade.update(extra)

    since, until = YEARS[year]
    t0 = time.time()
    from backtest.bot_aligned import run_bot_aligned_backtest

    try:
        res = run_bot_aligned_backtest(
            since=since, until=until, profile="tf7_main", symbol=sym,
            limit_bars=2, pos_bars=144, htf_ratio=None,
            detect_filters=AVD, fee_model="mexc", max_positions=5,
            entry_kind_mode="limit_only", market_fill_mode="signal_ref",
            cancel_fib2=False, save=False, quiet=True,
            hooks={"on_close": on_close, "accept_gate": accept_gate},
        )
    except Exception as e:
        return f"FAIL {sym} {year}: {e!r}"
    rows = []
    for t in res.get("trades") or []:
        r = {"sym": sym, "year": year}
        for k in (
            "outcome", "direction", "entry_kind", "entry_px", "stop", "tp", "sp",
            "hash", "htf_time", "entry_ts", "created_ts",
            "atr_ratio", "vol_ratio", "touches", "soft_dow",
        ):
            r[k] = t.get(k)
        r["r_net_mexc"] = float(t.get("r_net"))
        rows.append(r)
    os.makedirs(OUT, exist_ok=True)
    with open(dst + ".tmp", "wb") as f:
        pickle.dump(rows, f)
    os.replace(dst + ".tmp", dst)
    n_feat = sum(1 for x in rows if x.get("atr_ratio") is not None)
    return f"OK {sym} {year}: {len(rows)} сделок feat={n_feat} sec={time.time()-t0:.0f}"


def _fee(entry_maker, exit_maker, sp, maker, taker):
    if not sp or sp <= 0:
        return 0.0
    e = maker if entry_maker else taker
    x = maker if exit_maker else taker
    return (e + x) / sp


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


def passes(df, a_min, v_max, d_min) -> pd.Series:
    atr_ok = df["atr_ratio"].notna() & (df["atr_ratio"] >= a_min)
    soft = df["soft_dow"].fillna(False).astype(bool)
    touch_ok = df["touches"].notna() & (df["touches"] >= d_min)
    vol_ok = df["vol_ratio"].notna() & (df["vol_ratio"] <= v_max)
    # пн/ср/пт: касания, объём не смотрим. Остальные дни: объём, касания не смотрим.
    dow_ok = np.where(soft, touch_ok, vol_ok)
    return atr_ok & pd.Series(dow_ok, index=df.index)


def add_bybit(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    mexc_fee = [
        _fee(True, o == "tp", s, 0.0006, 0.0008)
        for o, s in zip(out.outcome, out.sp)
    ]
    byb_fee = [
        _fee(True, o == "tp", s, 0.00036, 0.0010)
        for o, s in zip(out.outcome, out.sp)
    ]
    out["r_mexc"] = out["r_net_mexc"]
    out["r_byb"] = out["r_net_mexc"] + np.array(mexc_fee) - np.array(byb_fee)
    return out


def load_loose() -> pd.DataFrame:
    rows = []
    for sym in PAIRS:
        for year in YEARS:
            p = f"{OUT}/LOOSE_{sym}_{year}.pkl"
            if os.path.exists(p):
                rows.extend(pickle.load(open(p, "rb")))
    return add_bybit(pd.DataFrame(rows))


def load_canon_core() -> pd.DataFrame:
    rows = []
    for sym in PAIRS:
        for year in YEARS:
            p = f"{CANON}/ABL_MSS_MAIN_{sym}_{year}.pkl"
            if os.path.exists(p):
                rows.extend(pickle.load(open(p, "rb")))
    d = pd.DataFrame(rows)
    d = d.rename(columns={"r_net_mexc": "r_net_mexc"})
    return add_bybit(d)


def cell_stats(df: pd.DataFrame) -> dict:
    y = df[df.year.astype(int) >= 2024]
    early = df[df.year.astype(int) < 2024]
    return {
        "n": len(y),
        "mexc": float(y.r_mexc.mean()) if len(y) else float("nan"),
        "byb": float(y.r_byb.mean()) if len(y) else float("nan"),
        "t": _tstat(y.r_byb) if len(y) else float("nan"),
        "n23": len(early),
        "mexc23": float(early.r_mexc.mean()) if len(early) else float("nan"),
        "byb23": float(early.r_byb.mean()) if len(early) else float("nan"),
    }


def write_report(loose: pd.DataFrame) -> None:
    canon = load_canon_core()
    lines = [
        "# Пертурбация порогов A/V/D, ядро-6 (23.09.2026)",
        "",
        "Один прогон на широких порогах (0,32 / 3,0 / 4). "
        "Остальные точки — отбор тех же сделок. "
        "Канон для сверки — готовый `ABL_MSS_MAIN` на тех же парах и годах.",
        "",
        "## Сверка среза канона",
        "",
    ]
    mask = passes(loose, 0.40, 2.5, 5)
    cut = loose[mask]
    lines.append(
        f"Широкий прогон, срез 0,40 / 2,5 / 5: n={len(cut)} (2024–26: {(cut.year.astype(int)>=2024).sum()}), "
        f"MEXC 2024–26 {_fmt(cut[cut.year.astype(int)>=2024].r_mexc.mean())}."
    )
    lines.append(
        f"Готовый канон ABL_MSS_MAIN: n={len(canon)} (2024–26: {(canon.year.astype(int)>=2024).sum()}), "
        f"MEXC 2024–26 {_fmt(canon[canon.year.astype(int)>=2024].r_mexc.mean())}."
    )
    c24 = canon[canon.year.astype(int) >= 2024]
    k24 = cut[cut.year.astype(int) >= 2024]
    if len(c24) and len(k24):
        dn = abs(len(k24) - len(c24)) / len(c24)
        lines.append(
            f"Расхождение числа сделок 2024–26: {dn*100:.1f}%. "
            "Ноль был бы при полном совпадении пути детекта. Ненулевое — слоты и пересвип на широком фильтре."
        )
    lines.append("")
    lines.append("Признаков нет (atr_ratio пустой): "
                 f"{int(loose.atr_ratio.isna().sum())} из {len(loose)}.")
    lines.append("")

    a_grid = [0.32, 0.36, 0.40, 0.44, 0.48]
    v_grid = [2.0, 2.25, 2.5, 2.75, 3.0]
    d_grid = [4, 5, 6]

    def row(a, v, d, mark=""):
        st = cell_stats(loose[passes(loose, a, v, d)])
        flag = " ← канон" if mark else ""
        return (
            f"| {a:.2f} | {v:.2f} | {d} | {st['n']} | {_fmt(st['mexc'])} | {_fmt(st['byb'])} | {_fmt(st['t'], 2)} | "
            f"{st['n23']} | {_fmt(st['mexc23'])} | {_fmt(st['byb23'])} |{flag}"
        )

    lines.append("## Ось A, V=2,50, D=5")
    lines.append("")
    lines.append("| A | V | D | n 24–26 | MEXC | Bybit | t Bybit | n до 24 | MEXC до 24 | Bybit до 24 |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for a in a_grid:
        lines.append(row(a, 2.5, 5, mark=abs(a - 0.40) < 1e-9))
    lines.append("")
    lines.append("## Ось V, A=0,40, D=5")
    lines.append("")
    lines.append("| A | V | D | n 24–26 | MEXC | Bybit | t Bybit | n до 24 | MEXC до 24 | Bybit до 24 |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for v in v_grid:
        lines.append(row(0.40, v, 5, mark=abs(v - 2.5) < 1e-9))
    lines.append("")
    lines.append("## Ось D, A=0,40, V=2,50")
    lines.append("")
    lines.append("| A | V | D | n 24–26 | MEXC | Bybit | t Bybit | n до 24 | MEXC до 24 | Bybit до 24 |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for dv in d_grid:
        lines.append(row(0.40, 2.5, dv, mark=dv == 5))
    lines.append("")

    # full factorial summary: min/max of MEXC 2024-26 inside the box
    cells = []
    for a in a_grid:
        for v in v_grid:
            for dv in d_grid:
                st = cell_stats(loose[passes(loose, a, v, dv)])
                cells.append((st["mexc"], st["byb"], a, v, dv, st["n"]))
    cells = [c for c in cells if np.isfinite(c[0])]
    if cells:
        worst = min(cells, key=lambda c: c[0])
        best = max(cells, key=lambda c: c[0])
        neg = sum(1 for c in cells if c[0] <= 0)
        lines.append("## Вся сетка 5×5×3 внутри ±20%")
        lines.append("")
        lines.append(f"Клеток: {len(cells)}. MEXC 2024–26 ≤ 0: {neg}.")
        lines.append(
            f"Худшая MEXC: {_fmt(worst[0])} при A={worst[2]:.2f}, V={worst[3]:.2f}, D={worst[4]} (n={worst[5]})."
        )
        lines.append(
            f"Лучшая MEXC: {_fmt(best[0])} при A={best[2]:.2f}, V={best[3]:.2f}, D={best[4]} (n={best[5]})."
        )
        lines.append("")
    text = "\n".join(lines) + "\n"
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(text)
    print(text, flush=True)


def main():
    nw = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    os.makedirs(OUT, exist_ok=True)
    tasks = [(s, y) for s in PAIRS for y in YEARS]
    print(f"задач: {len(tasks)} | воркеров: {nw}", flush=True)
    from multiprocessing import Pool

    t0 = time.time()
    with Pool(nw) as pool:
        for i, msg in enumerate(pool.imap_unordered(one, tasks), 1):
            print(f"[{i}/{len(tasks)}] +{time.time()-t0:.0f}s {msg}", flush=True)
    print(f"RUN DONE {time.time()-t0:.0f}s", flush=True)
    loose = load_loose()
    print(f"rows {len(loose)}", flush=True)
    write_report(loose)


if __name__ == "__main__":
    main()
