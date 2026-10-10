"""test_bybit_life.py — сколько времени ЖИВОЙ (bybit) детект держит сигнал:
notseen vs paired (выборка 2024, по 3 кейса на пару).

Метод: для кейса (sym, cbt, dir) вызываем bot.detect_signals на барах
cbt+5..+90 мин и смотрим, выдаётся ли ещё сигнал с тем же (cbt, dir).

Запуск: python -u test_bybit_life.py
"""
from __future__ import annotations

import logging
import os
import sys
import time

import pandas as pd

PATHS = {
    "SOL": r"D:\databtcusdt\SOLUSDT-1m\SOLUSDT_1m_full_hdr.csv",
    "DOGE": r"D:\databtcusdt\DOGEUSDT-1m\DOGEUSDT_1m_full_hdr.csv",
    "KAS": r"D:\databtcusdt\KASUSDT-1m\KASUSDT_1m_full_hdr.csv",
    "ADA": r"D:\databtcusdt\ADAUSDT-1m-merged.csv",
    "LINK": r"D:\databtcusdt\LINKUSDT-1m-merged.csv",
    "LTC": r"D:\databtcusdt\LTCUSDT-1m-merged.csv",
}
KS = [5, 10, 15, 20, 30, 40, 55, 70, 90]
WIN = 300


def load_1m(path, since, until):
    t0 = pd.Timestamp(since) - pd.Timedelta(days=4)
    t1 = pd.Timestamp(until) + pd.Timedelta(days=1)
    parts = []
    cols = ["open_time", "open", "high", "low", "close", "volume"]
    for chunk in pd.read_csv(path, usecols=cols, chunksize=500_000):
        ot = pd.to_datetime(chunk["open_time"], unit="ms")
        m = (ot >= t0) & (ot < t1)
        if not m.any():
            if len(ot) and ot.iloc[-1] < t0:
                continue
            if len(ot) and ot.iloc[0] >= t1:
                break
            continue
        sub = chunk.loc[m, ["open", "high", "low", "close", "volume"]].astype(float)
        sub.index = ot[m]
        parts.append(sub)
    df = pd.concat(parts)
    return df[~df.index.duplicated(keep="last")].sort_index()


def main():
    sys.path.insert(0, r"D:\PYTHON\cisdbotbybit")
    logging.disable(logging.CRITICAL)
    import cisdbot as bot

    bot.CONFIG["tf7"]["detect_filters"] = {"atr_enabled": False, "vol_enabled": False, "d_enabled": True}
    bot.state.paper = True
    htf = int(bot.CONFIG["tf7"]["htf_ratio"])

    A = pd.read_csv(r"D:\PYTHON\cisdbotbybit\RUNS\temp\analyze_b_rows.csv")
    A["cbt"] = pd.to_datetime(A["cbt"])
    A["scan"] = pd.to_datetime(A["scan"])

    cases = {}
    for sym in PATHS:
        for cls, n in (("notseen", 3), ("paired", 3)):
            sub = A[(A.sym == sym) & (A.cls == cls)].head(n)
            cases.setdefault(sym, []).extend((cls, r) for _, r in sub.iterrows())

    print("K:", KS, flush=True)
    summary = {("notseen", k): [] for k in KS}
    summary.update({("paired", k): [] for k in KS})

    for sym, rows in cases.items():
        df1 = load_1m(PATHS[sym], "2024-01-01", "2025-01-01")
        df5 = bot._resample_ohlcv(df1, "5m")
        for cls, r in rows:
            cbt = r["cbt"]
            d = str(r["direction"])
            cbt_s = str(cbt)[:19]
            alive = {}
            for k in KS:
                ts = cbt + pd.Timedelta(minutes=k)
                j = int(df5.index.searchsorted(ts - pd.Timedelta(minutes=5), side="left"))
                # sl заканчивается на баре ts (включительно)
                j2 = int(df5.index.searchsorted(ts, side="right")) - 1
                if j2 < WIN:
                    alive[k] = None
                    continue
                sl = df5.iloc[j2 - (WIN - 1) : j2 + 1]
                if pd.Timestamp(sl.index[-1]) != ts:
                    # бара ровно на ts нет (дырка) — сдвигаем к последнему <= ts
                    pass
                seen: set = set()
                sigs = bot.detect_signals(sl, seen, htf_ratio=htf, tf_name="tf7", df_confirm=None, min_sweep_atr=0.0) or []
                ok = any(str(s.get("direction")) == d and str(s.get("confirm_bar_time") or "")[:19] == cbt_s for s in sigs)
                alive[k] = 1 if ok else 0
                summary[(cls, k)].append(alive[k])
            line = " ".join(f"+{k}:{'-' if alive[k] is None else alive[k]}" for k in KS)
            print(f"[{cls:7}] {sym:4} {str(cbt)[5:16]} {d:5} r={float(r['r']):+.2f} | {line}", flush=True)

    print("\n===== ИТОГ: доля 'ещё жив' по классам =====", flush=True)
    for cls in ("notseen", "paired"):
        tot = []
        for k in KS:
            vals = [v for v in summary[(cls, k)] if v is not None]
            frac = sum(vals) / len(vals) if vals else float("nan")
            tot.append(f"+{k}:{frac:.2f}")
        print(f"{cls:8}: " + "  ".join(tot), flush=True)


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"DONE {time.time()-t0:.0f}s", flush=True)
