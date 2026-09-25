"""Часовое подтверждение, старшее окно 1H–4H. Только Bybit.

Сборка как у tf7-канона бота: фильтры A+V+D, лимит на CISD, тейк 1R,
честный филл после закрытия свечи подтверждения, комиссия Bybit.
Отличие: серия на 1h, сигнал только после закрытия этой часовой свечи.
Старшее окно перебирается: 1H, 2H, 3H, 4H.

Лимитка живёт 1 час (короче одной часовой свечи окно бота в 10 минут
не выразить). Удержание 12 часов. Филл лимитки, стопа и тейка — по 1m.

Запуск: python h1_confirm_htf.py [workers]
Один пробный: python h1_confirm_htf.py smoke
Отчёт без прогона: python h1_confirm_htf.py report
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

OUT = r"D:/PYTHON/cisdbotbybit/RUNS/temp/h1_confirm_htf"
REPORT = r"D:/PYTHON/cisdbotbybit/RUNS/temp/H1_CONFIRM_HTF_2026-09-25.md"
OUT_OFF = r"D:/PYTHON/cisdbotbybit/RUNS/temp/h1_4h_nofilter"
REPORT_OFF = r"D:/PYTHON/cisdbotbybit/RUNS/temp/H1_4H_NOFILTER_2026-09-25.md"
PAIRS = ["SOL", "DOGE", "KAS", "ADA", "LINK", "LTC"]
YEARS = {
    2023: ("2023-01-01", "2023-12-31"),
    2024: ("2024-01-01", "2024-12-31"),
    2025: ("2025-01-01", "2025-12-31"),
    2026: ("2026-01-01", "2026-06-23"),
}
KAS_SKIP = set()
HTF = {"1H": 60, "2H": 120, "3H": 180, "4H": 240}
AVD = {"atr_enabled": True, "vol_enabled": True, "d_enabled": True}
FILT_OFF = {"atr_enabled": False, "vol_enabled": False, "d_enabled": False}
PROFILE = "h1c"

import backtest.config as _cfg  # noqa: E402
import cisdbot as bot  # noqa: E402

_cfg.BOT_TF_PROFILES[PROFILE] = {
    "timeframe": "1h",
    "fill_timeframe": "1m",
    "htf_ratio": 240,
    "limit_h": 1,
    "position_h": 12,
    "label": "1h close -> HTF",
}
bot.CONFIG[PROFILE] = {
    "timeframe": "1h",
    "htf_ratio": 240,
    "limit_h": 1,
    "position_h": 12,
    "ohlcv": 500,
    "label": "1h close -> HTF",
}

import backtest.bot_aligned as ba  # noqa: E402

_ORIG_TRY = ba._try_accept_signal


def _patch_tp1r():
    def patched(sim, sig, tf, bar_i, *a, **kw):
        try:
            e, s = float(sig["entry"]), float(sig["stop"])
            if e > 0 and s > 0 and e != s:
                sig = {**sig, "tp": 2.0 * e - s}
        except Exception:
            pass
        return _ORIG_TRY(sim, sig, tf, bar_i, *a, **kw)

    ba._try_accept_signal = patched


def one(task):
    htf_name, sym, year = task
    dst = os.path.join(OUT, f"{htf_name}_{sym}_{year}.pkl")
    if os.path.exists(dst):
        return f"skip {htf_name} {sym} {year}"
    _patch_tp1r()
    since, until = YEARS[year]
    t0 = time.time()
    from backtest.bot_aligned import run_bot_aligned_backtest

    try:
        res = run_bot_aligned_backtest(
            since=since,
            until=until,
            profile=PROFILE,
            symbol=sym,
            limit_bars=1,
            pos_bars=12,
            htf_ratio=HTF[htf_name],
            detect_filters=AVD,
            fee_model="bybit",
            max_positions=5,
            entry_kind_mode="limit_only",
            market_fill_mode="signal_ref",
            cancel_fib2=False,
            mss_on_ltf=False,
            save=False,
            quiet=True,
        )
    except Exception as e:
        return f"FAIL {htf_name} {sym} {year}: {e!r}"
    rows = []
    for t in res.get("trades") or []:
        rows.append({
            "htf": htf_name,
            "sym": sym,
            "year": year,
            "outcome": t.get("outcome"),
            "direction": t.get("direction"),
            "r": float(t.get("r_net")),
        })
    os.makedirs(OUT, exist_ok=True)
    with open(dst + ".tmp", "wb") as f:
        pickle.dump(rows, f)
    os.replace(dst + ".tmp", dst)
    return f"OK {htf_name} {sym} {year}: {len(rows)} сделок sec={time.time() - t0:.0f}"


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


def load_all() -> pd.DataFrame:
    rows = []
    for name in HTF:
        for sym in PAIRS:
            for year in YEARS:
                p = os.path.join(OUT, f"{name}_{sym}_{year}.pkl")
                if os.path.exists(p):
                    rows.extend(pickle.load(open(p, "rb")))
    return pd.DataFrame(rows)


def _line(g: pd.DataFrame) -> str:
    if len(g) == 0:
        return "0 | — | — | — | — | —"
    n = len(g)
    tp = int((g.outcome == "tp").sum())
    sl = int((g.outcome == "sl").sum())
    tm = int((g.outcome == "time").sum())
    wr = 100.0 * tp / n
    return (
        f"{n} | {_fmtu(wr, 1)}% | {_fmt(g.r.mean())} | {_fmt(g.r.sum(), 1)} | "
        f"{_fmt(_tstat(g.r), 2)} | {tp}/{sl}/{tm}"
    )


def write_report(tr: pd.DataFrame) -> None:
    lines = [
        "# Часовое подтверждение, старшее окно 1H–4H (25.09.2026)",
        "",
        "Движок тот же, что у последних сверок с ботом: `backtest/bot_aligned.py`.",
        "Фильтры A+V+D, вход только лимиткой на уровень CISD, тейк ровно 1R, "
        "комиссия Bybit (мейкер 0,036% на вход и на тейк, тейкер 0,10% на стоп и на выход по времени).",
        "",
        "Серия на часовых свечах. Сигнал появляется только после того, как часовая свеча закрылась. "
        "Минутного и пятиминутного подтверждения нет. Филл лимитки после этого закрытия считается по минутным свечам.",
        "",
        "Старшее окно — 1H, 2H, 3H или 4H: на нём ищется свип, часовая свеча только подтверждает сигнал. "
        "Лимитка живёт 1 час, позиция — 12 часов. Окно бота в 10 минут короче одной часовой свечи, "
        "поэтому здесь взят ближайший целый час.",
        "",
        "Пары — те, что сейчас в сканере бота: SOL, DOGE, KAS, ADA, LINK, LTC. "
        "Годы 2023–2026, 2026 обрезан 23 июня, как в прошлых прогонах.",
        "",
        "Для сравнения, текущий канон бота (5m→4H, подтверждение по закрытию 5m, те же фильтры и тейк 1R) "
        "на этих шести парах за 2024–26 давал около +0,127 R на сделку. Это другая сборка, не клетка этой таблицы.",
        "",
    ]
    recent = tr[tr.year >= 2024] if len(tr) else tr

    lines.append("## 2024–26, шесть пар")
    lines.append("")
    lines.append("| старшее окно | сделки | доля тейков | avg R | сумма R | t | тейк/стоп/время |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for name in HTF:
        g = recent[recent.htf == name] if len(recent) else recent
        lines.append(f"| {name} | {_line(g)} |")
    lines.append("")

    lines.append("## По годам, avg R")
    lines.append("")
    lines.append("| старшее окно | 2023 | 2024 | 2025 | 2026 (до 23.06) |")
    lines.append("|---|---:|---:|---:|---:|")
    for name in HTF:
        cells = []
        for year in YEARS:
            g = tr[(tr.htf == name) & (tr.year == year)] if len(tr) else tr
            if len(g) == 0:
                cells.append("—")
            else:
                cells.append(f"{_fmt(g.r.mean())} ({len(g)})")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("## Направление, 2024–26")
    lines.append("")
    lines.append("| старшее окно | LONG avg R | LONG n | SHORT avg R | SHORT n |")
    lines.append("|---|---:|---:|---:|---:|")
    for name in HTF:
        g = recent[recent.htf == name] if len(recent) else recent
        lo = g[g.direction == "LONG"] if len(g) else g
        sh = g[g.direction == "SHORT"] if len(g) else g
        lines.append(
            f"| {name} | {_fmt(lo.r.mean()) if len(lo) else '—'} | {len(lo)} | "
            f"{_fmt(sh.r.mean()) if len(sh) else '—'} | {len(sh)} |"
        )
    lines.append("")

    lines.append("## Пары, 2024–26, avg R")
    lines.append("")
    lines.append("| пара | 1H | 2H | 3H | 4H |")
    lines.append("|---|---:|---:|---:|---:|")
    for sym in PAIRS:
        cells = []
        for name in HTF:
            g = recent[(recent.htf == name) & (recent.sym == sym)] if len(recent) else recent
            if len(g) == 0:
                cells.append("—")
            else:
                cells.append(f"{_fmt(g.r.mean())} ({len(g)})")
        lines.append(f"| {sym} | " + " | ".join(cells) + " |")
    lines.append("")
    text = "\n".join(lines) + "\n"
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(text)


def one_off(task):
    """1h → 4H, без фильтров A+V+D. Тот же тейк 1R и часовое закрытие."""
    sym, year = task
    dst = os.path.join(OUT_OFF, f"4H_{sym}_{year}.pkl")
    if os.path.exists(dst):
        return f"skip 4H {sym} {year}"
    _patch_tp1r()
    since, until = YEARS[year]
    t0 = time.time()
    from backtest.bot_aligned import run_bot_aligned_backtest

    try:
        res = run_bot_aligned_backtest(
            since=since,
            until=until,
            profile=PROFILE,
            symbol=sym,
            limit_bars=1,
            pos_bars=12,
            htf_ratio=240,
            detect_filters=FILT_OFF,
            fee_model="bybit",
            max_positions=5,
            entry_kind_mode="limit_only",
            market_fill_mode="signal_ref",
            cancel_fib2=False,
            mss_on_ltf=False,
            save=False,
            quiet=True,
        )
    except Exception as e:
        return f"FAIL 4H {sym} {year}: {e!r}"
    rows = []
    for t in res.get("trades") or []:
        rows.append({
            "sym": sym,
            "year": year,
            "outcome": t.get("outcome"),
            "direction": t.get("direction"),
            "r": float(t.get("r_net")),
        })
    os.makedirs(OUT_OFF, exist_ok=True)
    with open(dst + ".tmp", "wb") as f:
        pickle.dump(rows, f)
    os.replace(dst + ".tmp", dst)
    return f"OK 4H {sym} {year}: {len(rows)} сделок sec={time.time() - t0:.0f}"


def write_off_report() -> None:
    rows = []
    for sym in PAIRS:
        for year in YEARS:
            p = os.path.join(OUT_OFF, f"4H_{sym}_{year}.pkl")
            if os.path.exists(p):
                rows.extend(pickle.load(open(p, "rb")))
    tr = pd.DataFrame(rows)
    recent = tr[tr.year >= 2024] if len(tr) else tr
    lines = [
        "# 1h → 4H без фильтров (25.09.2026)",
        "",
        "Та же сборка, что 5m→4H, только серия на часе: сигнал после закрытия часовой свечи, "
        "старшее окно 4H, тейк 1R, лимит на CISD, комиссия Bybit. Фильтры A+V+D выключены.",
        "",
        "Лимитка 1 час, удержание 12 часов. Пары сканера: SOL, DOGE, KAS, ADA, LINK, LTC. "
        "2026 обрезан 23 июня.",
        "",
        "С фильтрами на этом же окне за 2024–26 было −0,096 R на сделку (1 210 сделок).",
        "",
        "## 2024–26",
        "",
        "| срез | сделки | доля тейков | avg R | сумма R | t | тейк/стоп/время |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| все | {_line(recent)} |",
    ]
    if len(recent):
        for direction in ("LONG", "SHORT"):
            g = recent[recent.direction == direction]
            lines.append(f"| {direction} | {_line(g)} |")
    lines.append("")
    lines.append("## По годам")
    lines.append("")
    lines.append("| год | сделки | avg R | сумма R | t |")
    lines.append("|---|---:|---:|---:|---:|")
    for year in YEARS:
        g = tr[tr.year == year] if len(tr) else tr
        if len(g) == 0:
            lines.append(f"| {year} | 0 | — | — | — |")
        else:
            lines.append(
                f"| {year} | {len(g)} | {_fmt(g.r.mean())} | {_fmt(g.r.sum(), 1)} | {_fmt(_tstat(g.r), 2)} |"
            )
    lines.append("")
    lines.append("## Пары, 2024–26")
    lines.append("")
    lines.append("| пара | сделки | avg R | сумма R | t |")
    lines.append("|---|---:|---:|---:|---:|")
    for sym in PAIRS:
        g = recent[recent.sym == sym] if len(recent) else recent
        if len(g) == 0:
            lines.append(f"| {sym} | 0 | — | — | — |")
        else:
            lines.append(
                f"| {sym} | {len(g)} | {_fmt(g.r.mean())} | {_fmt(g.r.sum(), 1)} | {_fmt(_tstat(g.r), 2)} |"
            )
    lines.append("")
    text = "\n".join(lines) + "\n"
    with open(REPORT_OFF, "w", encoding="utf-8") as f:
        f.write(text)


def _tasks(only=None):
    tasks = []
    for name in HTF:
        for sym in PAIRS:
            for year in YEARS:
                if sym == "KAS" and year in KAS_SKIP:
                    continue
                if only and (name, sym, year) != only:
                    continue
                tasks.append((name, sym, year))
    return tasks


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    args = sys.argv[1:]
    if args and args[0] == "report":
        write_report(load_all())
        print(REPORT, flush=True)
    elif args and args[0] == "smoke":
        print(one(("4H", "SOL", 2024)), flush=True)
    elif args and args[0] == "off":
        os.makedirs(OUT_OFF, exist_ok=True)
        nw = int(args[1]) if len(args) > 1 else 8
        tasks = [(s, y) for s in PAIRS for y in YEARS]
        print(f"no filters, 1h-4h | tasks: {len(tasks)} | workers: {nw}", flush=True)
        from multiprocessing import Pool

        t0 = time.time()
        with Pool(nw) as pool:
            for msg in pool.imap_unordered(one_off, tasks):
                print(msg, flush=True)
        print(f"done in {time.time() - t0:.0f}s", flush=True)
        write_off_report()
        print(REPORT_OFF, flush=True)
    elif args and args[0] == "off-report":
        write_off_report()
        print(REPORT_OFF, flush=True)
    else:
        nw = int(args[0]) if args else 8
        tasks = _tasks()
        print(f"задач: {len(tasks)} | воркеров: {nw}", flush=True)
        from multiprocessing import Pool

        t0 = time.time()
        with Pool(nw) as pool:
            for msg in pool.imap_unordered(one, tasks):
                print(msg, flush=True)
        print(f"готово за {time.time() - t0:.0f} с", flush=True)
        write_report(load_all())
        print(REPORT, flush=True)
