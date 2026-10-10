"""Старая книга SOL tf7: LIMIT vs MARKET, MEXC→Bybit, TP fib vs 1R, половины лет."""
from __future__ import annotations

import glob
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON/CISDBOT")
from backtest.data import load_ltf  # noqa: E402

CACHE = "D:/PYTHON/CISDBOT/RUNS/cache"
MEXC_M, MEXC_T = 0.0006, 0.0008
BYBIT_M, BYBIT_T = 0.00036, 0.0010
EARLY, LATE = {2020, 2021, 2022, 2023}, {2024, 2025, 2026}


def fee_r(kind: str, outcome: str, sp: float, maker: float, taker: float) -> float:
    if sp <= 0:
        return 0.0
    entry = maker if kind == "LIMIT" else taker
    exit_ = maker if outcome == "tp" else taker
    return (entry + exit_) / sp


def load_old() -> pd.DataFrame:
    rows = []
    for f in sorted(glob.glob(f"{CACHE}/SOL_tf7_*_1m_lim10m.pkl")):
        c = pickle.load(open(f, "rb"))
        sigs = {str(s.get("hash")): s for s in c.get("signals") or []}
        for t in c.get("trades") or []:
            s = sigs.get(str(t.get("hash")), {})
            entry = float(t["entry_px"]); stop = float(t["stop"]); tp = float(t["tp"])
            sp = float(t.get("sp") or abs(entry - stop) / entry)
            risk = abs(entry - stop)
            cbt = s.get("confirm_bar_time")
            rows.append({
                "year": int(str(c["since"])[:4]),
                "since": c["since"],
                "until": c["until"],
                "kind": t["entry_kind"],
                "dir": t["direction"],
                "outcome": t["outcome"],
                "r_net": float(t["r_net"]),
                "entry": entry, "stop": stop, "tp": tp, "sp": sp,
                "tp_r": abs(tp - entry) / risk if risk else np.nan,
                "entry_bar": int(t["entry_bar"]),
                "exit_bar": int(t.get("exit_bar") or t["entry_bar"]),
                "cbt": pd.Timestamp(cbt) if cbt else pd.NaT,
                "hash": str(t["hash"]),
            })
    d = pd.DataFrame(rows)
    d["fee_mexc"] = [fee_r(k, o, s, MEXC_M, MEXC_T) for k, o, s in zip(d.kind, d.outcome, d.sp)]
    d["fee_bybit"] = [fee_r(k, o, s, BYBIT_M, BYBIT_T) for k, o, s in zip(d.kind, d.outcome, d.sp)]
    d["gross"] = d["r_net"] + d["fee_mexc"]
    d["net_bybit"] = d["gross"] - d["fee_bybit"]
    return d


def block(title: str, d: pd.DataFrame) -> None:
    n = len(d)
    if n == 0:
        print(f"{title}: n=0"); return
    tp = int((d.outcome == "tp").sum()); sl = int((d.outcome == "sl").sum())
    wr = 100 * tp / (tp + sl) if tp + sl else float("nan")
    print(
        f"{title:28} n={n:5d} WR={wr:5.1f}%  "
        f"netMEXC={d.r_net.sum():+8.1f} avg={d.r_net.mean():+.4f}  "
        f"gross={d.gross.mean():+.4f}  netBybit={d.net_bybit.sum():+8.1f} avg={d.net_bybit.mean():+.4f}"
    )


def sim_1r_year(d: pd.DataFrame, year: int, since: str, until: str) -> pd.Series:
    """TP=1R по 1m-пути с open 5m-бара входа. Грубо, но без look-ahead сверх старого филла."""
    df5, _ = load_ltf(tf="5m", since=since, until=until, symbol="SOL")
    df1, _ = load_ltf(tf="1m", since=since, until=until, symbol="SOL")
    ts5 = df5.index
    ts1 = pd.DatetimeIndex(df1.index).to_numpy(dtype="datetime64[ns]").astype("int64") // 60_000_000_000
    hi, lo, cl = (df1[k].to_numpy(dtype=float) for k in ("high", "low", "close"))
    out = []
    q = d[d.year == year]
    for r in q.itertuples():
        if r.entry_bar < 0 or r.entry_bar >= len(ts5):
            out.append(np.nan); continue
        t0 = ts5[r.entry_bar]
        t0m = int(pd.Timestamp(t0).value // 60_000_000_000)
        j = int(np.searchsorted(ts1, t0m, side="left"))
        if j >= len(ts1):
            out.append(np.nan); continue
        entry, stop = float(r.entry), float(r.stop)
        risk = abs(entry - stop)
        if risk <= 0:
            out.append(np.nan); continue
        long = r.dir == "LONG"
        # hold 12h = 720 1m bars
        slc = slice(j, min(len(hi), j + 720 + 1))
        kh, kl, kc = hi[slc], lo[slc], cl[slc]
        if long:
            fav = (kh - entry) / risk
            adv = (entry - kl) / risk
        else:
            fav = (entry - kl) / risk
            adv = (kh - entry) / risk
        i_sl = int(np.where(adv >= 1.0)[0][0]) if (adv >= 1.0).any() else 10 ** 9
        i_tp = int(np.where(fav >= 1.0)[0][0]) if (fav >= 1.0).any() else 10 ** 9
        if i_tp <= i_sl and i_tp != 10 ** 9:
            out.append(1.0)
        elif i_sl != 10 ** 9:
            out.append(-1.0)
        else:
            px = float(kc[-1])
            out.append((px - entry) / risk if long else (entry - px) / risk)
    return pd.Series(out, index=q.index)


def main() -> None:
    d = load_old()
    print("=" * 88)
    print("СТАРАЯ КНИГА  both/A+V  fib TP  MEXC  (кэш 2026-07-24)")
    print("=" * 88)
    block("все", d)
    block("LIMIT", d[d.kind == "LIMIT"])
    block("MARKET", d[d.kind == "MARKET"])
    print()
    print("по годам (все / LIMIT / MARKET avg net MEXC):")
    print(f"{'год':6} {'n':>5} {'all':>8} {'LIM n':>6} {'LIM':>8} {'MKT n':>6} {'MKT':>8}")
    for y in sorted(d.year.unique()):
        q = d[d.year == y]
        L, M = q[q.kind == "LIMIT"], q[q.kind == "MARKET"]
        print(f"{y}  {len(q):5d} {q.r_net.mean():+8.4f} {len(L):6d} {L.r_net.mean():+8.4f} "
              f"{len(M):6d} {M.r_net.mean():+8.4f}")
    print()
    block("2020-2023 все", d[d.year.isin(EARLY)])
    block("2024-2026 все", d[d.year.isin(LATE)])
    block("2020-2023 LIMIT", d[d.year.isin(EARLY) & (d.kind == "LIMIT")])
    block("2024-2026 LIMIT", d[d.year.isin(LATE) & (d.kind == "LIMIT")])
    block("2020-2023 MARKET", d[d.year.isin(EARLY) & (d.kind == "MARKET")])
    block("2024-2026 MARKET", d[d.year.isin(LATE) & (d.kind == "MARKET")])

    print()
    print("=" * 88)
    print("TP=1R на тех же филлах (1m path, hold 12ч), комиссии пересчитываем")
    print("=" * 88)
    r1 = []
    for f in sorted(glob.glob(f"{CACHE}/SOL_tf7_*_1m_lim10m.pkl")):
        c = pickle.load(open(f, "rb"))
        year = int(str(c["since"])[:4])
        print(f"  1R {year}...", flush=True)
        r1.append(sim_1r_year(d, year, c["since"], c["until"]))
    d["r_1r"] = pd.concat(r1).reindex(d.index)
    # комиссии для 1R: исход tp/sl/time по знаку r_1r
    oc = np.where(d.r_1r >= 0.999, "tp", np.where(d.r_1r <= -0.999, "sl", "time"))
    d["fee_mexc_1r"] = [fee_r(k, o, s, MEXC_M, MEXC_T) for k, o, s in zip(d.kind, oc, d.sp)]
    d["fee_bybit_1r"] = [fee_r(k, o, s, BYBIT_M, BYBIT_T) for k, o, s in zip(d.kind, oc, d.sp)]
    d["net_mexc_1r"] = d.r_1r - d.fee_mexc_1r
    d["net_bybit_1r"] = d.r_1r - d.fee_bybit_1r
    ok = d.r_1r.notna()

    def b1(title, q):
        q = q[q.r_1r.notna()]
        n = len(q)
        if n == 0:
            return
        wr = 100 * (q.r_1r >= 0.999).sum() / max(1, ((q.r_1r >= 0.999) | (q.r_1r <= -0.999)).sum())
        print(f"{title:28} n={n:5d} WR1R={wr:5.1f}%  "
              f"gross1R={q.r_1r.mean():+.4f}  "
              f"netMEXC={q.net_mexc_1r.mean():+.4f} Σ{q.net_mexc_1r.sum():+.0f}  "
              f"netBybit={q.net_bybit_1r.mean():+.4f} Σ{q.net_bybit_1r.sum():+.0f}")

    b1("все 1R", d)
    b1("LIMIT 1R", d[d.kind == "LIMIT"])
    b1("MARKET 1R", d[d.kind == "MARKET"])
    b1("2020-23 1R", d[d.year.isin(EARLY)])
    b1("2024-26 1R", d[d.year.isin(LATE)])
    b1("2020-23 LIMIT 1R", d[d.year.isin(EARLY) & (d.kind == "LIMIT")])
    b1("2024-26 LIMIT 1R", d[d.year.isin(LATE) & (d.kind == "LIMIT")])

    d.to_pickle(r"D:/PYTHON/cisdbotbybit/RUNS/temp/sol_tf7_old_book.pkl")
    print("\nсохранено sol_tf7_old_book.pkl")


if __name__ == "__main__":
    main()
