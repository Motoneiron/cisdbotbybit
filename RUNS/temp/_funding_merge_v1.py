"""Фандинг-мерж v1: к снапшоту потока добавляет фандинг на сделку + квартили.

Использование: python _funding_merge_v1.py [stream_pkl]
По умолчанию: RUNS/temp/stream_off_v1.pkl → выход stream_off_v1_funded.pkl + таблицы.
"""
import os
import pickle
import sys
from bisect import bisect_right

import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
FUND = os.path.join(BASE, "funding_bybit.pkl")


def load_funding():
    rows = pickle.load(open(FUND, "rb"))
    by = {}
    for sym, ts, rate in rows:
        by.setdefault(sym, []).append((ts, rate))
    for sym in by:
        by[sym].sort()
    return by


def rate_asof(series, ts_ms):
    if not series:
        return None
    i = bisect_right([t for t, _ in series], ts_ms) - 1
    if i < 0:
        return None
    return series[i][1]


def sum_crossings(series, t0_ms, t1_ms):
    """Сумма ставок в (t0, t1] — сколько раз позиция платила/получала фандинг."""
    if not series or t1_ms <= t0_ms:
        return 0.0, 0
    ts = [t for t, _ in series]
    lo = bisect_right(ts, t0_ms)
    hi = bisect_right(ts, t1_ms)
    seg = series[lo:hi]
    return sum(r for _, r in seg), len(seg)


def main():
    stream_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "stream_off_v1.pkl")
    df = pd.read_pickle(stream_path)
    fund = load_funding()
    print("stream rows:", len(df), "| funding pairs:", {k: len(v) for k, v in sorted(fund.items())})

    df = df.copy()
    tsv = pd.to_datetime(df["ts_fill"], errors="coerce")
    df["ts_fill_ms"] = tsv.map(lambda x: None if pd.isna(x) else int(x.timestamp() * 1000))
    # выход: плановый таймаут позиции от fill
    pos_h = {"tf7": 16, "tf8": 6}
    fund_asof, fund_next, fund_cost_r, fund_cross = [], [], [], []
    for _, row in df.iterrows():
        sym = row["sym"]
        series = fund.get(sym)
        t0 = int(row["ts_fill_ms"]) if pd.notna(row["ts_fill_ms"]) else None
        ra = rate_asof(series, t0) if t0 else None
        fund_asof.append(ra)
        t1 = t0 + int(pos_h.get(row["prof"], 12) * 3600 * 1000) if t0 else None
        if series and t0:
            ts = [t for t, _ in series]
            i = bisect_right(ts, t0)
            fund_next.append(series[i][1] if i < len(series) else None)
            s, n = sum_crossings(series, t0, t1)
            sign = -1.0 if row["dir"] == "SHORT" else 1.0  # SHORT получает плюсовой фандинг → минус издержка
            cost = (s / row["sp"]) * sign if row["sp"] else None
            fund_cost_r.append(cost)
            fund_cross.append(n)
        else:
            fund_next.append(None)
            fund_cost_r.append(None)
            fund_cross.append(None)
    df["fund_asof"] = fund_asof
    df["fund_next"] = fund_next
    df["fund_cost_r"] = fund_cost_r
    df["fund_cross"] = fund_cross

    out = stream_path.replace(".pkl", "_funded.pkl")
    df.to_pickle(out)
    print("saved:", out)

    # квартали по fund_asof, раздельно по направлению (только строки с фандингом)
    sub = df.dropna(subset=["fund_asof", "r_net"])
    for d in ("SHORT", "LONG"):
        part = sub[sub["dir"] == d].copy()
        if part.empty:
            continue
        part["qs"] = pd.qcut(part["fund_asof"].rank(method="first"), 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"])
        print(f"\n=== {d}: фандинг на входе (Q1=самый negative, Q5=самый positive) ===")
        g = part.groupby("qs", observed=True)
        tp = g["outcome"].apply(lambda s: int((s == "tp").sum()))
        dec = g["outcome"].apply(lambda s: int(s.isin(["tp", "sl"]).sum()))
        tab = pd.DataFrame({
            "n": g.size(),
            "WR%": (100 * tp / dec.clip(lower=1)).round(1),
            "SumR": g["r_net"].sum().round(1),
            "AvgR": g["r_net"].mean().round(3),
            "fund_med": g["fund_asof"].median().round(6),
        })
        print(tab.to_string())

    # издержки фандинга: суммарно и по годам
    cc = df.dropna(subset=["fund_cost_r"])
    print(f"\n=== Фандинг-издержка (в R, знак: + = платим) ===")
    print("всего по сделкам: ΣcostR =", round(cc["fund_cost_r"].sum(), 1), "| медиана/сд:", round(cc["fund_cost_r"].median(), 4))
    byy = cc.groupby("year")["fund_cost_r"].sum().round(1)
    print(byy.to_string())


if __name__ == "__main__":
    main()
