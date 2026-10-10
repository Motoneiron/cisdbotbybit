"""Скученность по СИГНАЛАМ, а не по заполненным сделкам — чистая причинность.

В crowding.py «позиция другого профиля открыта» определялась по сделкам, то есть
по факту заполнения лимитки, а заполнение может случиться уже после нашего якоря
(лимитка живёт до часа). Утечка небольшая, но она есть.

Здесь скученность считается по факту существования СИГНАЛА: сигнал известен на
своём якоре (close конфирм-бара + первый 5m-скан), и если этот якорь не позже
нашего, информация доступна. Именно так это и работает в живом боте: он видит
свои сигналы по всем профилям в реальном времени, независимо от заполнения.

  crowd_sig = (профилей с сигналом в ту же сторону за окно удержания)
            − (профилей с сигналом в противоположную)

Запуск: python crowding_signals.py
"""
from __future__ import annotations

import pickle

import numpy as np
import pandas as pd

from cross_tf import PROF, TPG, signal_anchors
from cross_tf2 import HOLD_H


def main() -> None:
    tabs = pickle.load(open(f"{TPG}/cross_tf_crowd.pkl", "rb"))
    idx = {p: signal_anchors(p) for p in PROF}
    print("сигналов в индексе:",
          {p: int(sum(len(v) for v in idx[p].values())) for p in PROF}, "\n")

    out = {}
    for target, d in tabs.items():
        d = d.copy()
        same = np.zeros(len(d), dtype=int)
        opp = np.zeros(len(d), dtype=int)
        for src in PROF:
            if src == target:
                continue
            hold = np.timedelta64(HOLD_H[src], "h")
            for i, (sym, dr, a) in enumerate(zip(d.sym, d.dir, d.anchor)):
                a64 = np.datetime64(a)
                o = "SHORT" if dr == "LONG" else "LONG"
                for side, dst in ((dr, same), (o, opp)):
                    arr = idx[src].get((sym, side))
                    if arr is None:
                        continue
                    lo = np.searchsorted(arr, a64 - hold, "right")
                    hi = np.searchsorted(arr, a64, "right")
                    if hi > lo:
                        dst[i] += 1
        d["cs"] = same - opp
        out[target] = d

    print("net R по скученности сигналов\n")
    print("   crowd_sig " + "".join(p.rjust(24) for p in PROF))
    for c in (-3, -2, -1, 0, 1, 2, 3):
        line = f"   {c:+d}        "
        for p in PROF:
            g = out[p][out[p].cs == c]
            if len(g) < 100:
                line += f"n={len(g)}".rjust(24)
                continue
            se = g.net.std() / np.sqrt(len(g))
            line += f"{g.net.mean():+.4f}±{se:.3f} n={len(g):<5d}".rjust(24)
        print(line)

    print("\nразница net(crowd_sig≤0) − net(crowd_sig>0) по годам\n")
    print("   профиль " + "".join(str(y).rjust(10) for y in range(2020, 2027)) + "   плюс-лет")
    for p in PROF:
        d, line, pos = out[p], f"   {p:8s}", 0
        for y in range(2020, 2027):
            g = d[d.year == y]
            a_, z_ = g[g.cs <= 0], g[g.cs > 0]
            if len(a_) < 50 or len(z_) < 50:
                line += "—".rjust(10)
                continue
            diff = a_.net.mean() - z_.net.mean()
            pos += diff > 0
            line += f"{diff:+.4f}".rjust(10)
        print(line + f"   {pos}/7")

    print("\nсовокупно и вневыборочно\n")
    for p in PROF:
        d = tabs[p]
        s = out[p]
        a_, z_ = s[s.cs <= 0], s[s.cs > 0]
        diff = a_.net.mean() - z_.net.mean()
        se = np.sqrt(a_.net.var() / len(a_) + z_.net.var() / len(z_))
        ins, oos = s[s.year <= 2023], s[s.year >= 2024]
        print(f"  {p}: crowd_sig≤0 n={len(a_):5d} net={a_.net.mean():+.4f} | "
              f">0 n={len(z_):5d} net={z_.net.mean():+.4f} | разница {diff:+.4f} "
              f"(t={diff/se:+.1f})")
        for lbl, f in (("SHORT & стоп≥2.5% & crowd_sig≤0",
                        lambda x: (x.cs <= 0) & (x.dir == "SHORT") & (x.stop_pct >= 2.5)),):
            gi, go = ins[f(ins)], oos[f(oos)]
            if len(gi) >= 100 and len(go) >= 100:
                g = s[f(s)]
                pos = sum(1 for y in sorted(g.year.unique())
                          if g[g.year == y].net.mean() > 0)
                print(f"      {lbl}: всё n={len(g):4d} net={g.net.mean():+.4f}"
                      f"±{g.net.std()/np.sqrt(len(g)):.4f} лет={pos}/7 | "
                      f"in={gi.net.mean():+.4f} out={go.net.mean():+.4f}")
    pickle.dump(out, open(f"{TPG}/cross_tf_crowd_sig.pkl", "wb"))


if __name__ == "__main__":
    main()
