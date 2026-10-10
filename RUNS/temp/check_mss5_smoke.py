"""Smoke-проверка прогона №2: сравнить SOL_2025 старый (30m-MSS) vs новый (5m-MSS)."""
import pickle
from collections import Counter

n = pickle.load(open(r"D:/PYTHON/cisdbotbybit/RUNS/temp/early_entry_mss5/SOL_2025.pkl", "rb"))
o = pickle.load(open(r"D:/PYTHON/cisdbotbybit/RUNS/temp/early_entry/SOL_2025.pkl", "rb"))
for name, p in (("old(30m-MSS)", o), ("new(5m-MSS) ", n)):
    sigs = p.get("signals") or []
    trades = p.get("trades") or []
    ctf = Counter(s.get("confirm_timeframe") for s in sigs)
    ek = Counter(t.get("entry_kind") for t in trades)
    print(f"{name}: signals={len(sigs)} trades={len(trades)}")
    print(f"   confirm_timeframe: {dict(ctf)}")
    print(f"   entry_kinds: {dict(ek)}")

sh = {str(s.get("hash")) for s in (n.get("signals") or [])}
oh = {str(s.get("hash")) for s in (o.get("signals") or [])}
print("hash overlap:", len(sh & oh), "| new-only:", len(sh - oh), "| old-only:", len(oh - sh))

# пример нового сигнала
if n.get("signals"):
    s = n["signals"][0]
    keep = {k: s.get(k) for k in ("hash", "direction", "cisd_level", "confirm_bar_time",
                                  "confirm_close", "trigger_bar_time", "htf_time", "confirm_timeframe")}
    print("sample new signal:", keep)
