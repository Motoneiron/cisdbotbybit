"""Meta-модель (walk-forward): логистическая регрессия на наших фичах, обучение на прошлых годах.

Фичи (стандартизованные, NaN→0 после стандартизации): of_1h_s, of_4h_s, r1_s, r4_s, vol_pct,
ema10_ok, ema20_ok, ema_slope_s, zz_frac, keep18, vd_s, hour_sin, hour_cos.
Цель: y = 1 если r_net > 0 (все исходы).
Walk-forward: годы 2021..2026 — обучение на ВСЕХ предыдущих годах; веса риска 0.7/1.0/1.3 по
квантилям 30/70 предсказаний ОБУЧАЮЩЕЙ части (заморожены).
Выход: таблицы по годам + общий OOS-компаундинг + децили.
"""
import numpy as np
import pandas as pd

BASE = "D:/PYTHON/cisdbotbybit/RUNS/temp"
SYMS = ["SOL", "BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP"]

FEATS = ["of_1h_s", "of_4h_s", "r1_s", "r4_s", "vol_pct", "ema10_ok", "ema20_ok",
         "ema_slope_s", "zz_frac", "keep18", "vd_s", "hour_sin", "hour_cos"]


def wr(g):
    d = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (d.outcome == "tp").mean() if len(d) else float("nan")


def fit_lr(X, y, lam=1.0, iters=40):
    """Логистическая регрессия (IRLS/Ньютон) с L2; X — стандартизованная, с колонкой 1."""
    n, d = X.shape
    w = np.zeros(d)
    for _ in range(iters):
        z = X @ w
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        W = np.clip(p * (1 - p), 1e-6, None)
        g = X.T @ (p - y) + lam * np.r_[0.0, w[1:]]
        H = X.T @ (X * W[:, None]) + lam * np.diag(np.r_[0.0, np.ones(d - 1)])
        try:
            step = np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            break
        w -= step
        if np.max(np.abs(step)) < 1e-8:
            break
    return w


def main() -> None:
    df = pd.concat([pd.read_pickle(f"{BASE}/stream_{s}_cvd.pkl") for s in SYMS], ignore_index=True)
    pf = pd.read_pickle(f"{BASE}/stream_off_v1_lv0_v2_pf.pkl")
    df["dec"] = pd.to_datetime(df["decision_at"])
    df["hour"] = df.dec.dt.hour
    df["hour_sin"] = np.sin(2 * np.pi * df.hour / 24.0)
    df["hour_cos"] = np.cos(2 * np.pi * df.hour / 24.0)
    # merge pf-фич по hash+prof (один сигнал может быть в tf7 и tf8 — ключ hash+prof)
    pf = pf[["hash", "prof", "r1_s", "r4_s", "vol_pct", "ema10_ok", "ema20_ok", "ema_slope_s", "hurst"]]
    df = df.merge(pf.drop_duplicates(["hash", "prof"]), on=["hash", "prof"], how="left")
    # zz_frac уже есть в cvd-фрейме (мерж ep при построении CVD) — отдельный merge НЕ делать (иначе суффиксы _x/_y)
    if "zz_frac" not in df.columns:
        el = pd.read_pickle(f"{BASE}/stream_off_v1_lv0_v2_el.pkl")[["hash", "zz_frac"]]
        df = df.merge(el.drop_duplicates("hash"), on="hash", how="left")
    # keep18
    knn = pd.read_pickle(f"{BASE}/knn18_lv0.pkl")[["hash", "keep"]]
    df = df.merge(knn.drop_duplicates("hash"), on="hash", how="left")
    df["keep18"] = df["keep"].astype(float)
    # vd_s — если есть колонка vd; иначе NaN
    if "vd" in df.columns:
        df["vd_s"] = df.vd * np.where(df["dir"] == "SHORT", -1.0, 1.0)
    else:
        df["vd_s"] = np.nan
    df["y"] = (df.r_net > 0).astype(float)

    have = [f for f in FEATS if df[f].notna().sum() > len(df) * 0.3]
    print("фичи в модели:", have, flush=True)

    rows = []
    oos_frames = []
    for year in range(2021, 2027):
        train = df[df.year < year]
        test = df[df.year == year].copy()
        if len(train) < 2000 or len(test) < 200:
            print(f"{year}: пропуск (train={len(train)}, test={len(test)})", flush=True)
            continue
        med = train[have].median()
        Xtr = train[have].fillna(med).to_numpy(float)
        Xte = test[have].fillna(med).to_numpy(float)
        mu, sd = Xtr.mean(0), Xtr.std(0)
        sd[sd == 0] = 1.0
        Xtr = (Xtr - mu) / sd
        Xte = (Xte - mu) / sd
        Xtr = np.c_[np.ones(len(Xtr)), Xtr]
        Xte = np.c_[np.ones(len(Xte)), Xte]
        w = fit_lr(Xtr, train.y.to_numpy(float))
        p_tr = 1.0 / (1.0 + np.exp(-np.clip(Xtr @ w, -30, 30)))
        p_te = 1.0 / (1.0 + np.exp(-np.clip(Xte @ w, -30, 30)))
        test["p"] = p_te
        q30, q70 = np.quantile(p_tr, 0.30), np.quantile(p_tr, 0.70)
        test["w"] = np.where(p_te < q30, 0.7, np.where(p_te > q70, 1.3, 1.0))
        base = float((1 + 0.01 * test.r_net).prod())
        sized = float((1 + 0.01 * test.w * test.r_net).prod())
        lo = test[test.w == 0.7]
        hi = test[test.w == 1.3]
        rows.append((year, len(test), wr(lo), lo.r_net.mean(), wr(hi), hi.r_net.mean(), base, sized))
        print(f"{year}: n={len(test)} | loWR={wr(lo):.1f}%/{lo.r_net.mean():+.3f} hiWR={wr(hi):.1f}%/{hi.r_net.mean():+.3f} | base={base:,.0f} sized={sized:,.0f} ×{sized/base:.2f}", flush=True)
        oos_frames.append(test)

    oos = pd.concat(oos_frames, ignore_index=True)
    base = float((1 + 0.01 * oos.r_net).prod())
    sized = float((1 + 0.01 * oos.w * oos.r_net).prod())
    print(f"\nВСЕ OOS (2021-26 walk-forward): n={len(oos)} base={base:,.0f}x sized={sized:,.0f}x → ×{sized/base:.2f}", flush=True)
    print("децили по p:", flush=True)
    oos = oos.copy()
    oos["dq"] = pd.qcut(oos.p.rank(method="first"), 10, labels=False) + 1
    for q, g in oos.groupby("dq"):
        print(f"  D{q}: n={len(g)} WR={wr(g):.1f}% avg={g.r_net.mean():+.3f}", flush=True)
    print("\nкоэффициенты последней модели (стандартиз.):", flush=True)
    print("  ", dict(zip(["bias"] + have, np.round(w, 3))), flush=True)
    oos.to_pickle(f"{BASE}/stream_off_v1_lv0_v2_meta.pkl")
    print("saved stream_off_v1_lv0_v2_meta.pkl", flush=True)


if __name__ == "__main__":
    main()
