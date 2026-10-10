"""tf7 (5m→4H, ресемпл, MSS 1m) на ОСТАЛЬНЫХ парах: LIMIT-книга, TP 1R (и фибо).

Контекст: SOL tf7 на честном якоре даёт LIMIT-книгу ≈ +0.16 R (Bybit, 2024-26,
t≈2.9-4.3, см. SOL_TF7_RESURRECT_2026-09-21.md). Вопрос: механизм общий или
SOL-специфика. Стек единый для всех пар: A+V+D detect, окно лимитки 10 мин
(limit_bars=2), позиция 12ч (pos_bars=144) — как research-stack SOL tf7.

⚠️ Патчи (tp1r) применяются к модулю навсегда; в sol_tf7_matrix.py old_fill
протекал на весь воркер. Здесь перед КАЖДОЙ задачей патчи сбрасываются к
оригиналам — чисто по конфигу.

Конфиги:
  C5_limit_1r : LIMIT-only, TP=1R     (модель выхода нынешнего бота)
  C4_limit_fib: LIMIT-only, фибо-тейк (полнота)
Очередь: сначала все C5, затем C4.
Запуск: python tf7_pairs_matrix.py [workers=6]
"""
import os
import pickle
import sys
import time

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

OUT = "D:/PYTHON/cisdbotbybit/RUNS/temp/tf7_pairs"
PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP"]
YEARS = {
    2020: ("2020-09-14", "2020-12-31"),
    2021: ("2021-01-01", "2021-12-31"),
    2022: ("2022-01-01", "2022-12-31"),
    2023: ("2023-01-01", "2023-12-31"),
    2024: ("2024-01-01", "2024-12-31"),
    2025: ("2025-01-01", "2025-12-31"),
    2026: ("2026-01-01", "2026-06-23"),
}
KAS_SKIP = {2020, 2021, 2022}
AVD = {"atr_enabled": True, "vol_enabled": True, "d_enabled": True}
CONFIGS = ("C5_limit_1r", "C4_limit_fib")

import backtest.bot_aligned as ba  # noqa: E402

_ORIG_FILL = ba._fill_from_after_confirm_close
_ORIG_TRY = ba._try_accept_signal


def _reset_patches():
    ba._fill_from_after_confirm_close = _ORIG_FILL
    ba._try_accept_signal = _ORIG_TRY


def _patch_tp1r():
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
    cfg_name, sym, year = task
    dst = f"{OUT}/{cfg_name}_{sym}_{year}.pkl"
    if os.path.exists(dst):
        return f"skip {cfg_name} {sym} {year}"
    _reset_patches()
    if cfg_name == "C5_limit_1r":
        _patch_tp1r()
    since, until = YEARS[year]
    t0 = time.time()
    from backtest.bot_aligned import run_bot_aligned_backtest
    try:
        res = run_bot_aligned_backtest(
            since=since, until=until,
            profile="tf7", symbol=sym,
            limit_bars=2, pos_bars=144,
            detect_filters=AVD, fee_model="mexc", max_positions=5,
            entry_kind_mode="limit_only", market_fill_mode="signal_ref",
            cancel_fib2=False, save=False, quiet=True,
        )
    except Exception as e:
        return f"FAIL {cfg_name} {sym} {year}: {e!r}"
    rows = []
    for t in res.get("trades") or []:
        rows.append({
            "config": cfg_name, "sym": sym, "year": year,
            "outcome": t.get("outcome"), "r_net_mexc": float(t.get("r_net")),
            "direction": t.get("direction"), "entry_kind": t.get("entry_kind"),
            "entry_px": float(t.get("entry_px") or 0), "stop": float(t.get("stop") or 0),
            "tp": float(t.get("tp") or 0), "sp": float(t.get("sp") or 0),
            "hash": str(t.get("hash")),
        })
    with open(dst + ".tmp", "wb") as f:
        pickle.dump(rows, f)
    os.replace(dst + ".tmp", dst)
    return f"OK {cfg_name} {sym} {year}: {len(rows)} сделок sec={time.time()-t0:.0f}"


if __name__ == "__main__":
    nw = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    os.makedirs(OUT, exist_ok=True)
    tasks = []
    for c in CONFIGS:
        for s in PAIRS:
            for y in YEARS:
                if s == "KAS" and y in KAS_SKIP:
                    continue
                tasks.append((c, s, y))
    print(f"задач: {len(tasks)} | воркеров: {nw}", flush=True)
    from multiprocessing import Pool
    t0 = time.time()
    with Pool(nw) as pool:
        for i, msg in enumerate(pool.imap_unordered(one, tasks), 1):
            print(f"[{i}/{len(tasks)}] +{time.time()-t0:.0f}s {msg}", flush=True)
    print(f"DONE {time.time()-t0:.0f}s", flush=True)
