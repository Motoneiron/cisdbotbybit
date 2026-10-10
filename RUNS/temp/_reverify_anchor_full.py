"""РЕ-ПРОВЕРКА на ЛАЙВ-якоре (from_ts): VWAP (все ноги) + CVD + Эллиотт.

База: stream_ungated_v2.pkl (54 368 сд, полный LIMIT-поток, filters-off, min_stop 0.25%, TP1R,
комиссии Bybit). vd_conf уже там. На этом якоре считаем ЗАНОВО:
  - of1_conf  — order-flow 1ч до from_ts (Binance minute delta), direction-adjusted;
  - elliott   — ZigZag(HTF, theta=1.5 ATR), только ЗАКРЫТЫЕ бакеты; frac, same_leg, chase.
Плюс для КОНТРАСТА на подмножестве DEP-гейта (25 230) тянем СТАРЫЙ якорь из
stream_off_v1_lv0_v2_el.pkl / _pf.pkl (zz_frac/zz_last_dir/of_1h_s на decision_at).

Выход: stream_reanchor_full.pkl + полный отчёт в stdout.
"""
import heapq
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from backtest.data import load_ltf
from backtest.sweep_atr_filter import compute_atr14

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"


def wr(g):
    d = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (d.outcome == "tp").mean() if len(d) else float("nan")


def line(g, label, total=None):
    tp = int((g.outcome == "tp").sum()); sl = int((g.outcome == "sl").sum())
    tme = int((g.outcome == "time").sum())
    share = f" ({100*len(g)/total:4.1f}%)" if total else ""
    return (f"  {label:36}: n={len(g):6d} WR={wr(g):5.1f}% SumR={g.r_net.sum():+9.1f} "
            f"avg={g.r_net.mean():+.3f} TP/SL/TIME={tp}/{sl}/{tme}{share}")


def zigzag(htf, atr, theta):
    """Порт бит-в-бит из бота (ELLIOTT_PATCH_SKETCH): пивот подтверждается откатом >= theta*ATR."""
    pivots = []
    idx = htf.index
    h = htf["high"].to_numpy(float)
    l = htf["low"].to_numpy(float)
    c = htf["close"].to_numpy(float)
    a = atr.to_numpy(float)
    n = len(htf)
    if n < 3:
        return pivots
    dirn = 1 if c[1] >= c[0] else -1
    ext = h[1] if dirn == 1 else l[1]
    ext_i = 1
    for i in range(2, n):
        if not np.isfinite(a[i]) or a[i] <= 0:
            continue
        if dirn == 1:
            if h[i] > ext:
                ext, ext_i = h[i], i
            elif (ext - l[i]) >= theta * a[i]:
                pivots.append((idx[i], idx[ext_i], ext, "up"))
                dirn, ext, ext_i = -1, l[i], i
        else:
            if l[i] < ext:
                ext, ext_i = l[i], i
            elif (h[i] - ext) >= theta * a[i]:
                pivots.append((idx[i], idx[ext_i], ext, "down"))
                dirn, ext, ext_i = 1, h[i], i
    return pivots


def portfolio(d, risk_pct=0.01, start=100.0, max_pos=7, w=None):
    """1 поз/пара, лимит max_pos, риск risk_pct (× w_i для сайзинга). События по минутам."""
    d = d.sort_values("t_in")
    if w is None:
        w = np.ones(len(d))
    d = list(zip(d.t_in.astype("int64"), d.t_out.astype("int64"), d.sym,
                 d.r_net.astype(float), np.asarray(w, float)))
    pair_end, open_heap, taken = {}, [], []
    skip_pair = skip_lim = max_conc = 0
    for tin, tout, sym, r, wi in d:
        while open_heap and open_heap[0] <= tin:
            heapq.heappop(open_heap)
        pe = pair_end.get(sym)
        if pe is not None and tin < pe:
            skip_pair += 1
            continue
        if len(open_heap) >= max_pos:
            skip_lim += 1
            continue
        taken.append((tin, tout, r, wi))
        heapq.heappush(open_heap, tout)
        pair_end[sym] = tout
        max_conc = max(max_conc, len(open_heap))
    ev = []
    for i, (tin, tout, r, wi) in enumerate(taken):
        ev.append((tin, 1, i)); ev.append((tout, 0, i))
    ev.sort(key=lambda e: (e[0], e[1], e[2]))
    balance = start
    risks = {}
    curve = [(ev[0][0] if ev else 0, balance)]
    for t, kind, i in ev:
        tin, tout, r, wi = taken[i]
        if kind == 0:
            if i in risks:
                balance += risks.pop(i) * r
        else:
            if tout <= tin:
                balance += balance * risk_pct * wi * r
            else:
                risks[i] = balance * risk_pct * wi
        curve.append((t, balance))
    s = pd.Series([c[1] for c in curve])
    mdd = float(((s - s.cummax()) / s.cummax()).min() * 100)
    cur = pd.DataFrame(curve, columns=["t", "bal"])
    cur["year"] = pd.to_datetime(cur.t, unit="m").dt.year
    yearly = cur.groupby("year")["bal"].last()
    return balance, mdd, {"n": len(taken), "sp": skip_pair, "sl": skip_lim, "mc": max_conc}, yearly


def main():
    df = pd.read_pickle(f"{BASE}/stream_ungated_v2.pkl")
    df["from_ts"] = pd.to_datetime(df["from_ts"])
    print(f"БАЗА: полный поток n={len(df)} rows, cols={list(df.columns)}", flush=True)

    # ---------- 1) CVD на from_ts ----------
    df["of1_conf"] = np.nan
    import pickle
    for sym, idx in df.groupby("sym").groups.items():
        p = f"{BASE}/cvd/{sym}USDT_minute.pkl"
        if not os.path.exists(p):
            print(f"  [cvd {sym}] НЕТ файла", flush=True); continue
        with open(p, "rb") as fh:
            m = pickle.load(fh)
        m = m.sort_values("ts_ms")
        ts = m.ts_ms.to_numpy(np.int64)
        dlt = m.delta.to_numpy(float)
        vol = (m.buy + m.sell).to_numpy(float)
        cd = np.concatenate([[0.0], np.cumsum(dlt)])
        cv = np.concatenate([[0.0], np.cumsum(vol)])
        for r_i, row in df.loc[idx].iterrows():
            t1 = int(row.from_ts.timestamp() * 1000)
            i0 = int(np.searchsorted(ts, t1 - 3600_000, "left"))
            i1 = int(np.searchsorted(ts, t1, "left"))
            v = cv[i1] - cv[i0]
            if v > 0:
                of = (cd[i1] - cd[i0]) / v
                df.at[r_i, "of1_conf"] = of * (1.0 if row["dir"] == "LONG" else -1.0)
        print(f"  [cvd {sym}] ok", flush=True)
    print(f"CVD: посчитано of1_conf на {int(df.of1_conf.notna().sum())}/{len(df)}", flush=True)

    # ---------- 2) Эллиотт на from_ts ----------
    df["el_frac"] = np.nan
    df["el_same"] = np.nan
    for (sym, prof), idx in df.groupby(["sym", "prof"]).groups.items():
        rule = "4h" if prof == "tf7" else "8h"
        years = sorted(df.loc[idx, "year"].unique())
        for y in years:
            sel = df.index[(df.sym == sym) & (df.prof == prof) & (df.year == y)]
            if len(sel) == 0:
                continue
            try:
                dft, _ = load_ltf(tf=("5m" if prof == "tf7" else "30m"),
                                  since=f"{int(y)}-01-01", until=f"{int(y)}-12-31", symbol=sym)
            except Exception as e:
                print(f"  [el {sym} {prof} {y}] load fail {e!r}", flush=True); continue
            dft.index = pd.DatetimeIndex(dft.index)
            htf = pd.DataFrame({
                "high": dft["high"].resample(rule, label="left", closed="left").max(),
                "low": dft["low"].resample(rule, label="left", closed="left").min(),
                "close": dft["close"].resample(rule, label="left", closed="left").last(),
            }).dropna()
            htf_atr = compute_atr14(htf)
            rule_td = pd.Timedelta(rule)
            close_arr = dft["close"].to_numpy(float)
            low_arr = dft["low"].to_numpy(float)
            high_arr = dft["high"].to_numpy(float)
            ts_arr = dft.index.to_numpy()
            # закрытые бакеты: bucket_start + rule <= fts
            closed_end = (htf.index + rule_td).to_numpy()
            rows = df.loc[sel].sort_values("from_ts")
            cache_n, cache_piv = -1, []
            for r_i, row in rows.iterrows():
                fts = row.from_ts
                n_closed = int(np.searchsorted(closed_end, np.datetime64(fts), "right"))
                if n_closed < 3:
                    continue
                if n_closed != cache_n:
                    hc = htf.iloc[:n_closed]
                    cache_piv = zigzag(hc, htf_atr.iloc[:n_closed], 1.5)
                    cache_n = n_closed
                piv = cache_piv
                if len(piv) < 2:
                    continue
                pB, pA = piv[-1], piv[-2]
                leg = abs(pB[2] - pA[2])
                if leg <= 0:
                    continue
                i0 = int(np.searchsorted(ts_arr, np.datetime64(pB[0] + rule_td), "left"))
                i1 = int(np.searchsorted(ts_arr, np.datetime64(fts), "right"))
                if i1 - i0 < 1:
                    continue
                if pB[3] == "up":
                    frac = (pB[2] - float(low_arr[i0:i1].min())) / leg
                else:
                    frac = (float(high_arr[i0:i1].max()) - pB[2]) / leg
                same = (pB[3] == "up" and row["dir"] == "LONG") or (pB[3] == "down" and row["dir"] == "SHORT")
                df.at[r_i, "el_frac"] = frac
                df.at[r_i, "el_same"] = 1.0 if same else 0.0
            print(f"  [el {sym} {prof} {int(y)}] ok", flush=True)

    df.to_pickle(f"{BASE}/stream_reanchor_full.pkl")
    print(f"\nsaved stream_reanchor_full.pkl ({len(df)} rows)", flush=True)

    # ---------- контраст: старый якорь на подмножестве DEP ----------
    elp = pd.read_pickle(f"{BASE}/stream_off_v1_lv0_v2_el.pkl")
    pfp = pd.read_pickle(f"{BASE}/stream_off_v1_lv0_v2_pf.pkl")
    key = lambda d: d["hash"].astype(str) + "|" + d["prof"].astype(str)
    old = {}
    for k, zz_d, zz_f in zip(key(elp), elp.zz_last_dir, elp.zz_frac):
        old[(k, "zz")] = (zz_d, zz_f)
    for k, o1, o4 in zip(key(pfp), pfp.of_1h_s, pfp.of_4h_s):
        old[(k, "of")] = (o1, o4)
    kdf = key(df)
    df["old_zz_dir"] = [old.get((k, "zz"), (None, None))[0] for k in kdf]
    df["old_zz_frac"] = [old.get((k, "zz"), (None, None))[1] for k in kdf]
    df["old_of1"] = [old.get((k, "of"), (None, None))[0] for k in kdf]
    df["in_dep"] = ((df["dir"] == "SHORT") & (df.vd_conf <= 0)) | ((df["dir"] == "LONG") & (df.vd_conf >= 0))
    print(f"старые фичи подтянуты на {int(df.old_of1.notna().sum())} строк (DEP-подмножество)", flush=True)

    total = len(df)
    print("\n" + "=" * 96, flush=True)
    print("A) VWAP-ГЕЙТ — ВСЕ НОГИ на ЛАЙВ-якоре (vd_conf), полный поток", flush=True)
    print("=" * 96, flush=True)
    g = df[df.vd_conf.notna()]
    print(f"  (vd_conf есть у {len(g)}/{total})", flush=True)
    vc = g.vd_conf; S = g["dir"] == "SHORT"; L = g["dir"] == "LONG"
    print(line(g, "ПОТОК без гейта", total))
    print(line(g[S & (vc <= 0)], "S vd<=0 (ОСТАВЛЯЕМ)", total))
    print(line(g[S & (vc <= -1)], "  S vd<=-1", total))
    print(line(g[S & (vc <= -2)], "  S vd<=-2", total))
    print(line(g[S & (vc > 0)], "S vd>0 (РЕЖЕМ)", total))
    print(line(g[L & (vc >= 0)], "L vd>=0 (ОСТАВЛЯЕМ)", total))
    print(line(g[L & (vc >= 1)], "  L vd>=1", total))
    print(line(g[L & (vc >= 2)], "  L vd>=2", total))
    print(line(g[L & (vc < 0)], "L vd<0 (РЕЖЕМ)", total))
    print(line(g[((g["dir"] == "SHORT") & (vc <= 0)) | ((g["dir"] == "LONG") & (vc >= 0))],
               "КОМБО = ДЕПЛОЙ (S<=0 / L>=0)", total), flush=True)
    print("\n  --- вариант: L>=0, шорты БЕЗ фильтра ---", flush=True)
    print(line(g[(g["dir"] == "SHORT") | ((g["dir"] == "LONG") & (vc >= 0))], "S все / L>=0", total))
    m_lonly = (g["dir"] == "SHORT") | ((g["dir"] == "LONG") & (vc >= 0))
    print("\n  --- по годам (L>=0-only) ---", flush=True)
    for y, gy in g.groupby("year"):
        my = (gy["dir"] == "SHORT") | ((gy["dir"] == "LONG") & (gy.vd_conf >= 0))
        print(line(gy[my], f"    {int(y)}"), flush=True)

    print("\n" + "=" * 96, flush=True)
    print("B) CVD (of1_conf, 1ч до from_ts) — старый якорь vs новый", flush=True)
    print("=" * 96, flush=True)
    ov = df[df.old_of1.notna() & df.of1_conf.notna()]
    if len(ov) > 100:
        print(f"  corr(rank) старый/новый (DEP-подмножество n={len(ov)}): "
              f"{np.corrcoef(ov.old_of1.rank(), ov.of1_conf.rank())[0,1]:.3f}", flush=True)
    for tag, col in (("СТАРЫЙ (decision)", "old_of1"), ("НОВЫЙ (from_ts)", "of1_conf")):
        for dr in ("SHORT", "LONG"):
            s = df[(df["dir"] == dr) & df[col].notna()].copy()
            if len(s) < 500:
                continue
            s["q"] = pd.qcut(s[col].rank(method="first"), 5, labels=[1, 2, 3, 4, 5])
            line_s = "  ".join(f"Q{q}:{wr(x):4.0f}%/{x.r_net.mean():+.3f}" for q, x in s.groupby("q", observed=True))
            print(f"  {tag:18} {dr:5}: {line_s}", flush=True)
    print("\n  --- НОВЫЙ якорь, по годам (полный поток) ---", flush=True)
    for dr in ("SHORT", "LONG"):
        s = df[(df["dir"] == dr) & df.of1_conf.notna()].copy()
        s["q"] = pd.qcut(s.of1_conf.rank(method="first"), 5, labels=[1, 2, 3, 4, 5])
        for y, gy in s.groupby("year"):
            if len(gy) < 100:
                continue
            agg = gy.groupby("q", observed=True).r_net.agg(["size", "mean"])
            q1, q5 = agg.loc[1], agg.loc[5]
            print(f"    {dr:5} {int(y)}: Q1 n={int(q1['size']):4d} avg={q1['mean']:+.3f} | "
                  f"Q5 n={int(q5['size']):4d} avg={q5['mean']:+.3f}", flush=True)

    print("\n" + "=" * 96, flush=True)
    print("C) ЭЛЛИОТТ («гонка» = вдоль последней ноги ZigZag с мелким откатом)", flush=True)
    print("=" * 96, flush=True)
    el = df[df.el_frac.notna()]
    print(f"  фича есть у {len(el)}/{total}", flush=True)
    same = el.el_same == 1.0
    for thr in (0.08, 0.15, 0.236, 0.25, 0.35):
        m = same & (el.el_frac < thr)
        print(line(el[m], f"  горит: same_leg & frac<{thr}"), flush=True)
    m236 = same & (el.el_frac < 0.236)
    print("\n  --- frac<0.236 по годам (полный поток) ---", flush=True)
    for y, gy in el.groupby("year"):
        my = (gy.el_same == 1.0) & (gy.el_frac < 0.236)
        print(line(gy[my], f"    {int(y)}"), flush=True)
    print("\n  --- контраст: СТАРЫЙ якорь (decision) на DEP-подмножестве ---", flush=True)
    od = df[df.old_zz_frac.notna()].copy()
    om = (od["dir"] == od.old_zz_dir) & (od.old_zz_frac < 0.236)
    print(line(od[om], "  старое: same & frac<0.236 (DEP-подмн)", len(od)), flush=True)
    nm = (od.el_same == 1.0) & (od.el_frac < 0.236)
    print(line(od[nm], "  новое (те же строки)", len(od)), flush=True)
    print("\n  --- эффект SKIP: поток минус гонка ---", flush=True)
    base = df[df.el_frac.notna()]
    keep = ~((base.el_same == 1.0) & (base.el_frac < 0.236))
    print(line(base[keep], "  полный поток БЕЗ гонки"), flush=True)
    dep = base[base.in_dep]
    keep_d = ~((dep.el_same == 1.0) & (dep.el_frac < 0.236))
    print(line(dep[keep_d], "  DEP-поток БЕЗ гонки"), flush=True)

    print("\n" + "=" * 96, flush=True)
    print("D) ПОРТФЕЛЬ (1 поз/пара, лимит 7, риск 1%, $100) — правила на vd_conf", flush=True)
    print("=" * 96, flush=True)
    d2 = df.copy()
    d2["t_in"] = ((pd.to_datetime(d2.ts_fill) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
    d2["t_out"] = ((pd.to_datetime(d2.exit_ts) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
    d2 = d2[d2.t_out > d2.t_in].copy()
    vc2 = d2.vd_conf; S2 = d2["dir"] == "SHORT"; L2 = d2["dir"] == "LONG"
    RULES = {
        "raw (без гейта)": pd.Series(True, index=d2.index),
        "DEP: S<=0 / L>=0": (S2 & (vc2 <= 0)) | (L2 & (vc2 >= 0)),
        "S<=0, L все": (S2 & (vc2 <= 0)) | L2,
        "S все, L>=0": S2 | (L2 & (vc2 >= 0)),
        "S<=0.5 / L>=0": (S2 & (vc2 <= 0.5)) | (L2 & (vc2 >= 0)),
        "S<=1 / L>=0": (S2 & (vc2 <= 1)) | (L2 & (vc2 >= 0)),
        "S<=0 / L>=-1": (S2 & (vc2 <= 0)) | (L2 & (vc2 >= -1)),
    }
    print(f"  {'правило':22} | {'взято':>6} | {'финал $':>13} | {'MaxDD':>7} | {'2024 $':>10} | {'2025 $':>10} | {'2026 $':>10}", flush=True)
    for name, mask in RULES.items():
        fin, mdd, st, yearly = portfolio(d2[mask.fillna(False)])
        print(f"  {name:22} | {st['n']:>6} | {fin:>13,.0f} | {mdd:>6.1f}% | "
              f"{yearly.get(2024, float('nan')):>10,.0f} | {yearly.get(2025, float('nan')):>10,.0f} | "
              f"{yearly.get(2026, float('nan')):>10,.0f}", flush=True)
    print("\n  --- + SKIP гонки поверх правил ---", flush=True)
    nocl = ~((d2.el_same == 1.0) & (d2.el_frac < 0.236))
    for name in ("raw (без гейта)", "DEP: S<=0 / L>=0", "S все, L>=0"):
        fin, mdd, st, yearly = portfolio(d2[RULES[name].fillna(False) & nocl])
        print(f"  {name+' + Эллиотт':34} | {st['n']:>6} | {fin:>13,.0f} | {mdd:>6.1f}%", flush=True)

    print("\n  --- CVD-сайзинг (frozen-терцили 2020-23, веса 0.7/1.0/1.3) ---", flush=True)
    lo, hi = 0.0063, 0.0712
    wgt = np.where(d2.of1_conf.isna(), 1.0,
                   np.where(d2.of1_conf <= lo, 0.7, np.where(d2.of1_conf <= hi, 1.0, 1.3)))
    m_dep = RULES["DEP: S<=0 / L>=0"].fillna(False).to_numpy()
    m_lon = RULES["S все, L>=0"].fillna(False).to_numpy()
    m_all = np.ones(len(d2), bool)
    for name, m in (("raw", m_all), ("DEP", m_dep), ("L>=0-only", m_lon)):
        fin, mdd, st, yearly = portfolio(d2[m], w=wgt[m])
        print(f"  сайзинг {name:12} | {st['n']:>6} | {fin:>13,.0f} | MaxDD {mdd:>6.1f}%", flush=True)
    print("\nDONE", flush=True)


if __name__ == "__main__":
    main()
