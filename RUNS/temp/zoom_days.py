"""Точные записи канона и live за конкретные дни (SOL 2024)."""
import pickle

import pandas as pd

CAN = pickle.load(open("tf7_abl/ABL_MSS_MAIN_SOL_2024.pkl", "rb"))
LIV = pickle.load(open("live_filt/SOL_2024.pkl", "rb"))

print("=== КАНОН SOL 2024: 01-01..01-10 (все записи) ===")
for r in CAN:
    d = str(r["created_ts"])[:10]
    if "2024-01-01" <= d <= "2024-01-10":
        print(f"  created={r['created_ts']} entry={r['entry_ts']} {r['direction']:5s} {r['outcome']:4s} entry_px={r.get('entry_px')} stop={r.get('stop')} tp={r.get('tp')} bars=({r.get('created_bar')},{r.get('entry_bar')},{r.get('exit_bar')}) hash={str(r.get('hash'))[:12]}")

print()
print("=== LIVE SOL 2024: 01-01..01-10 (все записи, без фильтра) ===")
for r in LIV:
    d = str(r["scan"])[:10]
    if "2024-01-01" <= d <= "2024-01-10":
        print(f"  scan={r['scan']} {r['direction']:5s} {r['outcome']:4s} r={r['r']:+.2f} sw={r.get('sw')} vol={r.get('vol')} touches={r.get('touches')}")

print()
print("=== CANON only fields of a record ===")
print(sorted(CAN[0].keys()))
print()
print("=== также 01-14/01-18/01-23 канон ===")
for r in CAN:
    d = str(r["created_ts"])[:10]
    if d in ("2024-01-14", "2024-01-18", "2024-01-23"):
        print(f"  created={r['created_ts']} entry={r['entry_ts']} exit={r['exit_ts']} {r['direction']:5s} {r['outcome']:4s} entry_px={r.get('entry_px')} bars=({r.get('created_bar')},{r.get('entry_bar')},{r.get('exit_bar')}) hash={str(r.get('hash'))[:12]}")
