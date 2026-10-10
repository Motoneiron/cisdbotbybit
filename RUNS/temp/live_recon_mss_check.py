"""Сводка сверки MSS_MAIN на живом окне: согласие исходов, суммы R."""
import json
import pickle

import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp/live_recon"
live = pd.DataFrame(json.load(open(BASE + "/live_sol_tf7_trades.json", encoding="utf-8")))
live["tkey"] = live.direction + "|" + live.signal_time.astype(str).str[:13]

res = pickle.load(open(BASE + "/recon_MSS_MAIN.pkl", "rb"))
tr = res["trades"] or []
bt = pd.DataFrame([{**t, "r_net_mexc": t.get("r_net")} for t in tr])
bt["hkey"] = bt.direction + "|" + bt.htf_time.astype(str).str[:13]

def o_norm(v):
    v = str(v)
    return "tp" if "tp" in v else ("sl" if "sl" in v else "other")

def fr(k, o, s, m, t):
    if not s or s <= 0:
        return 0.0
    e = m if str(k).upper() == "LIMIT" else t
    x = m if o == "tp" else t
    return (e + x) / s

bt["r_byb"] = bt.r_net_mexc + [
    fr(k, o, s, 0.0006, 0.0008) - fr(k, o, s, 0.00036, 0.0010)
    for k, o, s in zip(bt.entry_kind, bt.outcome, bt.sp)
]

bh = set(bt.hash.astype(str))
bk = set(bt.hkey)
live["m_hash"] = live.sig_hash.astype(str).isin(bh)
live["m_key"] = live.tkey.isin(bk)
live["matched"] = live.m_hash | live.m_key

bt_h = bt.drop_duplicates("hash").copy()
bt_h["hash"] = bt_h["hash"].astype(str)
bt_h = bt_h.set_index("hash")
bt_k = bt.drop_duplicates("hkey").set_index("hkey")

ag = dis = 0
ex = []
for _, t in live[live.matched].iterrows():
    cand = None
    if str(t.sig_hash) in bt_h.index:
        cand = bt_h.loc[str(t.sig_hash)]
    elif t.tkey in bt_k.index:
        cand = bt_k.loc[t.tkey]
    if cand is None:
        continue
    lo, bo = o_norm(t.exit_reason), o_norm(cand["outcome"])
    if lo == bo:
        ag += 1
    else:
        dis += 1
        if len(ex) < 8:
            ex.append(f"    {t.get('id')} live={lo} bt={bo} sig={t.get('signal_time')} "
                      f"liveR={t.get('net_r'):+.2f} btR={float(cand.get('r_net')):+.2f}")

print("matched:", int(live.matched.sum()), f"| согласие исходов: {ag}/{ag+dis} = {100*ag/(ag+dis):.0f}%" if ag + dis else "")
print(f"бэк: n={len(bt)} | MEXC ΣR {bt.r_net_mexc.sum():+.1f} (avg {bt.r_net_mexc.mean():+.3f}) | "
      f"Bybit ΣR {bt.r_byb.sum():+.1f} (avg {bt.r_byb.mean():+.3f})")
print("по направлению: ", {d: round(g.r_net_mexc.sum(), 1) for d, g in bt.groupby("direction")})
for e in ex:
    print(e)
