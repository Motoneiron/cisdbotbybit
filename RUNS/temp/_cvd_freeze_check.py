"""Freeze-check порога CVD-потока: подбор порога на 2020-23 (discovery), проверка на 2024-26 (OOS).

Правило: SKIP если of_1h_s < tau(direction); tau = квантиль discovery-периода.
Плюс универсальное правило of_1h_s >= 0.
"""
import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
SYMS = ["SOL", "BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP"]


def wr(g):
    d = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (d.outcome == "tp").mean() if len(d) else 0.0


def main() -> None:
    parts = []
    for s in SYMS:
        parts.append(pd.read_pickle(f"{BASE}/stream_{s}_cvd.pkl"))
    p = pd.concat(parts, ignore_index=True)
    p = p[p.of_1h_s.notna()].copy()
    disc = p[p.year <= 2023]
    oos = p[p.year >= 2024]
    print(f"disc n={len(disc)} | oos n={len(oos)} | всего={len(p)}", flush=True)
    for d in ("SHORT", "LONG"):
        dd = disc[disc["dir"] == d]
        oo = oos[oos["dir"] == d]
        print(f"\n======== {d} (disc n={len(dd)}, oos n={len(oo)}) ========", flush=True)
        print(f"  OOS baseline: WR={wr(oo):.1f} ΣR={oo.r_net.sum():.1f}", flush=True)
        for q in (0.10, 0.20, 0.25, 0.33, 0.50):
            tau = dd.of_1h_s.quantile(q)
            dk = dd[dd.of_1h_s >= tau]
            dc = dd[dd.of_1h_s < tau]
            ok = oo[oo.of_1h_s >= tau]
            oc = oo[oo.of_1h_s < tau]
            print(
                f"  tau=q{q:.2f}({tau:+.4f}): DISC kept n={len(dk)}/{len(dd)} ΣR={dk.r_net.sum():.0f} (cut ΣR={dc.r_net.sum():.0f}, cutWR={wr(dc):.0f}%)"
                f" || OOS kept n={len(ok)} ({100*len(ok)/max(1,len(oo)):.0f}%) WR={wr(ok):.1f} ΣR={ok.r_net.sum():.1f} (cut ΣR={oc.r_net.sum():.1f}, cutWR={wr(oc):.0f}%)",
                flush=True,
            )
    print("\n======== правило of_1h_s >= 0 (универсальное, без подбора) ========", flush=True)
    for y, g in p.groupby("year"):
        kept = g[g.of_1h_s >= 0]
        cut = g[g.of_1h_s < 0]
        print(
            f"  {int(y)}: keep n={len(kept)}/{len(g)} ({100*len(kept)/max(1,len(g)):.0f}%) WR={wr(kept):.1f} ΣR={kept.r_net.sum():.0f} | cut n={len(cut)} WR={wr(cut):.0f} ΣR={cut.r_net.sum():.0f}",
            flush=True,
        )


if __name__ == "__main__":
    main()
