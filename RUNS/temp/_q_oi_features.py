"""OI / Long-Short-ratio фичи к сделкам lv0 (Bybit, 1h, данные с 2022-06).

Фичи на decision_at:
  oi_chg1  — изменение OI за 1ч (%)
  oi_chg4  — изменение OI за 4ч (%)
  oi_z     — z-score oi_chg1 против trailing 30 дней
  ls_buy   — buyRatio (уровень, 0..1)
  ls_chg1  — изменение buyRatio за 1ч
Выход: stream_off_v1_lv0_v2_oi.pkl + таблицы (фит 2022-23 / OOS 2024-26).
"""
import numpy as np
import pandas as pd

BASE = "D:/PYTHON/cisdbotbybit/RUNS/temp"
OI = BASE + "/q_oi"
SYMS = ["SOL", "BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP"]
H = 3600_000


def wr(g):
    d = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (d.outcome == "tp").mean() if len(d) else float("nan")


def main() -> None:
    df = pd.concat([pd.read_pickle(f"{BASE}/stream_{s}_cvd.pkl") for s in SYMS], ignore_index=True)
    pf = pd.read_pickle(f"{BASE}/stream_off_v1_lv0_v2_pf.pkl")[["hash", "prof", "r1_s"]].drop_duplicates(["hash", "prof"])
    df = df.merge(pf, on=["hash", "prof"], how="left")
    for c in ["oi_chg1", "oi_chg4", "oi_z", "ls_buy", "ls_chg1"]:
        df[c] = np.nan

    for sym, idx in df.groupby("sym").groups.items():
        try:
            oi = pd.read_pickle(f"{OI}/{sym}_oi.pkl").sort_values("ts_ms")
            ls = pd.read_pickle(f"{OI}/{sym}_ls.pkl").sort_values("ts_ms")
        except Exception as e:
            print(f"[{sym}] нет данных: {e!r}", flush=True)
            continue
        oi_ts = oi.ts_ms.to_numpy(np.int64)
        oi_v = oi.oi.to_numpy(float)
        # часовой ряд изменений OI
        oi_step = np.full(len(oi_v), np.nan)
        oi_step[1:] = np.where(oi_v[:-1] > 0, oi_v[1:] / oi_v[:-1] - 1.0, np.nan) * 100.0
        roll_m = pd.Series(oi_step).rolling(720, min_periods=168).mean().to_numpy()
        roll_s = pd.Series(oi_step).rolling(720, min_periods=168).std(ddof=0).to_numpy()
        ls_ts = ls.ts_ms.to_numpy(np.int64)
        ls_b = ls.buy.to_numpy(float)
        n_ok = 0
        for r_i, row in df.loc[idx].iterrows():
            dec = int(pd.Timestamp(str(row["decision_at"])).timestamp() * 1000)
            i = int(np.searchsorted(oi_ts, dec, "right")) - 1
            if i < 24 or i >= len(oi_v):
                continue
            v = oi_v[i]
            if oi_v[i - 1] > 0:
                df.at[r_i, "oi_chg1"] = (v / oi_v[i - 1] - 1.0) * 100.0
            if oi_v[i - 4] > 0:
                df.at[r_i, "oi_chg4"] = (v / oi_v[i - 4] - 1.0) * 100.0
            s = roll_s[i]
            if np.isfinite(s) and s > 0:
                df.at[r_i, "oi_z"] = (oi_step[i] - roll_m[i]) / s
            j = int(np.searchsorted(ls_ts, dec, "right")) - 1
            if j >= 1:
                df.at[r_i, "ls_buy"] = ls_b[j]
                df.at[r_i, "ls_chg1"] = ls_b[j] - ls_b[j - 1]
            n_ok += 1
        print(f"[{sym}] заполнено {n_ok}", flush=True)

    df.to_pickle(f"{BASE}/stream_off_v1_lv0_v2_oi.pkl")
    print("saved stream_off_v1_lv0_v2_oi.pkl", flush=True)

    def qtab(g, col, tag):
        gg = g[g[col].notna()]
        if len(gg) < 100:
            print(f"  {tag}: мало ({len(gg)})", flush=True)
            return
        gg = gg.copy()
        gg["q"] = pd.qcut(gg[col].rank(method="first"), 5, labels=[1, 2, 3, 4, 5])
        out = " ".join(f"Q{q}:{wr(s):.0f}%/{s.r_net.mean():+.3f}" for q, s in gg.groupby("q", observed=True))
        print(f"  {tag} n={len(gg)} | {out}", flush=True)

    fit = df[(df.year <= 2023) & (df.oi_chg1.notna())]
    oos = df[(df.year >= 2024) & (df.oi_chg1.notna())]
    print(f"\n=== OI/LS (данные с 2022-06): fit n={len(fit)}, oos n={len(oos)} ===", flush=True)
    for name, g in [("FIT 2022-23", fit), ("OOS 2024-26", oos)]:
        print(f" -- {name}", flush=True)
        for col in ("oi_chg1", "oi_chg4", "oi_z", "ls_buy", "ls_chg1"):
            qtab(g, col, col)
    print("\n=== Кросс: OI рост x направление цены (r1_s) ===", flush=True)
    for name, g in [("FIT", fit), ("OOS", oos)]:
        gg = g[g.r1_s.notna() & g.oi_chg1.notna()]
        for oi_lbl, om in [("OI+", gg.oi_chg1 > 0), ("OI-", gg.oi_chg1 <= 0)]:
            s = gg[om]
            if len(s):
                print(f"  {name} {oi_lbl}: n={len(s)} WR={wr(s):.1f}% avg={s.r_net.mean():+.3f}", flush=True)
    print("\n=== По годам (oi_chg1 верхний/нижний квинтиль фита) ===", flush=True)
    if len(fit):
        lo, hi = fit.oi_chg1.quantile(1 / 3), fit.oi_chg1.quantile(2 / 3)
        print(f"  терцили фита: {lo:+.3f} / {hi:+.3f}", flush=True)
        for y, g in df[df.oi_chg1.notna()].groupby("year"):
            low = g[g.oi_chg1 <= lo]
            high = g[g.oi_chg1 >= hi]
            print(f"  {int(y)}: низкийOI n={len(low)} WR={wr(low):.1f}%/{low.r_net.mean():+.3f} | высокийOI n={len(high)} WR={wr(high):.1f}%/{high.r_net.mean():+.3f}", flush=True)


if __name__ == "__main__":
    main()
