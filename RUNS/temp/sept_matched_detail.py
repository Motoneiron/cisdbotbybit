"""Разбор: какие сделки совпали и какие исходы (tp/sl) в каждой группе."""
import json
import pickle
from collections import Counter
from pathlib import Path

T = Path(r"D:/PYTHON/cisdbotbybit/RUNS/temp")
live = json.load(open(T / "live_recon/sept_tf7_trades.json", encoding="utf-8"))
rec = pickle.load(open(T / "live_recon/sept_recon_mss.pkl", "rb"))
tr, sg = rec["trades"], rec["signals"]

def key(pair, dr, ts):
    return f"{pair}|{dr}|{str(ts)[:13]}"

sig_keys = {}
for s in sg:
    sig_keys.setdefault(key(s.get("_pair"), s.get("direction"), s.get("htf_time")), []).append(s)
tr_keys = {}
for t in tr:
    tr_keys.setdefault(key(t.get("_pair"), t.get("direction"), t.get("htf_time")), []).append(t)
sig_hash = {str(s.get("hash")): s for s in sg}
tr_hash = {str(t.get("hash")): t for t in tr}

def o_norm(v):
    v = str(v)
    return "tp" if "tp" in v else ("sl" if "sl" in v else "other")

matched = []
unmatched = []
for v in live:
    pair, dr, ts = v.get("sym_guess"), v.get("direction"), v.get("htf_time")
    h = str(v.get("sig_hash"))
    kk = key(pair, dr, ts)
    row = {"id": v["id"], "pair": pair, "dr": dr, "ts": str(ts)[:16], "live": o_norm(v.get("status"))}
    if h in sig_hash or h in tr_hash:
        row["kind"] = "HASH"
        matched.append(row)
    elif kk in tr_keys:
        t = tr_keys[kk][0]
        row["kind"] = f"трейд ({o_norm(t.get('outcome'))})"
        matched.append(row)
    elif kk in sig_keys:
        row["kind"] = "сигнал (лимитка не исполнилась)"
        matched.append(row)
    else:
        unmatched.append(row)

print("=== 26 сентябрьских (shadow): исходы ВСЕГО:", dict(Counter(v["live"] for v in matched + unmatched)))
print("  matched:", dict(Counter(v["live"] for v in matched)), "| не найдено:", dict(Counter(v["live"] for v in unmatched)))
print()
print("=== СОВПАВШИЕ 6:")
for m in matched:
    print(f"   {m['id']} {m['pair']:>4} {m['dr']:>5} {m['ts']} | живой: {m['live']:>3} | у нас: {m['kind']}")
print()
print("=== НЕ совпавшие 20 (по исходам):")
print("   ", dict(Counter(v["live"] for v in unmatched)))

print()
print("=== наши 61 сделки на окне: исходы:", dict(Counter(o_norm(t.get("outcome")) for t in tr)))
print("=== наши 121 сигнал: сколько стали сделками:", len(tr), "| не исполнено:", len(sg) - len(set(str(t.get('hash')) for t in tr)), "(прим.)")
