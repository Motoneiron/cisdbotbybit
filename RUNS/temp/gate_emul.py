"""Эмуляция гейта свипа (_sweep_valid_for_setup) на канонных сделках tf7.

Условие (2) гейта: 4H-свеча окна htf_time должна закрыться "за уровнем" свипа
(SHORT: close < level; LONG: close > level), level = экстремум предыдущей свечи.
Гейт применим только если на момент создания лимитки окно уже закрыто
(created_ts >= htf_time + 4h) — иначе "мягкий режим" пропускает сетап.

Считаем R в сетке Bybit (maker 0.036% / taker 0.10%, TP->maker).
"""
import pickle

import numpy as np
import pandas as pd

T = r"D:/PYTHON/cisdbotbybit/RUNS/temp"

PATHS = {
    "SOL": r"D:/databtcusdt/SOLUSDT-1m/SOLUSDT_1m_full_hdr.csv",
    "DOGE": r"D:/databtcusdt/DOGEUSDT-1m/DOGEUSDT_1m_full_hdr.csv",
    "KAS": r"D:/databtcusdt/KASUSDT-1m/KASUSDT_1m_full_hdr.csv",
    "ADA": r"D:/databtcusdt/ADAUSDT-1m-merged.csv",
    "LINK": r"D:/databtcusdt/LINKUSDT-1m-merged.csv",
    "LTC": r"D:/databtcusdt/LTCUSDT-1m-merged.csv",
}

MEXC_M, MEXC_T = 0.0006, 0.0008
BYBIT_M, BYBIT_T = 0.00036, 0.0010


def load_1m(path: str, since: str, until: str) -> pd.DataFrame:
    t0 = pd.Timestamp(since)
    t1 = pd.Timestamp(until)
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
    if not parts:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.concat(parts)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def fee_r(kind, outcome, sp, maker, taker):
    if not sp or sp <= 0:
        return 0.0
    entry = maker if str(kind).upper() == "LIMIT" else taker
    exit_ = maker if outcome == "tp" else taker
    return (entry + exit_) / sp


rows_out = []
for sym, path in PATHS.items():
    print("== load", sym, flush=True)
    df1 = load_1m(path, "2022-12-25", "2026-06-25")
    print("   rows:", len(df1), flush=True)
    htf = df1.resample("4h", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    )
    for y in [2023, 2024, 2025, 2026]:
        f = f"{T}/tf7_abl/ABL_MSS_MAIN_{sym}_{y}.pkl"
        try:
            c = pickle.load(open(f, "rb"))
        except FileNotFoundError:
            continue
        for r in c:
            win = pd.Timestamp(str(r["htf_time"]))
            created = pd.Timestamp(str(r["created_ts"]))
            if win not in htf.index:
                continue
            pos = htf.index.get_loc(win)
            if pos == 0:
                continue
            prev = htf.iloc[pos - 1]
            level = float(prev["high"]) if r["direction"] == "SHORT" else float(prev["low"])
            close_win = float(htf.iloc[pos]["close"])
            ok2 = (close_win < level) if r["direction"] == "SHORT" else (close_win > level)
            appl = created >= win + pd.Timedelta(hours=4)
            sp = float(r["sp"]) if r.get("sp") else np.nan
            if np.isfinite(sp):
                r_byb = (r["r_net_mexc"]
                         + fee_r(r["entry_kind"], r["outcome"], sp, MEXC_M, MEXC_T)
                         - fee_r(r["entry_kind"], r["outcome"], sp, BYBIT_M, BYBIT_T))
            else:
                r_byb = np.nan
            rows_out.append({
                "sym": sym, "year": y, "htf": win, "created": created,
                "dir": r["direction"], "outcome": r["outcome"], "sp": sp,
                "r_byb": r_byb, "appl": appl, "ok2": ok2,
                "level": level, "close_win": close_win,
                "entry_px": r["entry_px"], "stop": r["stop"],
            })
    del df1, htf

d = pd.DataFrame(rows_out)
d.to_pickle(f"{T}/gate_emul_rows.pkl")
print("saved rows:", len(d), flush=True)


def stat(name, q):
    n = len(q)
    if n == 0:
        print(name, "n=0")
        return
    tp = 100 * (q.outcome == "tp").mean()
    sl = 100 * (q.outcome == "sl").mean()
    avg = q.r_byb.mean()
    sd = q.r_byb.std(ddof=1)
    t = avg / (sd / np.sqrt(n)) if n > 1 and sd > 0 else float("nan")
    print(f"{name}: n={n} | tp {tp:.0f}% sl {sl:.0f}% | avg {avg:+.4f} t={t:+.2f} | Sum {q.r_byb.sum():+.1f}")


print()
print("=== ВСЕ сделки ядра ===")
stat("  ok2=TRUE  (закрылось за уровнем)", d[d.ok2 == True])
stat("  ok2=FALSE (НЕ за уровнем)      ", d[d.ok2 == False])
print()
print("=== APPL (гейт применим: created>=закрытие окна) ===")
stat("  все APPL          ", d[d.appl])
stat("  APPL & ok2=TRUE   ", d[(d.appl) & (d.ok2 == True)])
stat("  APPL & ok2=FALSE  (ГЕЙТ РЕЖЕТ)", d[(d.appl) & (d.ok2 == False)])
print()
print("=== PRE (создано до закрытия окна) ===")
stat("  PRE & ok2=TRUE   ", d[(~d.appl) & (d.ok2 == True)])
stat("  PRE & ok2=FALSE  ", d[(~d.appl) & (d.ok2 == False)])
print()
print("=== только 2024-26 ===")
dd = d[d.year >= 2024]
stat("  ВСЕ 24-26        ", dd)
stat("  ok2=TRUE         ", dd[dd.ok2 == True])
stat("  ok2=FALSE        ", dd[dd.ok2 == False])
stat("  APPL&ok2=FALSE   (ГЕЙТ РЕЖЕТ)", dd[(dd.appl) & (dd.ok2 == False)])
