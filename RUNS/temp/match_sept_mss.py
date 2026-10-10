"""Сопоставление: сентябрьские живые tf7-сделки (26) vs наш MSS-поток (61/121)."""
import json
import pickle
from collections import Counter
from pathlib import Path

T = Path(r"D:/PYTHON/cisdbotbybit/RUNS/temp")
live = json.load(open(T / "live_recon/sept_tf7_trades.json", encoding="utf-8"))
rec = pickle.load(open(T / "live_recon/sept_recon_mss.pkl", "rb"))
tr, sg = rec["trades"], rec["signals"]
print(f"живых: {len(live)} | наш поток: trades={len(tr)} signals={len(sg)}")

def key(pair, dr, ts):
    return f"{pair}|{dr}|{str(ts)[:13]}"

bt_by_key = {}
for t in tr:
    bt_by_key.setdefault(key(t.get("_pair"), t.get("direction"), t.get("htf_time")), []).append(t)
bt_by_hash = {}
for t in tr:
    bt_by_hash.setdefault(str(t.get("hash")), []).append(t)

def o_norm(v):
    v = str(v)
    return "tp" if "tp" in v else ("sl" if "sl" in v else "other")

m_hash = m_key = m_none = 0
agree = dis = 0
unmatched = []
examples = []
used = set()
for v in live:
    pair, dr, ts = v.get("sym_guess"), v.get("direction"), v.get("htf_time")
    h = str(v.get("sig_hash"))
    cand, tag = None, None
    if bt_by_hash.get(h):
        cand, tag = bt_by_hash[h][0], "hash"
        m_hash += 1
    else:
        kk = key(pair, dr, ts)
        if kk in bt_by_key:
            cand, tag = bt_by_key[kk][0], "key"
            m_key += 1
    if cand is None:
        m_none += 1
        unmatched.append(f"   {v['id']} {pair} {dr} htf={ts} px={v['entry_price']} {v.get('status')}")
        continue
    used.add(id(cand))
    lo, bo = o_norm(v.get("status")), o_norm(cand.get("outcome"))
    if lo == bo:
        agree += 1
    else:
        dis += 1
        if len(examples) < 12:
            examples.append(f"   {v['id']} {pair} {dr} htf={ts} live={lo} bt={bo} livePx={v['entry_price']} btEntry={cand.get('entry_px')}")

mm = m_hash + m_key
print(f"\nматч: hash={m_hash} key={m_key} -> {mm}/{len(live)} = {100*mm/len(live):.0f}%")
print(f"согласие исходов: {agree}/{agree+dis} = {100*agree/(agree+dis) if agree+dis else 0:.0f}%")
print(f"не найдено: {m_none}")
print("\nне найденные:")
print("\n".join(unmatched) or "   (нет)")
print("\nрасхождения исходов:")
print("\n".join(examples) or "   (нет)")
extra = [t for t in tr if id(t) not in used]
print(f"\nнаши 'лишние' (нет в живых): {len(extra)}")
print("   исходы лишних:", dict(Counter(str(t.get("outcome")) for t in extra)))
