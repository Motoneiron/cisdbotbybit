"""Три варианта правила b9d3d3f на потоке tf8 (filters_off_full, 2020-26).

V1 full    — как в коде: (а) кандидат «не берём», если живой глубже; (б) старый кандидат
             снят + висящая лимитка отменена (сделка теряется, если ещё не вошла).
V2 nocross — только (а) + отмена лимитки при обновлении В СВОЁМ окне; кросс-оконного снятия нет.
V3 samewin — только отмена лимитки при обновлении в своём окне (классический пересвип).

База: сигналов 29066, сделок 26015, ΣR +1642.5.
"""
import glob
import pickle
import sys
from collections import defaultdict

import pandas as pd

MODE = sys.argv[1] if len(sys.argv) > 1 else "full"
PAT = "D:/PYTHON/CISDBOT/RUNS/filters_off_full/*tf8*.pkl"
EPS = 1e-8


def deeper(direction, a, b):
    return a < b - EPS if direction == "LONG" else a > b + EPS


sigs, trades = [], {}
for f in sorted(glob.glob(PAT)):
    c = pickle.load(open(f, "rb"))
    sym = c.get("symbol")
    for s in c.get("signals") or []:
        sigs.append({"sym": sym, "dir": s.get("direction"), "htf": str(s.get("htf_time")),
                     "sweep": float(s.get("htf_sweep_level") or 0),
                     "ext": float(s.get("trigger_extreme") or 0),
                     "scan": s.get("scan_bar"), "hash": str(s.get("hash"))})
    for t in c.get("trades") or []:
        trades[str(t.get("hash"))] = {"r": float(t.get("r_net") or 0),
                                      "entry_bar": t.get("entry_bar")}

df = pd.DataFrame(sigs).sort_values(["sym", "scan"]).reset_index(drop=True)
base_r = sum(t["r"] for t in trades.values())

suppressed = removed = kept = 0
removed_r = 0.0
removed_rows = []
for sym, g in df.groupby("sym"):
    cands, win_order = {}, []
    for r in g.itertuples():
        key = (r.dir, r.htf)
        if r.htf not in win_order:
            win_order.append(r.htf)
        keep_windows = set(win_order[-2:])
        cands = {k: v for k, v in cands.items() if k[1] in keep_windows}

        sibs = {k: v for k, v in cands.items() if k[0] == r.dir and k != key}
        beats_in = {k: (deeper(r.dir, r.ext, v["ext"]) or deeper(r.dir, r.sweep, v["sweep"]))
                    for k, v in sibs.items()}
        beats_sib = {k: (deeper(r.dir, v["ext"], r.ext) or deeper(r.dir, v["sweep"], r.sweep))
                     for k, v in sibs.items()}
        do_suppress = MODE in ("full", "nocross")
        do_cross = MODE == "full"

        if do_suppress and any(beats_sib[k] and not beats_in[k] for k in sibs):
            suppressed += 1
            t = trades.get(r.hash)
            if t:
                removed += 1
                removed_r += t["r"]
                removed_rows.append((sym, r.dir, r.htf, r.sweep, t["r"], "не берём (живой глубже)"))
            continue

        if do_cross:
            for k, v in sibs.items():
                if beats_in[k] and not beats_sib[k]:
                    t = trades.get(v["hash"])
                    if t and t["entry_bar"] is not None and r.scan is not None and \
                            float(t["entry_bar"]) <= float(r.scan):
                        kept += 1
                    elif t:
                        removed += 1
                        removed_r += t["r"]
                        removed_rows.append((sym, r.dir, v["htf"], v["sweep"], t["r"],
                                             f"снят пересвипом → {r.sweep}"))
                    cands.pop(k, None)

        cur = cands.get(key)
        if cur is None:
            cands[key] = dict(sweep=r.sweep, ext=r.ext, htf=r.htf, hash=r.hash)
        else:
            if deeper(r.dir, r.ext, cur["ext"]) or deeper(r.dir, r.sweep, cur["sweep"]):
                t = trades.get(cur["hash"])
                if t and t["entry_bar"] is not None and r.scan is not None and \
                        float(t["entry_bar"]) <= float(r.scan):
                    kept += 1
                elif t:
                    removed += 1
                    removed_r += t["r"]
                    removed_rows.append((sym, r.dir, cur["htf"], cur["sweep"], t["r"],
                                         "обновление в своём окне (лимитка снята)"))
                cands[key] = dict(sweep=r.sweep, ext=r.ext, htf=r.htf, hash=r.hash)

print(f"MODE={MODE}")
print(f"  сигналов «не берём»: {suppressed}")
print(f"  сделок снято: {removed} | их ΣR {removed_r:+.1f} | ср.R {(removed_r / removed if removed else 0):+.3f}")
print(f"  сохранено (уже в позиции): {kept}")
print(f"  ΣR потока: {base_r:+.1f} → {base_r - removed_r:+.1f}  ({100 * (base_r - removed_r) / base_r:.1f}% от базы)")
