"""Проба старого кэша SOL tf7 lim10m (оба фильтра + D-like)."""
import glob
import pickle
from collections import Counter

import pandas as pd

CACHE = "D:/PYTHON/CISDBOT/RUNS/cache"
files = sorted(glob.glob(f"{CACHE}/SOL_tf7_*_1m_lim10m.pkl"))
print("файлов both:", len(files))
for f in files:
    print(" ", f.split("\\")[-1].split("/")[-1])

trades, sigs = [], []
meta = None
for f in files:
    c = pickle.load(open(f, "rb"))
    if meta is None:
        meta = {k: c.get(k) for k in c if k not in ("trades", "signals", "df")}
    trades.extend(c.get("trades") or [])
    sigs.extend(c.get("signals") or [])

print("\nMETA keys:", sorted((meta or {}).keys())[:40])
print("meta sample:", {k: meta.get(k) for k in (
    "fee_model", "limit_bars", "pos_bars", "detector_stack", "filter_variant",
    "sw_atr_min", "trigger_vol_max", "cancel_fib2", "entry_policy", "profile",
) if meta})

print("n trades", len(trades), "n sigs", len(sigs))
if not trades:
    raise SystemExit

t0 = trades[0]
print("trade keys:", sorted(t0.keys()))
print("sample trade:")
for k in ("entry_time", "exit_time", "entry_px", "entry", "stop", "tp", "r_net",
          "r_gross", "outcome", "entry_kind", "direction", "hash",
          "confirm_bar_time", "fill_time", "fees"):
    if k in t0:
        print(f"  {k}: {t0[k]}")

# merge signals
smap = {str(s.get("hash")): s for s in sigs}
print("sig keys sample:", sorted((sigs[0] or {}).keys())[:50] if sigs else None)

rows = []
for t in trades:
    s = smap.get(str(t.get("hash")), {})
    entry = float(t.get("entry_px") or t.get("entry") or 0)
    stop = float(t.get("stop") or 0)
    tp = float(t.get("tp") or t.get("tp_price") or 0)
    risk = abs(entry - stop) if entry and stop else None
    tp_r = abs(tp - entry) / risk if risk and tp else None
    cbt = s.get("confirm_bar_time") or t.get("confirm_bar_time")
    et = t.get("entry_time") or t.get("fill_time") or t.get("entry_at")
    lag = None
    if cbt is not None and et is not None:
        lag = (pd.Timestamp(et) - pd.Timestamp(cbt)).total_seconds() / 60.0
    rows.append({
        "year": pd.Timestamp(et if et is not None else cbt).year if (et or cbt) else None,
        "r_net": float(t.get("r_net") or 0),
        "r_gross": float(t.get("r_gross") or 0) if t.get("r_gross") is not None else None,
        "outcome": t.get("outcome"),
        "kind": t.get("entry_kind"),
        "dir": t.get("direction"),
        "stop_pct": abs(entry - stop) / entry * 100 if entry and stop else None,
        "tp_r": tp_r,
        "lag_min": lag,
        "entry": entry,
        "stop": stop,
    })

d = pd.DataFrame(rows)
print("\nисходы:", Counter(d["outcome"]))
print("kinds:", Counter(d["kind"]))
print("n", len(d), "WR", (d.outcome.eq("tp").sum() / d.outcome.isin(["tp","sl"]).sum()))
print("SumR net", d.r_net.sum(), "avg", d.r_net.mean())
if d.r_gross.notna().any():
    print("SumR gross", d.r_gross.sum(), "avg", d.r_gross.mean())
print("tp_r median/mean", d.tp_r.median(), d.tp_r.mean())
print("lag_min p50/p10/p90", d.lag_min.median(), d.lag_min.quantile(0.1), d.lag_min.quantile(0.9))
print("lag < 0 (fill before confirm open):", int((d.lag_min < 0).sum()))
print("lag < 1 (fill inside confirm 1m bar):", int((d.lag_min < 1).sum()))
print("\nпо годам:")
for y, q in d.groupby("year"):
    wr = q.outcome.eq("tp").sum() / q.outcome.isin(["tp","sl"]).sum()
    print(f"  {y}: n={len(q):4d} WR={wr:.3f} net={q.r_net.sum():+.1f} avg={q.r_net.mean():+.4f}"
          + (f" gross_avg={q.r_gross.mean():+.4f}" if q.r_gross.notna().any() else ""))
