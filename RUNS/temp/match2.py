"""Матчинг сделок live_filt (живой код) vs канон ABL_MSS_MAIN по паре-году: кто с кем совпал, кто лишний, чей исход расходится."""
import pickle
import sys

import numpy as np
import pandas as pd

CORE6 = ["SOL", "DOGE", "KAS", "ADA", "LINK", "LTC"]


def live_kept(sym, year):
    rows = pickle.load(open(f"live_filt/{sym}_{year}.pkl", "rb"))
    out = []
    for r in rows:
        sw, vol, soft = r.get("sw"), r.get("vol"), r.get("soft")
        if sw is None or not np.isfinite(sw) or sw < 0.40:
            continue
        if not soft and (vol is None or not np.isfinite(vol) or vol > 2.5):
            continue
        out.append(r)
    return out


def canon(sym, year):
    rows = pickle.load(open(f"tf7_abl/ABL_MSS_MAIN_{sym}_{year}.pkl", "rb"))
    out = []
    for r in rows:
        r = dict(r)
        r["r"] = r["r_net_mexc"]
        out.append(r)
    return out


def match_pair(sym, year, tol_min=7):
    L = live_kept(sym, year)
    C = canon(sym, year)
    if not L or not C:
        return None
    Ld = pd.DataFrame(L)
    Ld["ts"] = pd.to_datetime(Ld["scan"])
    Cd = pd.DataFrame(C)
    Cd["ts"] = pd.to_datetime(Cd["created_ts"])
    used = set()
    pairs = []
    for _, c in Cd.sort_values("ts").iterrows():
        cand = Ld[(Ld.direction == c.direction) & ~Ld.index.isin(used)]
        if len(cand) == 0:
            pairs.append((c, None))
            continue
        d = (cand.ts - c.ts).abs()
        i = d.idxmin()
        if d.loc[i] <= pd.Timedelta(minutes=tol_min):
            used.add(i)
            pairs.append((c, Ld.loc[i]))
        else:
            pairs.append((c, None))
    live_only = Ld[~Ld.index.isin(used)]
    return pairs, live_only


def run(sym, year):
    res = match_pair(sym, year)
    if res is None:
        print(f"{sym} {year}: нет данных")
        return
    pairs, live_only = res
    both = [(c, l) for c, l in pairs if l is not None]
    no_live = [c for c, l in pairs if l is None]
    conf = {}
    for c, l in both:
        key = (str(c.outcome), str(l.outcome))
        conf[key] = conf.get(key, 0) + 1
    same = sum(v for k, v in conf.items() if k[0] == k[1])
    print(f"== {sym} {year}: canon={len(pairs)} live_kept={len(live_only) + len(both)}")
    print(f"   матч: {len(both)} (совпал исход {same}), канон-без-пары {len(no_live)}, live-без-пары {len(live_only)}")
    if both:
        rc = np.array([l and 0 for _ in []] or [float(c['r']) for c, l in both])
        rl = np.array([float(l['r']) for c, l in both])
        print(f"   avg r матченных: canon={rc.mean():+.4f} live={rl.mean():+.4f}")
    for k, v in sorted(conf.items(), key=lambda x: -x[1]):
        if k[0] != k[1]:
            print(f"     расхождение {k[0]}->{k[1]}: {v}")
    if no_live:
        rr = np.array([float(c['r']) for c in no_live])
        print(f"   канон-без-пары: avg={rr.mean():+.4f} sum={rr.sum():+.0f}")
    if len(live_only):
        rr = np.array([float(c['r']) for c in live_only])
        print(f"   live-без-пары:  avg={rr.mean():+.4f} sum={rr.sum():+.0f}")
    # примеры расхождений
    shown = 0
    for c, l in both:
        if str(c.outcome) != str(l.outcome) and shown < 6:
            print(
                f"     ex: {c.direction:5s} ts(h)={c.ts} canon={c.outcome:4s}(r={c['r']:+.2f}) "
                f"live={l.outcome:4s}(r={l['r']:+.2f}) entry={c.entry_px} stop={c.stop} tp={c.tp}"
            )
            shown += 1


if __name__ == "__main__":
    years = [int(a) for a in sys.argv[1:]] or [2024]
    for y in years:
        for s in CORE6:
            run(s, y)
        print()
