"""CVD-фичи v1 к SOL-потоку: дельта-имбалансы (order-flow) около решения/триггера.

of_trig / of_1h / of_4h — Σdelta/Σvol в окнах (доля агрессивных покупок минус продаж),
act — активность (сделок/мин в окне триггера vs средняя за 12ч).
Плюс signed-версии: >0 = поток В СТОРОНУ сделки (LONG: +delta, SHORT: −delta).
Использование: python _cvd_features_v1.py
"""
import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"


def wr(p):
    d = p[p.outcome.isin(["tp", "sl"])]
    return 100.0 * (d.outcome == "tp").mean() if len(d) else 0.0


def main() -> None:
    df = pd.read_pickle(BASE + "/stream_off_v1_v2.pkl")
    sol = df[df.sym == "SOL"].copy()
    m = pd.read_pickle(BASE + "/cvd/SOLUSDT_minute.pkl").sort_values("ts_ms")
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
    for r in sol.itertuples():
        ms = int(pd.Timestamp(r.decision_at).timestamp() * 1000)
        trig_raw = r.trigger_bar_time
        try:
            trig = int(pd.Timestamp(str(trig_raw)).timestamp() * 1000)
        except Exception:
            trig = None
        tfm = 5 if r.prof == "tf7" else 30
        row = {"of_trig": np.nan, "of_1h": np.nan, "of_4h": np.nan, "act": np.nan}
        if trig is not None:
            d_t, v_t = wsum(cd, trig, trig + tfm * 60000), wsum(cv, trig, trig + tfm * 60000)
            n_t = wsum(cn, trig, trig + tfm * 60000)
            if v_t > 0:
                row["of_trig"] = d_t / v_t
            n_prev = wsum(cn, ms - 12 * 3600_000, ms)
            if n_prev > 0:
                row["act"] = (n_t / tfm) / (n_prev / 720.0)
        d1, v1 = wsum(cd, ms - 3600_000, ms), wsum(cv, ms - 3600_000, ms)
        d4, v4 = wsum(cd, ms - 4 * 3600_000, ms), wsum(cv, ms - 4 * 3600_000, ms)
        if v1 > 0:
            row["of_1h"] = d1 / v1
        if v4 > 0:
            row["of_4h"] = d4 / v4
        feats.append(row)
    ff = pd.DataFrame(feats, index=sol.index)
    sgn = np.where(sol["dir"] == "SHORT", -1.0, 1.0)
    for c in ("of_trig", "of_1h", "of_4h"):
        ff[c + "_s"] = ff[c] * sgn
    sol2 = pd.concat([sol, ff], axis=1)
    sol2.to_pickle(BASE + "/stream_sol_cvd.pkl")
    print(f"saved stream_sol_cvd.pkl | SOL n={len(sol2)} | notna: "
          + ", ".join(f"{c}={sol2[c].notna().sum()}" for c in ("of_trig", "of_1h", "of_4h", "act")), flush=True)

    s = sol2
    print("corr с r_net:", flush=True)
    for c in ("of_trig_s", "of_1h_s", "of_4h_s", "act"):
        cc = s[[c, "r_net"]].corr().iloc[0, 1]
        print(f"  corr({c}, r_net) = {cc:.3f}", flush=True)

    for col in ("of_trig_s", "of_1h_s", "of_4h_s", "act"):
        g_all = s[s[col].notna()]
        for d in ("SHORT", "LONG"):
            g = g_all[g_all["dir"] == d].copy()
            if len(g) < 60:
                continue
            g["q"] = pd.qcut(g[col].rank(method="first"), 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"])
            print(f"--- {col} × {d} (n={len(g)}) ---", flush=True)
            for q, gg in g.groupby("q", observed=True):
                print(f"  {q}: n={len(gg):4d} WR={wr(gg):5.1f}%  ΣR={gg.r_net.sum():7.1f}  AvgR={gg.r_net.mean():6.3f}", flush=True)


if __name__ == "__main__":
    main()
