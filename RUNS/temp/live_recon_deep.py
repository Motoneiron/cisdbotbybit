"""Глубже по live-сверке: суммы R бэка, сверка исходов, разрезы. v2."""
import json
import pickle

import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp/live_recon"
live = pd.DataFrame(json.load(open(BASE + "/live_sol_tf7_trades.json", encoding="utf-8")))
live["tkey"] = live.direction + "|" + live.signal_time.astype(str).str[:13]
live["month"] = live.entry_time.astype(str).str[:7]

def load(cfg):
    res = pickle.load(open(f"{BASE}/recon_{cfg}.pkl", "rb"))
    tr = res["trades"] or []
    bt = pd.DataFrame([{**t, "r_net_mexc": t.get("r_net")} for t in tr])
    bt["hkey"] = bt.direction + "|" + bt.htf_time.astype(str).str[:13]
    return bt

def o_norm(v):
    v = str(v)
    if "tp" in v:
        return "tp"
    if "sl" in v:
        return "sl"
    return "other"

for cfg in ("LIVE_EMUL", "CORE_C5"):
    bt = load(cfg)
    n = len(bt)
    print(f"\n=== {cfg}: n={n} | SumR={bt.r_net_mexc.sum():+.1f} | avg={bt.r_net_mexc.mean():+.3f} | "
          f"WR_tp={100*(bt.outcome=='tp').mean():.0f}% | kinds={bt.entry_kind.value_counts().to_dict()}")
    bh = set(bt.hash.astype(str))
    bkeys = set(bt.hkey)
    live["m_hash"] = live.sig_hash.astype(str).isin(bh)
    live["m_key"] = live.tkey.isin(bkeys)
    live["matched"] = live.m_hash | live.m_key
    print("  найдено:", int(live.matched.sum()), "| по видам:")
    print(live.groupby(["entry_kind", "matched"]).size().unstack(fill_value=0).to_string())

    # сверка исходов среди matched
    bt_h = bt.drop_duplicates("hash").set_index(bt.drop_duplicates("hash").hash.astype(str))
    bt_k = bt.drop_duplicates("hkey").set_index("hkey")
    agree = dis = 0
    ex = []
    bt_r_matched = 0.0
    for _, t in live[live.matched].iterrows():
        cand = None
        sh = str(t.get("sig_hash"))
        if sh in bt_h.index:
            cand = bt_h.loc[sh]
        elif t.tkey in bt_k.index:
            cand = bt_k.loc[t.tkey]
        if cand is None:
            continue
        bt_r_matched += float(cand.get("r_net"))
        lo, bo = o_norm(t.get("exit_reason")), o_norm(cand.get("outcome"))
        if lo == bo:
            agree += 1
        else:
            dis += 1
            if len(ex) < 10:
                ex.append(f"    {t.get('id')} {t.get('direction')} live={lo} bt={bo} sig={t.get('signal_time')} "
                          f"liveR={t.get('net_r'):+.2f} btR={float(cand.get('r_net')):+.2f}")
    tot = agree + dis
    print(f"  совпадение исходов среди matched: {agree}/{tot} = {100*agree/tot:.0f}%" if tot else "  нет матчей")
    print(f"  (SumR бэка по matched ~{bt_r_matched:+.1f}; живых по ним -=*-)")
    for e in ex:
        print(e)

bt = load("LIVE_EMUL")
lkeys = set(live.tkey)
lh = set(live.sig_hash.astype(str))
extra = bt[~(bt.hash.astype(str).isin(lh)) & ~(bt.hkey.isin(lkeys))]
print(f"\nЛИШНИЕ (LIVE_EMUL): {len(extra)} | SumR={extra.r_net_mexc.sum():+.1f} | WR={100*(extra.outcome=='tp').mean():.0f}%")
print(extra.head(12)[["direction", "entry_kind", "htf_time", "outcome", "r_net_mexc"]].to_string())
