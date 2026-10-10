"""Пересчёт матчинга: ЖИВЫЕ vs (наши сигналы + трейды)."""
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

m_hash = m_sig = m_tr = m_none = 0
detail = []
for v in live:
    pair, dr, ts = v.get("sym_guess"), v.get("direction"), v.get("htf_time")
    h = str(v.get("sig_hash"))
    kk = key(pair, dr, ts)
    if h in sig_hash or h in tr_hash:
        m_hash += 1
        detail.append(f"  {v['id']} {pair} {dr} {ts} -> HASH")
    elif kk in tr_keys:
        m_tr += 1
        t = tr_keys[kk][0]
        lo, bo = o_norm(v.get("status")), o_norm(t.get("outcome"))
        detail.append(f"  {v['id']} {pair} {dr} {ts} -> трейд (live={lo} bt={bo})")
    elif kk in sig_keys:
        m_sig += 1
        s = sig_keys[kk][0]
        detail.append(f"  {v['id']} {pair} {dr} {ts} -> сигнал (trade не открылся), entry={s.get('entry')}")
    else:
        m_none += 1
        detail.append(f"  {v['id']} {pair} {dr} {ts} -> НЕТ")

mm = m_hash + m_sig + m_tr
print(f"живых {len(live)} | match: hash={m_hash} трейд={m_tr} сигнал={m_sig} -> {mm}/{len(live)} = {100*mm/len(live):.0f}% | нет={m_none}")
print()
print("\n".join(detail))
