"""Лаг филла vs confirm на старом кэше SOL tf7."""
import glob
import pickle

import pandas as pd

CACHE = "D:/PYTHON/CISDBOT/RUNS/cache"
f = f"{CACHE}/SOL_tf7_2024-01-01_2024-12-31_1m_lim10m.pkl"
c = pickle.load(open(f, "rb"))
trades = c["trades"]
sigs = {str(s.get("hash")): s for s in c["signals"]}
print("2024 trades", len(trades), "sigs", len(sigs))
s = sigs[str(trades[0]["hash"])]
print("sig times:")
for k in ("confirm_bar_time", "confirm_timeframe", "sweep_close_bar_time",
          "sweep_confirm_5m_time", "trigger_bar_time", "timestamp", "scan_bar",
          "confirm_idx", "fib_stretch_market", "tp", "stop", "entry"):
    print(f"  {k}: {s.get(k)}")
print("trade:", {k: trades[0][k] for k in trades[0]})

rows = []
for t in trades:
    s = sigs.get(str(t.get("hash")), {})
    cbt = s.get("confirm_bar_time")
    sw = s.get("sweep_close_bar_time") or s.get("sweep_confirm_5m_time")
    scan = s.get("scan_bar")
    ts = s.get("timestamp")
    rows.append({
        "kind": t.get("entry_kind"),
        "cbt": pd.Timestamp(cbt) if cbt else pd.NaT,
        "sw": pd.Timestamp(sw) if sw else pd.NaT,
        "scan": scan,
        "entry_bar": t.get("entry_bar"),
        "created_lag_bars": (t.get("entry_bar") - scan) if scan is not None else None,
        "fib_mkt": bool(s.get("fib_stretch_market")),
        "r_net": float(t.get("r_net") or 0),
        "outcome": t.get("outcome"),
        "tp_r": abs(float(t["tp"]) - float(t["entry_px"])) / abs(float(t["entry_px"]) - float(t["stop"])),
    })
d = pd.DataFrame(rows)
print("\ncreated_lag_bars (entry_bar - scan_bar) by kind:")
print(d.groupby("kind")["created_lag_bars"].describe())
print("fib_stretch_market vs kind:")
print(pd.crosstab(d.kind, d.fib_mkt))
print("scan vs entry_bar equal:", int((d.entry_bar == d.scan).sum()), "/", len(d))
print("entry_bar < scan (fill before detect bar):", int((d.entry_bar < d.scan).sum()))
print("\nMARKET avgR", d.loc[d.kind=="MARKET","r_net"].mean(), "n", (d.kind=="MARKET").sum())
print("LIMIT avgR", d.loc[d.kind=="LIMIT","r_net"].mean(), "n", (d.kind=="LIMIT").sum())
