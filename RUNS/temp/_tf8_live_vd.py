"""tf8: воспроизведение БОЕВОГО vwap-гейта (partial 30m-ведро) vs мой vd_conf (последнее закрытое).

Боевой код (cisdbot.py:9322-9355, вызов 11998): _run_detect_and_trade("tf8", df30) →
  df_cut = df30.loc[:confirm_bar_time]; vd = (close_last - vwap(df_cut))/atr14(df_cut)
df30 = resample(5m) c label/closed='left', volume=sum. Последнее ведро в df30 — ЧАСТИЧНОЕ
(включает формирующийся 5m-бар). Т.к. confirm_bar_time = from_ts − 5min, срез .loc[:confirm]
оставляет это частичное ведро → живой vd для tf8 считается по НЕЗАКРЫТОМУ ведру.

Варианты:
  A = последнее ПОЛНОСТЬЮ закрытое 30m-ведро к from_ts (то, что я считал в _reverify)  → vd_conf
  B = частичное ведро [floor30(confirm), confirm] (срез на закрытии конфирм-бара)      → vd_B
(живой = B + кусок формирующегося бара; точной копии из истории не сделать — берём рамку A..B)

Выход: tf8_vd_variants.pkl + таблица гейта на каждом варианте + комбинированный портфель.
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from backtest.data import load_ltf
from backtest.sweep_atr_filter import compute_atr14, compute_atr14 as _atr
from backtest.vwap_filter import daily_session_vwap

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
TFM = 30


def wr(g):
    d = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (d.outcome == "tp").mean() if len(d) else float("nan")


def line(g, label, total=None):
    tp = int((g.outcome == "tp").sum()); sl = int((g.outcome == "sl").sum())
    share = f" ({100*len(g)/total:4.1f}%)" if total else ""
    return (f"  {label:32}: n={len(g):6d} WR={wr(g):5.1f}% SumR={g.r_net.sum():+9.1f} "
            f"avg={g.r_net.mean():+.3f}{share}")


def main():
    df = pd.read_pickle(f"{BASE}/stream_reanchor_full.pkl")
    df["from_ts"] = pd.to_datetime(df["from_ts"])
    t8 = df[df.prof == "tf8"].copy()
    t8["vd_B"] = np.nan
    for sym, idx in t8.groupby("sym").groups.items():
        for y in sorted(t8.loc[idx, "year"].unique()):
            sel = t8.index[(t8.sym == sym) & (t8.year == y)]
            if len(sel) == 0:
                continue
            d5, _ = load_ltf(tf="5m", since=f"{int(y)}-01-01", until=f"{int(y)}-12-31", symbol=sym)
            d5.index = pd.DatetimeIndex(d5.index)
            ts5 = d5.index.to_numpy()
            h5 = d5["high"].to_numpy(float); l5 = d5["low"].to_numpy(float)
            c5 = d5["close"].to_numpy(float); v5 = d5["volume"].to_numpy(float)
            d30 = pd.DataFrame({
                "high": d5["high"].resample("30min", label="left", closed="left").max(),
                "low": d5["low"].resample("30min", label="left", closed="left").min(),
                "close": d5["close"].resample("30min", label="left", closed="left").last(),
                "volume": d5["volume"].resample("30min", label="left", closed="left").sum(),
            }).dropna()
            ts30 = d30.index.to_numpy()
            h30 = d30["high"].to_numpy(float); l30 = d30["low"].to_numpy(float)
            c30 = d30["close"].to_numpy(float); v30 = d30["volume"].to_numpy(float)
            tr30 = np.maximum.reduce([h30 - l30, np.abs(h30 - np.concatenate([[np.nan], c30[:-1]])),
                                      np.abs(l30 - np.concatenate([[np.nan], c30[:-1]]))])
            cs_pv = np.concatenate([[0.0], np.cumsum(c30 * v30)])
            cs_v = np.concatenate([[0.0], np.cumsum(v30)])
            day30 = pd.DatetimeIndex(ts30).floor("D").to_numpy()
            for r_i, row in t8.loc[sel].iterrows():
                fts = row.from_ts
                confirm = fts - pd.Timedelta(minutes=5)
                if row.prof != "tf8":
                    continue
                # --- B: частичное ведро [floor30(confirm), confirm] ---
                b_start = pd.Timestamp(confirm).floor("30min")
                j0 = int(np.searchsorted(ts5, np.datetime64(b_start), "left"))
                j1 = int(np.searchsorted(ts5, np.datetime64(confirm), "right"))
                if j1 <= j0:
                    continue
                ph = float(h5[j0:j1].max()); pl = float(l5[j0:j1].min())
                pc = float(c5[j1 - 1]); pv = float(v5[j0:j1].sum())
                i_full = int(np.searchsorted(ts30, np.datetime64(b_start), "left"))
                if i_full < 15 or i_full >= len(ts30):
                    continue
                prev_c = c30[i_full - 1]
                tr_i = max(ph - pl, abs(ph - prev_c), abs(pl - prev_c))
                tr_mod = tr30.copy(); tr_mod[i_full] = tr_i
                atr_i = np.nanmean(tr_mod[i_full - 13:i_full + 1])
                day = np.datetime64(pd.Timestamp(ts30[i_full]).floor("D"))
                d0 = int(np.searchsorted(day30, day, "left"))
                pvsum = (cs_pv[i_full] - cs_pv[d0]) + pc * pv
                vsum = (cs_v[i_full] - cs_v[d0]) + pv
                if not (atr_i > 0) or vsum <= 0:
                    continue
                t8.at[r_i, "vd_B"] = (pc - pvsum / vsum) / atr_i
            print(f"  [tf8 {sym} {int(y)}] ok", flush=True)

    t8.to_pickle(f"{BASE}/tf8_vd_variants.pkl")
    print(f"\nsaved tf8_vd_variants.pkl; vd_B посчитан на {int(t8.vd_B.notna().sum())}/{len(t8)}", flush=True)

    total = len(df)
    for tag, col in (("A: последнее ЗАКРЫТОЕ 30m (vd_conf)", "vd_conf"), ("B: частичное ведро на конфирме", "vd_B")):
        g = t8[t8[col].notna()]
        S = g["dir"] == "SHORT"; L = g["dir"] == "LONG"
        print(f"\n=== tf8, {tag} (n={len(g)}) ===", flush=True)
        print(line(g, "  поток tf8 (без гейта)", total), flush=True)
        print(line(g[S & (g[col] <= 0)], "  S vd<=0"), flush=True)
        print(line(g[S & (g[col] > 0)], "  S vd>0 (режем)"), flush=True)
        print(line(g[L & (g[col] >= 0)], "  L vd>=0"), flush=True)
        print(line(g[L & (g[col] < 0)], "  L vd<0 (режем)"), flush=True)
        dep = (S & (g[col] <= 0)) | (L & (g[col] >= 0))
        print(line(g[dep], "  ДЕПЛОЙ комбо"), flush=True)
        print(line(g[S | (L & (g[col] >= 0))], "  S все / L>=0"), flush=True)

    # --- согласие вердиктов A vs B ---
    ok = t8[t8.vd_B.notna() & t8.vd_conf.notna()]
    ga = ((ok["dir"] == "SHORT") & (ok.vd_conf <= 0)) | ((ok["dir"] == "LONG") & (ok.vd_conf >= 0))
    gb = ((ok["dir"] == "SHORT") & (ok.vd_B <= 0)) | ((ok["dir"] == "LONG") & (ok.vd_B >= 0))
    print(f"\nСОГЛАСИЕ вердикта гейта tf8 A vs B: {100*(ga == gb).mean():.1f}% (n={len(ok)})", flush=True)
    print(f"корреляция vd A/B (rank): {np.corrcoef(ok.vd_conf.rank(), ok.vd_B.rank())[0,1]:.3f}", flush=True)

    # --- комбинированный поток: tf7 (vd_conf) + tf8 (вариант) ---
    tf7 = df[df.prof == "tf7"].copy()
    m7 = ((tf7["dir"] == "SHORT") & (tf7.vd_conf <= 0)) | ((tf7["dir"] == "LONG") & (tf7.vd_conf >= 0))
    print("\n=== КОМБИНИРОВАННЫЙ ГЕЙТ (tf7 A + tf8 вариант) ===", flush=True)
    for tag, col in (("tf8=A", "vd_conf"), ("tf8=B", "vd_B")):
        S = t8["dir"] == "SHORT"; L = t8["dir"] == "LONG"
        m8 = (S & (t8[col] <= 0)) | (L & (t8[col] >= 0))
        m8lon = S | (L & (t8[col] >= 0))
        print(f"  [{tag}] поток: n={len(df)} SumR={df.r_net.sum():+.1f} | "
              f"DEP: n={int(m7.sum() + m8.fillna(False).sum())} SumR={tf7[m7].r_net.sum() + t8[m8.fillna(False)].r_net.sum():+.1f} | "
              f"S все/L>=0: n={int(m7.sum() + m8lon.fillna(False).sum())} "
              f"SumR={tf7[m7].r_net.sum() + t8[m8lon.fillna(False)].r_net.sum():+.1f}", flush=True)
    print("\nDONE", flush=True)


if __name__ == "__main__":
    main()
