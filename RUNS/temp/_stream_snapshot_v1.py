"""Снапшот честного потока v1.2 (filters-off кэши): мета + геометрия + TP1R-исходы.

Поток = LIMIT-сделки кэша + vwap-гейт (scan-бар; S: vd<=0, L: vd>=0 — пороги живого бота, 14.09) + min_stop 0.25%
        + честное окно постановки from_ts=ceil5(cbt+conf) [+20м tf7 / +30м tf8]
        + исход по TP 1R (SL/TP/TIME) на 1m, комиссии 0.036/0.10.
Кэш-исходы (родной TP) сохраняются отдельно: outcome_native / r_native.
Координаты: trigger_idx локальный в окне 200 → global = max(0,scan_bar-199)+trigger_idx (проверено).
"""
import argparse
import ast
import os
import pickle
import sys

import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from backtest.data import load_ltf
from backtest.sweep_atr_filter import compute_atr14, sweep_atr_ratio
from backtest.volume_filter import volume_ratio_series
from cryptofish.adapters.features import daily_session_vwap

PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]
YEARS = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
MIN_STOP = 0.0025
WINDOW = 200
MAKER = 0.00036
TAKER = 0.0010
CONF = {"tf7": (1, 20 / 60, 16, "5m"), "tf8": (5, 0.5, 6, "30m")}  # conf_add, limit_h, pos_h, dft_tf
QKEYS = ["start_n", "never", "unreclaim", "no_start_fvg", "no_conf_fvg"]
SIG_STR = ["confirm_bar_time", "htf_time", "trigger_bar_time", "sweep_close_bar_time"]
SIG_NUM = ["prior_touches", "quality_score", "psl_probability", "psl_quartile"]
SIG_FLAG = ["soft_dow", "late_retest", "one_bar_sweep_cisd", "confirm_on_sweep", "fib_stretch_market"]


def _num(v):
    try:
        return None if v is None else float(v)
    except Exception:
        return None


def _bool(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() == "true"


def trig_global(scan_bar, trigger_idx, n):
    if scan_bar is None or trigger_idx is None:
        return None
    gi = max(0, int(scan_bar) - (WINDOW - 1)) + int(trigger_idx)
    return gi if 0 <= gi < n else None


def simulate_tp1(df1, from_ts, win_end, entry, stop, long, sp, pos_h):
    """Копия final_early_sum.simulate: возвращает (outcome, r, hit_ts, exit_ts) или None."""
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
    conf_add, limit_h, pos_h, _ = CONF[prof]
    with open(path, "rb") as fh:
        c = pickle.load(fh)
    sigs = {str(s.get("hash")): s for s in c.get("signals") or []}
    trades = [t for t in (c.get("trades") or []) if str(t.get("entry_kind") or "").upper() == "LIMIT"]
    atr = compute_atr14(dft)
    vwap = daily_session_vwap(dft)
    volr = volume_ratio_series(dft, 20)
    rows, n_v, n_ms = [], 0, 0
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
        vd = (float(dft.iloc[i]["close"]) - v) / a
        d = str(t.get("direction") or s.get("direction") or "")
        if d == "SHORT" and not (vd <= 0):
            continue
        if d == "LONG" and not (vd >= 0):  # порог живого бота (14.09): LONG vd>=0
            continue
        n_v += 1
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
        out = simulate_tp1(df1, from_ts, win_end, entry, stop, d == "LONG", sp, pos_h)
        if out is None:
            continue
        outcome, r_tp1, hit_ts, exit_ts = out
        gi = trig_global(sb, s.get("trigger_idx"), len(dft))
        sw = None
        vr = None
        if gi is not None:
            lvl = _num(s.get("htf_sweep_level"))
            if lvl and lvl > 0:
                sw = sweep_atr_ratio(dft, gi, lvl, d == "SHORT", atr14=atr)
            if pd.notna(volr.iloc[gi]):
                vr = float(volr.iloc[gi])
        eb = t.get("entry_bar")
        try:
            eb = int(eb) if eb is not None and pd.notna(eb) else None
        except Exception:
            eb = None
        row = {
            "sym": sym, "prof": prof, "year": year, "dir": d,
            "outcome": outcome, "r_net": round(r_tp1, 6),
            "outcome_native": t.get("outcome"), "r_native": float(t.get("r_net") or 0.0),
            "entry": entry, "stop": stop, "tp": float(t.get("tp") or 0.0), "sp": round(sp, 6),
            "vd": round(vd, 6), "sweep_atr": (round(sw, 4) if sw is not None else None),
            "vol_ratio": (round(vr, 4) if vr is not None else None),
            "scan_bar": i, "trigger_gi": gi, "entry_bar": eb,
            "from_ts": str(from_ts), "ts_fill": str(hit_ts),
            "exit_ts": str(exit_ts),
            "decision_at": str(dft.index[i] + pd.Timedelta(minutes=(5 if prof == "tf7" else 30))),
            "fill_wait_min": round((hit_ts - from_ts).total_seconds() / 60, 1),
            "ts_scan": str(dft.index[i]),
            "hash": str(t.get("hash")),
        }
        if row["tp"] > 0 and stop != entry:
            row["rr_planned"] = round(abs(row["tp"] - entry) / abs(entry - stop), 4)
        else:
            row["rr_planned"] = None
        for k in SIG_STR:
            row[k] = str(s.get(k)) if s.get(k) is not None else None
        for k in SIG_NUM:
            val = _num(s.get(k))
            if k in ("prior_touches", "psl_quartile") and val is not None:
                val = int(val)
            row[k] = val
        for k in SIG_FLAG:
            row[k] = _bool(s.get(k))
        q = s.get("quality")
        if isinstance(q, str):
            try:
                q = ast.literal_eval(q)
            except Exception:
                q = {}
        if not isinstance(q, dict):
            q = {}
        for k in QKEYS:
            row["q_" + k] = q.get(k)
        rows.append(row)
    tp = sum(1 for r in rows if r["outcome"] == "tp")
    sl = sum(1 for r in rows if r["outcome"] == "sl")
    summ = {
        "sym": sym, "prof": prof, "year": year, "lim": len(trades), "vwap_kept": n_v, "minstop": n_ms,
        "n": len(rows), "wr": (round(100 * tp / (tp + sl), 1) if (tp + sl) else None),
        "sumr": round(sum(r["r_net"] for r in rows), 2),
        "sumr_native": round(sum(r["r_native"] for r in rows), 2),
    }
    return rows, summ


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=r"D:/PYTHON/CISDBOT/RUNS/filters_off_full")
    ap.add_argument("--only", default="")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()
    tax = f"_{args.tag}" if args.tag else ""
    base = r"D:/PYTHON/cisdbotbybit/RUNS/temp/stream_off_v1"
    out_pkl = f"{base}{tax}.pkl"
    out_csv = f"{base}{tax}.csv"
    out_sum = f"{base}{tax}_sum.txt"
    only = None
    if args.only:
        only = set(tuple(x.split(":")) for x in args.only.split(","))
    all_rows, summaries = [], []
    for sym in PAIRS:
        for year in YEARS:
            if not os.path.exists(f"{args.dir}/{sym}_tf7_{year}-01-01_{year}-12-31.pkl") and \
               not os.path.exists(f"{args.dir}/{sym}_tf8_{year}-01-01_{year}-12-31.pkl"):
                continue
            if only and not any((sym, p, str(year)) in only for p in ("tf7", "tf8")):
                continue
            d5 = d30 = d1 = None
            for prof in ("tf7", "tf8"):
                if only and (sym, prof, str(year)) not in only:
                    continue
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
                if rows is None:
                    continue
                all_rows.extend(rows)
                summaries.append(summ)
                print(f"{sym} {prof} {year}: lim={summ['lim']} vwap={summ['vwap_kept']} "
                      f"ms={summ['minstop']} filled={summ['n']} WR={summ['wr']} "
                      f"Σtp1={summ['sumr']} Σnat={summ['sumr_native']}", flush=True)
    df = pd.DataFrame(all_rows)
    df.to_pickle(out_pkl)
    df.to_csv(out_csv, index=False, encoding="utf-8")
    tp = int((df.outcome == "tp").sum()) if len(df) else 0
    sl = int((df.outcome == "sl").sum()) if len(df) else 0
    tot = float(df["r_net"].sum()) if len(df) else 0.0
    with open(out_sum, "w", encoding="utf-8") as f:
        f.write(f"STREAM v1.2 ({args.dir}) | filled n={len(df)} | Σr(TP1R)={tot:.1f} | "
                f"WR={100*tp/max(1,tp+sl):.1f}%\n")
        for s in summaries:
            f.write(str(s) + "\n")
    print(f"ИТОГО: n={len(df)} Σr(TP1R)={tot:.1f}")
    print("saved:", out_pkl)


if __name__ == "__main__":
    main()
