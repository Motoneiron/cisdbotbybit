"""SOL tf7 на ПОЧИНЕННОМ движке: матрица fill x TP x тип входа.

Вопрос: существует ли край у SOL tf7 после causal-fix, или +1195R был артефактом.

Плечи (все — A+V+D, lim10m, pos 12h, max_pos 5, детект как в research):
  C1 old_fill   все входы, фибо-тейк, MARKET=signal_ref  — как считали в июле
  C2 causal     все входы, фибо-тейк, MARKET=signal_ref  — тот же стек, новый якорь
  C3 causal     все входы, фибо-тейк, MARKET=scan_close  — честная заливка MARKET
  C4 causal     только LIMIT, фибо-тейк                  — чистая лимитная книга
  C5 causal     только LIMIT, тейк 1R                    — как торгует нынешний бот

Комиссии MEXC/Bybit считаются ОФФЛАЙН из sp/outcome/entry_kind (формула движка),
поэтому прогон один, а не два.

Пишет RUNS/temp/sol_tf7/<config>_<year>.pkl — резюмируемо.
Запуск: python sol_tf7_matrix.py [workers=6]
"""
import os
import pickle
import sys
import time

sys.path.insert(0, r"D:/PYTHON/CISDBOT")

OUT = "D:/PYTHON/cisdbotbybit/RUNS/temp/sol_tf7"
YEARS = {
    2020: ("2020-09-14", "2020-12-31"),
    2021: ("2021-01-01", "2021-12-31"),
    2022: ("2022-01-01", "2022-12-31"),
    2023: ("2023-01-01", "2023-12-31"),
    2024: ("2024-01-01", "2024-12-31"),
    2025: ("2025-01-01", "2025-12-31"),
    2026: ("2026-01-01", "2026-06-23"),
}
AVD = {"atr_enabled": True, "vol_enabled": True, "d_enabled": True}

CONFIGS = {
    "C1_oldfill_all_fib": dict(old_fill=True, tp1r=False, entry_kind_mode="all",
                               market_fill_mode="signal_ref", cancel_fib2=None),
    "C2_causal_all_fib": dict(old_fill=False, tp1r=False, entry_kind_mode="all",
                              market_fill_mode="signal_ref", cancel_fib2=None),
    "C3_causal_all_scanclose": dict(old_fill=False, tp1r=False, entry_kind_mode="all",
                                    market_fill_mode="scan_close", cancel_fib2=None),
    "C4_causal_limit_fib": dict(old_fill=False, tp1r=False, entry_kind_mode="limit_only",
                                market_fill_mode="signal_ref", cancel_fib2=False),
    "C5_causal_limit_1r": dict(old_fill=False, tp1r=True, entry_kind_mode="limit_only",
                               market_fill_mode="signal_ref", cancel_fib2=False),
}


def _patch_old_fill() -> None:
    """Старый якорь: cbt + длительность конфирм-бара, без выравнивания на 5m-скан."""
    import pandas as pd

    import backtest.bot_aligned as ba

    def old(cbt_ts, confirm_min):
        return pd.Timestamp(cbt_ts) + pd.Timedelta(minutes=int(confirm_min))

    ba._fill_from_after_confirm_close = old


def _patch_tp1r() -> None:
    """Тейк = 1R от предполагаемого входа (для LIMIT вход = уровень CISD)."""
    import backtest.bot_aligned as ba

    orig = ba._try_accept_signal

    def patched(sim, sig, tf, bar_i, *a, **kw):
        try:
            e, s = float(sig["entry"]), float(sig["stop"])
            if e > 0 and s > 0 and e != s:
                sig = {**sig, "tp": 2.0 * e - s}
        except Exception:
            pass
        return orig(sim, sig, tf, bar_i, *a, **kw)

    ba._try_accept_signal = patched


def one(task):
    cfg_name, year = task
    dst = f"{OUT}/{cfg_name}_{year}.pkl"
    if os.path.exists(dst):
        return f"skip {cfg_name} {year}"
    cfg = CONFIGS[cfg_name]
    since, until = YEARS[year]
    t0 = time.time()
    if cfg["old_fill"]:
        _patch_old_fill()
    if cfg["tp1r"]:
        _patch_tp1r()
    from backtest.bot_aligned import run_bot_aligned_backtest

    try:
        res = run_bot_aligned_backtest(
            since=since,
            until=until,
            profile="tf7",
            symbol="SOL",
            detect_filters=AVD,
            fee_model="mexc",
            max_positions=5,
            entry_kind_mode=cfg["entry_kind_mode"],
            market_fill_mode=cfg["market_fill_mode"],
            cancel_fib2=cfg["cancel_fib2"],
            save=False,
            quiet=True,
        )
    except Exception as e:
        return f"FAIL {cfg_name} {year}: {e!r}"
    rows = []
    for t in res.get("trades") or []:
        rows.append({
            "config": cfg_name, "year": year,
            "outcome": t.get("outcome"), "r_net_mexc": float(t.get("r_net")),
            "direction": t.get("direction"), "entry_kind": t.get("entry_kind"),
            "entry_px": float(t.get("entry_px") or 0), "stop": float(t.get("stop") or 0),
            "tp": float(t.get("tp") or 0), "sp": float(t.get("sp") or 0),
            "hash": str(t.get("hash")),
        })
    pickle.dump(rows, open(dst + ".tmp", "wb"))
    os.replace(dst + ".tmp", dst)
    return f"OK {cfg_name} {year}: {len(rows)} сделок sec={time.time()-t0:.0f}"


if __name__ == "__main__":
    nw = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    os.makedirs(OUT, exist_ok=True)
    tasks = [(c, y) for c in CONFIGS for y in YEARS]
    print(f"задач: {len(tasks)} | воркеров: {nw}", flush=True)
    from multiprocessing import Pool
    t0 = time.time()
    with Pool(nw) as pool:
        for i, msg in enumerate(pool.imap_unordered(one, tasks), 1):
            print(f"[{i}/{len(tasks)}] +{time.time()-t0:.0f}s {msg}", flush=True)
    print(f"DONE {time.time()-t0:.0f}s", flush=True)
