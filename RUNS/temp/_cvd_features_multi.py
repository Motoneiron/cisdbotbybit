"""CVD-фичи (v1) для списка пар + сводные таблицы (пул, внутри 18-KEEP, каскад).

Использование: python _cvd_features_multi.py SOL BTC ETH
Выход: stream_<SYM>_cvd.pkl по каждой паре + печать сводных таблиц.
"""
import sys

import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"


def wr(p):
    d = p[p.outcome.isin(["tp", "sl"])]
    return 100.0 * (d.outcome == "tp").mean() if len(d) else 0.0


def qtab(g, col, tag=""):
    gg = g[g[col].notna()].copy()
    if len(gg) < 60:
        print(f"   {tag} n<60, скип", flush=True)
        return
    gg["q"] = pd.qcut(gg[col].rank(method="first"), 5, labels=[1, 2, 3, 4, 5])
    parts = []
    for q, s in gg.groupby("q", observed=True):
        parts.append(f"Q{q}: {wr(s):4.0f}%/{s.r_net.mean():+.3f}")
    print(f"   {tag}n={len(gg)}  " + "  ".join(parts), flush=True)


def feats_for(sym: str, kp: pd.DataFrame, ep: pd.DataFrame, stream_name: str):
    df = pd.read_pickle(BASE + "/" + stream_name)
    sub = df[df.sym == sym].copy()
    m = pd.read_pickle(BASE + f"/cvd/{sym}USDT_minute.pkl").sort_values("ts_ms")
    ts = m.ts_ms.to_numpy(np.int64)
    vol = (m.buy + m.sell).to_numpy(float)
    dlt = m.delta.to_numpy(float)
    ntr = m.n.to_numpy(float)
    cd = np.concatenate([[0.0], np.cumsum(dlt)])
    cv = np.concatenate([[0.0], np.cumsum(vol)])
    cn = np.concatenate([[0.0], np.cumsum(ntr)])

    def wsum(c, t0, t1):
        i0 = np.searchsorted(ts, int(t0), "left")
        i1 = np.searchsorted(ts, int(t1), "left")
        return float(c[i1] - c[i0])

    feats = []
    for r in sub.itertuples():
        ms0 = int(pd.Timestamp(r.decision_at).timestamp() * 1000)
        try:
            trig = int(pd.Timestamp(str(r.trigger_bar_time)).timestamp() * 1000)
        except Exception:
            trig = None
        tfm = 5 if r.prof == "tf7" else 30
        row = {"of_trig": np.nan, "of_1h": np.nan, "of_4h": np.nan, "act": np.nan}
        if trig is not None:
            d_t, v_t = wsum(cd, trig, trig + tfm * 60000), wsum(cv, trig, trig + tfm * 60000)
            n_t = wsum(cn, trig, trig + tfm * 60000)
            if v_t > 0:
                row["of_trig"] = d_t / v_t
            n_prev = wsum(cn, ms0 - 12 * 3600_000, ms0)
            if n_prev > 0:
                row["act"] = (n_t / tfm) / (n_prev / 720.0)
        d1, v1 = wsum(cd, ms0 - 3600_000, ms0), wsum(cv, ms0 - 3600_000, ms0)
        d4, v4 = wsum(cd, ms0 - 4 * 3600_000, ms0), wsum(cv, ms0 - 4 * 3600_000, ms0)
        if v1 > 0:
            row["of_1h"] = d1 / v1
        if v4 > 0:
            row["of_4h"] = d4 / v4
        feats.append(row)
    ff = pd.DataFrame(feats, index=sub.index)
    sgn = np.where(sub["dir"] == "SHORT", -1.0, 1.0)
    for c in ("of_trig", "of_1h", "of_4h"):
        ff[c + "_s"] = ff[c] * sgn
    out = pd.concat([sub, ff], axis=1)
    out["keep18"] = out["hash"].map(kp)
    out = out.merge(ep, on="hash", how="left")
    out.to_pickle(BASE + f"/stream_{sym}_cvd.pkl")
    print(f"[{sym}] n={len(out)} notna(of_1h)={out.of_1h.notna().sum()}", flush=True)
    return out


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("syms", nargs="+")
    ap.add_argument("--stream", default="stream_off_v1_v2.pkl")
    ap.add_argument("--knn", default="knn18_full.pkl")
    ap.add_argument("--el", default="stream_off_v1_v2_el.pkl")
    a = ap.parse_args()
    syms = a.syms
    knn = pd.read_pickle(BASE + "/" + a.knn)
    kp = knn.drop_duplicates("hash").set_index("hash")["keep"]
    ep = pd.read_pickle(BASE + "/" + a.el)[["hash", "zz_frac", "zz_last_dir"]].drop_duplicates("hash")
    parts = []
    for sym in syms:
        try:
            parts.append(feats_for(sym, kp, ep, a.stream))
        except Exception as e:
            print(f"[{sym}] FAIL: {e!r}", flush=True)
    pool = pd.concat(parts, ignore_index=True)
    pool.to_pickle(BASE + "/stream_multi_cvd.pkl")
    print(f"\n========== ПУЛ {syms} n={len(pool)} ==========", flush=True)
    for c in ("of_1h_s", "of_4h_s", "of_trig_s", "act"):
        cc = pool[[c, "r_net"]].corr().iloc[0, 1]
        print(f"corr({c}, r_net) = {cc:.3f}", flush=True)
    for d in ("SHORT", "LONG"):
        g = pool[pool["dir"] == d]
        print(f"\n--- {d} (n={len(g)}) ---", flush=True)
        for c in ("of_1h_s", "of_4h_s"):
            qtab(g, c, f"{c} ")
    print("\n--- внутри 18-KEEP ---", flush=True)
    for d in ("SHORT", "LONG"):
        g = pool[(pool.keep18 == True) & (pool["dir"] == d)]
        for c in ("of_1h_s", "of_4h_s"):
            qtab(g, c, f"keep {d} {c} ")
    print("\n--- каскад (18-KEEP & of_1h_s>=медианы | по направлениям) ---", flush=True)
    for d in ("SHORT", "LONG"):
        g = pool[pool["dir"] == d]
        med = g.of_1h_s.median()
        casc = g[(g.keep18 == True) & (g.of_1h_s >= med)]
        rest = g[~((g.keep18 == True) & (g.of_1h_s >= med))]
        print(f"  {d}: каскад n={len(casc)} WR={wr(casc):.1f} ΣR={casc.r_net.sum():.1f} | остальное n={len(rest)} WR={wr(rest):.1f} ΣR={rest.r_net.sum():.1f}", flush=True)
    print("\n--- top-квадрант: keep18 & of_1h_s Q4-Q5 & !zzlow ---", flush=True)
    short = pool[(pool["dir"] == "SHORT")]
    thr = short.of_1h_s.quantile(0.6)
    zl = ((pool.zz_last_dir == 1) & (pool["dir"] == "LONG")) | ((pool.zz_last_dir == -1) & (pool["dir"] == "SHORT"))
    zlow = zl & (pool.zz_frac < 0.236)
    best = pool[(pool.keep18 == True) & (pool.of_1h_s >= thr) & ~zlow]
    print(f"  n={len(best)} WR={wr(best):.1f} ΣR={best.r_net.sum():.1f} AvgR={best.r_net.mean():.3f}", flush=True)


if __name__ == "__main__":
    main()
