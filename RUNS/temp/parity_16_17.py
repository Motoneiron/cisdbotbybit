"""Паритет 16-17.09.2026: сетапы бэктеста (свежий прогон движка на данных Bybit)
против живых лимиток/позиций SHADOW (из shadow_positions.json, снято 17.09 19:4x).
Сопоставление по (пара, направление, цена входа).
"""
import pickle

import pandas as pd

# живые записи, созданные 16-17.09 (из shadow_positions.json)
L = [
    ("ADA", "LONG", "2026-09-16 00:00", 0.1946, "closed_time"),
    ("KAS", "LONG", "2026-09-16 00:00", 0.03253, "closed_sl"),
    ("LINK", "LONG", "2026-09-16 08:00", 10.812, "voided_invalid_setup"),
    ("ETH", "LONG", "2026-09-16 08:00", 2405.4, "voided_invalid_setup"),
    ("BTC", "LONG", "2026-09-16 08:00", 75999.9, "closed_time"),
    ("DOGE", "LONG", "2026-09-16 08:00", 0.08019, "voided_invalid_setup"),
    ("BNB", "LONG", "2026-09-16 08:00", 713.9, "voided_invalid_setup"),
    ("SOL", "SHORT", "2026-09-16 08:00", 97.24, "closed_tp"),
    ("XRP", "LONG", "2026-09-16 16:00", 1.2675, "voided_invalid_setup"),
    ("ADA", "LONG", "2026-09-16 08:00", 0.1923, "voided_invalid_setup"),
    ("DOGE", "LONG", "2026-09-16 16:00", 0.07924, "closed_tp"),
    ("KAS", "LONG", "2026-09-16 08:00", 0.03225, "voided_invalid_setup"),
    ("LTC", "LONG", "2026-09-16 08:00", 50.72, "voided_invalid_setup"),
    ("BTC", "SHORT", "2026-09-16 16:00", 75681.0, "closed_time"),
    ("ETH", "SHORT", "2026-09-16 16:00", 2387.67, "closed_sl"),
    ("LTC", "SHORT", "2026-09-16 16:00", 50.58, "closed_sl"),
    ("ADA", "LONG", "2026-09-16 16:00", 0.1942, "closed_time"),
    ("BNB", "SHORT", "2026-09-17 00:00", 724.0, "closed_time"),
    ("LINK", "SHORT", "2026-09-17 00:00", 11.084, "closed_sl"),
    ("DOGE", "SHORT", "2026-09-17 08:00", 0.08113, "cancelled_timeout"),
    ("LINK", "SHORT", "2026-09-17 08:00", 11.169, "cancelled_timeout"),
    ("SOL", "SHORT", "2026-09-17 08:00", 99.98, "cancelled_timeout"),
    ("KAS", "SHORT", "2026-09-17 08:00", 0.03416, "cancelled_timeout"),
    ("XRP", "LONG", "2026-09-17 08:00", 1.3121, "open"),
]

bt = pickle.load(open("D:/PYTHON/cisdbotbybit/RUNS/temp/bt_recent_tf8.pkl", "rb"))
B = []
for sym, d in bt.items():
    tr = {str(t.get("hash")): t for t in d["trades"]}
    for s in d["signals"]:
        ts = pd.to_datetime(str(s.get("trigger_bar_time")), errors="coerce")
        if pd.isna(ts) or not (pd.Timestamp("2026-09-16") <= ts <= pd.Timestamp("2026-09-18")):
            continue
        t = tr.get(str(s.get("hash"))) or {}
        B.append(dict(sym=sym, dir=s.get("direction"), htf=str(s.get("htf_time"))[:16],
                      entry=float(s.get("entry") or 0), outcome=t.get("outcome"),
                      r=t.get("r_net"), trig=str(ts)[:16]))


def close(a, b, tol=6e-4):
    return abs(a - b) <= max(tol * max(abs(a), abs(b)), 1e-9)


used, matches = set(), []
for b in B:
    for j, l in enumerate(L):
        if j in used:
            continue
        if b["sym"] == l[0] and b["dir"] == l[1] and close(b["entry"], l[3]):
            matches.append((b, j, l))
            used.add(j)
            break

print(f"сетапов бэктеста 16-17.09: {len(B)} | живых записей: {len(L)}")
print(f"СОВПАЛО по (пара, направление, вход): {len(matches)}")
print(f"только в бэке: {len(B) - len(matches)} | только в живом: {len(L) - len(matches)}")
print()
print("=== СОВПАЛО: исход бэк vs статус живого ===")
agree = disagree = 0
for b, j, l in sorted(matches, key=lambda m: m[0]["trig"]):
    bt_out = str(b["outcome"])
    r = f"{b['r']:+.3f}" if isinstance(b["r"], float) else "—"
    live_st = l[4]
    m = {"tp": "closed_tp", "sl": "closed_sl", "time": "closed_time"}.get(bt_out)
    ok = (m == live_st) or (live_st.startswith("voided") and bt_out in ("sl", "tp", "time"))
    if m == live_st:
        agree += 1
    elif live_st.startswith("voided"):
        pass
    else:
        disagree += 1
    tag = "✓" if m == live_st else ("~" if live_st.startswith("voided") or str(live_st).startswith("cancel") else "✗ РАСХОЖДЕНИЕ")
    print(f"  {b['sym']:5s} {b['dir']:5s} триг {b['trig'][5:]} вход {b['entry']:<10} бэк {bt_out:5s} {r:>7s} | живой {live_st:<20} {tag}")
print(f"\nсовпало исходов: {agree} | расхождений: {disagree}")
print()
print("=== ТОЛЬКО В БЭКЕ (живой не взял вообще) ===")
for b in B:
    if not any(b is m[0] for m in matches):
        r = f"{b['r']:+.3f}" if isinstance(b["r"], float) else "—"
        print(f"  {b['sym']:5s} {b['dir']:5s} триг {b['trig'][5:]} htf {b['htf'][5:]} вход {b['entry']:<10} {b['outcome']} {r}")
print()
print("=== ТОЛЬКО В ЖИВОМ ===")
for j, l in enumerate(L):
    if j not in used:
        print(f"  {l[0]:5s} {l[1]:5s} htf {l[2][5:]} вход {l[3]:<10} {l[4]}")
