"""Снапшот ПОЛНОГО (ungated) LIMIT-потока: без vwap-фильтра, vd на ДВУХ якорях.

Зачем: research-стрим v1.2 фильтровался vd на scan_баре движка (+26/60 мин после
конфирма), а живой бот считает vd на confirm-баре (df.loc[:confirm_bar_time]) →
на гейт-потоке вердикты расходятся на 34%. Здесь: ВСЕ LIMIT-сделки (filters-off кэши),
min_stop 0.25% (как в лайве), исходы TP1R (1m, комиссии), и обе колонки:
  vd_scan  — старый якорь (scan_bar движка);
  vd_conf  — ЛАЙВ-якорь (последний бар, закрытый к from_ts = confirm+conf).
САНITY: подмножество {S: vd_scan≤0, L: vd_scan≥0} должно воспроизвести стрим v2
(n≈25230, Σr≈+5429.2) — печатается в конце.

Вход: D:/PYTHON/CISDBOT/RUNS/filters_off_full. Выход: stream_ungated_v2.pkl/.csv/.sum
"""
import argparse
import os
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from backtest.data import load_ltf
from backtest.sweep_atr_filter import compute_atr14
from cryptofish.adapters.features import daily_session_vwap

PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]
YEARS = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
MIN_STOP = 0.0025
MAKER = 0.00036
TAKER = 0.0010
CONF = {"tf7": (1, 20 / 60, 16, "5m", 5), "tf8": (5, 0.5, 6, "30m", 30)}  # conf_add, limit_h, pos_h, dft_tf, tfm


def simulate_tp1(df1, from_ts, win_end, entry, stop, long, sp, pos_h):
    seg = df1.loc[(df1.index >= from_ts) & (df1.index < win_end)]
    if seg.empty:
        return None
    if long:
        m = (seg["low"].to_numpy(float) <= entry)
    else:
        m = (seg["high"].to_numpy(float) >= entry)
    if not m.any():
        return None
    hit_ts = seg.index[int(m.argmax())]
    end_ts = hit_ts + pd.Timedelta(hours=pos_h)
    seg2 = df1.loc[(df1.index >= hit_ts) & (df1.index <= end_ts)]
    tp1 = entry + (entry - stop) if long else entry - (stop - entry)
    r = None
    outcome = "time"
    exit_ts = None
    for ts_x, row in seg2.iterrows():
        if not long:
            if row["high"] >= stop:
                outcome, r, exit_ts = "sl", -1.0 - MAKER / sp - TAKER / sp, ts_x
                break
            if row["low"] <= tp1:
                outcome, r, exit_ts = "tp", 1.0 - 2 * MAKER / sp, ts_x
                break
        else:
            if row["low"] <= stop:
                outcome, r, exit_ts = "sl", -1.0 - MAKER / sp - TAKER / sp, ts_x
                break
            if row["high"] >= tp1:
                outcome, r, exit_ts = "tp", 1.0 - 2 * MAKER / sp, ts_x
                break
    if r is None:
        px = float(seg2.iloc[-1]["close"])
        r = (((entry - px) if not long else (px - entry)) / (entry - stop)) - MAKER / sp - TAKER / sp
        exit_ts = seg2.index[-1]
    exit_ts = pd.Timestamp(exit_ts) + pd.Timedelta(minutes=1)
    return outcome, r, hit_ts, exit_ts


def build_one(sym, prof, year, cdir, dft, df1):
    path = f"{cdir}/{sym}_{prof}_{year}-01-01_{year}-12-31.pkl"
    if not os.path.exists(path):
        return None, None
    conf_add, limit_h, pos_h, _, tfm = CONF[prof]
    with open(path, "rb") as fh:
        c = pickle.load(fh)
    sigs = {str(s.get("hash")): s for s in c.get("signals") or []}
    trades = [t for t in (c.get("trades") or []) if str(t.get("entry_kind") or "").upper() == "LIMIT"]
    atr = compute_atr14(dft)
    vwap = daily_session_vwap(dft)
    ts_arr = dft.index.to_numpy()
    rows, n_oldgate, n_ms = [], 0, 0
    for t in trades:
        s = sigs.get(str(t.get("hash")))
        if not s:
            continue
        sb = s.get("scan_bar")
        try:
            i = int(sb)
        except Exception:
            i = -1
        if not (0 <= i < len(dft)):
            continue
        a = float(atr.iloc[i]) if pd.notna(atr.iloc[i]) else 0.0
        v = float(vwap.iloc[i]) if pd.notna(vwap.iloc[i]) else None
        if not a or a <= 0 or v is None:
            continue
        vd_scan = (float(dft.iloc[i]["close"]) - v) / a
        d = str(t.get("direction") or s.get("direction") or "")
        if (d == "SHORT" and vd_scan <= 0) or (d == "LONG" and vd_scan >= 0):
            n_oldgate += 1
        entry = float(t.get("entry_px") or 0)
        stop = float(t.get("stop") or 0)
        if entry <= 0 or stop <= 0:
            continue
        sp = abs(entry - stop) / entry
        if sp < MIN_STOP:
            continue
        n_ms += 1
        cbt = pd.Timestamp(str(s.get("confirm_bar_time")))
        from_ts = (cbt + pd.Timedelta(minutes=conf_add)).ceil("5min")
        win_end = from_ts + pd.Timedelta(hours=limit_h)
        # vd на лайв-якоре: последний бар, ПОЛНОСТЬЮ закрытый к from_ts
        ic = int(np.searchsorted(ts_arr, np.datetime64(from_ts - pd.Timedelta(minutes=tfm)), "right")) - 1
        vd_conf = None
        if 0 <= ic < len(dft):
            ac = float(atr.iloc[ic]) if pd.notna(atr.iloc[ic]) else 0.0
            vc = float(vwap.iloc[ic]) if pd.notna(vwap.iloc[ic]) else None
            if ac > 0 and vc is not None:
                vd_conf = (float(dft.iloc[ic]["close"]) - vc) / ac
        out = simulate_tp1(df1, from_ts, win_end, entry, stop, d == "LONG", sp, pos_h)
        if out is None:
            continue
        outcome, r_tp1, hit_ts, exit_ts = out
        row = {
            "sym": sym, "prof": prof, "year": year, "dir": d,
            "outcome": outcome, "r_net": round(r_tp1, 6),
            "outcome_native": t.get("outcome"), "r_native": float(t.get("r_net") or 0.0),
            "entry": entry, "stop": stop, "sp": round(sp, 6),
            "vd_scan": round(vd_scan, 6),
            "vd_conf": (round(vd_conf, 6) if vd_conf is not None else None),
            "from_ts": str(from_ts), "ts_fill": str(hit_ts), "exit_ts": str(exit_ts),
            "decision_at": str(dft.index[i] + pd.Timedelta(minutes=(5 if prof == "tf7" else 30))),
            "fill_wait_min": round((hit_ts - from_ts).total_seconds() / 60, 1),
            "hash": str(t.get("hash")),
        }
        rows.append(row)
    tp = sum(1 for r in rows if r["outcome"] == "tp")
    sl = sum(1 for r in rows if r["outcome"] == "sl")
    summ = {
        "sym": sym, "prof": prof, "year": year, "lim": len(trades), "oldgate": n_oldgate,
        "minstop": n_ms, "filled": len(rows),
        "wr": (round(100 * tp / (tp + sl), 1) if (tp + sl) else None),
        "sumr": round(sum(r["r_net"] for r in rows), 2),
    }
    return rows, summ


def gate_line(g, mask, label):
    d = g[mask]
    tp = int((d.outcome == "tp").sum())
    sl = int((d.outcome == "sl").sum())
    wr = round(100 * tp / max(1, tp + sl), 1)
    return f"  {label:34}: n={len(d):6d} WR={wr:5.1f}% SumR={d.r_net.sum():+9.1f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=r"D:/PYTHON/CISDBOT/RUNS/filters_off_full")
    args = ap.parse_args()
    all_rows, summaries = [], []
    for sym in PAIRS:
        for year in YEARS:
            if not os.path.exists(f"{args.dir}/{sym}_tf7_{year}-01-01_{year}-12-31.pkl") and \
               not os.path.exists(f"{args.dir}/{sym}_tf8_{year}-01-01_{year}-12-31.pkl"):
                continue
            d5 = d30 = d1 = None
            for prof in ("tf7", "tf8"):
                try:
                    if prof == "tf7" and d5 is None:
                        d5, _ = load_ltf(tf="5m", since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
                        d5.index = pd.DatetimeIndex(d5.index)
                    if prof == "tf8" and d30 is None:
                        d30, _ = load_ltf(tf="30m", since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
                        d30.index = pd.DatetimeIndex(d30.index)
                    if d1 is None:
                        d1, _ = load_ltf(tf="1m", since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
                        d1.index = pd.DatetimeIndex(d1.index)
                    rows, summ = build_one(sym, prof, year, args.dir, d5 if prof == "tf7" else d30, d1)
                except Exception as e:
                    print(f"FAIL {sym} {prof} {year}: {e!r}", flush=True)
                    continue
                if rows is None:
                    continue
                all_rows.extend(rows)
                summaries.append(summ)
                print(f"{sym} {prof} {year}: lim={summ['lim']} oldgate={summ['oldgate']} "
                      f"ms={summ['minstop']} filled={summ['filled']} WR={summ['wr']} "
                      f"Σtp1={summ['sumr']}", flush=True)
    df = pd.DataFrame(all_rows)
    out_pkl = r"D:/PYTHON/cisdbotbybit/RUNS/temp/stream_ungated_v2.pkl"
    df.to_pickle(out_pkl)
    df.to_csv(out_pkl.replace(".pkl", ".csv"), index=False, encoding="utf-8")

    print("\n=== ПОЛНЫЙ ПОТОК (ungated) ===", flush=True)
    print(f"  всего filled: n={len(df)} ΣR={df.r_net.sum():+.1f}", flush=True)
    tp = int((df.outcome == "tp").sum()); sl = int((df.outcome == "sl").sum())
    print(f"  WR={100*tp/max(1,tp+sl):.1f}%", flush=True)

    print("\n=== SANITY: старое гейт-подмножество (на vd_scan) ===", flush=True)
    m_scan = ((df["dir"] == "SHORT") & (df.vd_scan <= 0)) | ((df["dir"] == "LONG") & (df.vd_scan >= 0))
    d = df[m_scan]
    tp = int((d.outcome == "tp").sum()); sl = int((d.outcome == "sl").sum())
    print(f"  ожидаем ~25230 / +5429.2: n={len(d)} ΣR={d.r_net.sum():+.1f} WR={100*tp/max(1,tp+sl):.1f}%", flush=True)

    for tag, col in (("скан-якорь (research)", "vd_scan"), ("КОНФИРМ-якорь (ЛАЙВ)", "vd_conf")):
        print(f"\n=== ГЕЙТ на {tag} — ПОЛНЫЙ поток ===", flush=True)
        g = df[df[col].notna()].copy()
        print(gate_line(g, (g["dir"] == "SHORT") & (g[col] <= 0), "S vd<=0 (оставляем)"), flush=True)
        print(gate_line(g, (g["dir"] == "SHORT") & (g[col] > 0), "S vd>0 (режем)"), flush=True)
        print(gate_line(g, (g["dir"] == "LONG") & (g[col] >= 0), "L vd>=0 (оставляем)"), flush=True)
        print(gate_line(g, (g["dir"] == "LONG") & (g[col] < 0), "L vd<0 (режем)"), flush=True)
        m = ((g["dir"] == "SHORT") & (g[col] <= 0)) | ((g["dir"] == "LONG") & (g[col] >= 0))
        print(gate_line(g, m, "КОМБО гейт (деплой)"), flush=True)
        print(f"  --- по годам (комбо):", flush=True)
        for y, gy in g.groupby("year"):
            my = ((gy["dir"] == "SHORT") & (gy[col] <= 0)) | ((gy["dir"] == "LONG") & (gy[col] >= 0))
            dy = gy[my]
            print(f"    {int(y)}: n={len(dy):5d} ΣR={dy.r_net.sum():+8.1f} avg={dy.r_net.mean():+.3f}", flush=True)

    print("\n=== ЗОНЫ vd_conf (полный поток, по направлениям) ===", flush=True)
    bins = [-100, -4, -3, -2, -1, 0, 1, 2, 3, 4, 100]
    lbls = ["<=-4", "-4..-3", "-3..-2", "-2..-1", "-1..0", "0..1", "1..2", "2..3", "3..4", ">4"]
    for dr in ("LONG", "SHORT"):
        d = df[(df["dir"] == dr) & df.vd_conf.notna()].copy()
        d["zone"] = pd.cut(d.vd_conf, bins=bins, labels=lbls)
        g = d.groupby("zone", observed=True).agg(n=("r_net", "size"), sumr=("r_net", "sum"))
        g["avg"] = (g.sumr / g.n).round(3)
        print(f"\n--- {dr} ---", flush=True)
        print(g.round(1).to_string(), flush=True)

    print("\nsaved:", out_pkl, flush=True)


if __name__ == "__main__":
    main()
