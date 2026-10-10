"""Кросс-чек: 'лишние' бэк-сделки (LIVE_EMUL) vs живые signal_skipped.

Вопросы:
1) совпадают ли 'лишние' бэк-сделки со скипами живого?
2) что дал бы бэк по всем скип-сигналам (живой их отклонил своими фильтрами)?
"""
import glob
import json
import pickle
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

SRC = Path(r"D:/PYTHON/CISDBOT/.tmp_live_compare/audit_20260822")
BASE = Path(r"D:/PYTHON/cisdbotbybit/RUNS/temp/live_recon")

# 1) скипы живого (SOL tf7)
skips = []
for f in sorted(SRC.glob("trades_2026-*.jsonl")):
    for line in f.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("event") != "signal_skipped" or r.get("mode") != "live":
            continue
        px = float(r.get("signal_entry") or r.get("cisd_level") or 0)
        if not (0 < px < 1000):
            continue
        r["_k"] = f"{r.get('direction')}|{str(r.get('signal_time'))[:13]}"
        skips.append(r)
print("скипов SOL:", len(skips))
for k, v in Counter(str(r.get("skip_reason") or "")[:45] for r in skips).most_common(6):
    print(f"   {v:>4}  {k}")

sk_keys = {r["_k"] for r in skips}

def k_neigh(direction, tstr):
    try:
        t = datetime.fromisoformat(str(tstr)[:19])
    except Exception:
        return set()
    return {f"{direction}|{(t + timedelta(hours=dh)).strftime('%Y-%m-%d %H')}" for dh in (-1, 0, 1)}

# 2) лишние бэка
res = pickle.load(open(BASE / "recon_LIVE_EMUL.pkl", "rb"))
tr = res["trades"] or []
live = pd.DataFrame(json.load(open(BASE / "live_sol_tf7_trades.json", encoding="utf-8")))
lh = set(live.sig_hash.astype(str))
lk = set(live.direction + "|" + live.signal_time.astype(str).str[:13])
bt = pd.DataFrame([{**t, "r_net_mexc": t.get("r_net")} for t in tr])
bt["hkey"] = bt.direction + "|" + bt.htf_time.astype(str).str[:13]
extra = bt[~(bt.hash.astype(str).isin(lh)) & ~(bt.hkey.isin(lk))]
print(f"\nлишних бэк-сделок: {len(extra)}")

expl, unexp = [], []
for _, t in extra.iterrows():
    (expl if (k_neigh(t["direction"], t["htf_time"]) & sk_keys) else unexp).append(t)
e = pd.DataFrame(expl)
u = pd.DataFrame(unexp)
print(f"объяснены скипами живого: {len(e)} | SumR={e.r_net_mexc.sum() if len(e) else 0:+.1f} | WR={100*(e.outcome=='tp').mean() if len(e) else 0:.0f}%")
print(f"НЕ объяснены:              {len(u)} | SumR={u.r_net_mexc.sum() if len(u) else 0:+.1f} | WR={100*(u.outcome=='tp').mean() if len(u) else 0:.0f}%")

# 3) все скипы живого: что с ними в бэке?
hits = []   # (bt_row, reason)
miss = 0
for r in skips:
    ks = k_neigh(r["direction"], r["signal_time"])
    cand = bt[bt.hkey.isin(ks)]
    if len(cand):
        hits.append((cand.iloc[0], str(r.get("skip_reason") or "")))
    else:
        miss += 1
h = pd.DataFrame([x[0] for x in hits])
print(f"\nскипы живого: {len(skips)} | есть сделка в бэке: {len(hits)} | нет в бэке: {miss}")
if len(h):
    print(f"бэк по скип-сигналам: SumR={h.r_net_mexc.sum():+.1f} | avg={h.r_net_mexc.mean():+.3f} | WR={100*(h.outcome=='tp').mean():.0f}%")
    for k in ("KC mid_against", "Slope EMA1", "Slope EMA2", "HTF"):
        s2 = [row for row, rr in hits if k in rr]
        if s2:
            dd = pd.DataFrame(s2)
            print(f"   {k}: n={len(dd)} SumR={dd.r_net_mexc.sum():+.1f} WR={100*(dd.outcome=='tp').mean():.0f}%")
