"""Проверка устойчивости KC-клетки к якорю (главная претензия к старому KC-фильтру).

Старый провал: сравнение СВЕЖЕЙ цены сигнала с УСТАРЕВШИМ kc_mid + ожидание detect_step (задержка).
Мой замер: kc_pos_s = закрытие confirm-бара против СВОЕГО же канала (EMA20/1.5ATR того же бара) — self-consistent.

Здесь считаем kc_pos_s под ДВУМЯ якорями на одних и тех же сделках:
  A: последний бар, закрытый к decision_at;
  B: следующий закрытый бар после A (сдвиг +1 бар).
Сравниваем эффект клетки (KC<0 & r1<q1) под A и B: если отрицательна под ОБОИМИ — эффект не хрупок к сдвигу бара.
Плюс: флип-рейт вердикта KC<0 между якорями.

⚠️ ПРАВКА (14.09, после прогона): выяснилось, что `decision_at` = accept движка (+26/60 мин после конфирма), а филлы — на `from_ts` ⇒ ОБА якоря A/B здесь — ПОСТ-филловые (не лайв-якорь). Честную проверку на лайв-якоре делает `_q_reanchor.py`.

Вход: stream_off_v1_lv0_v2_pf.pkl (r1_s уже там). Выход: _q_kc_anchor.pkl + печать.
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from backtest.data import load_ltf

BASE = "D:/PYTHON/cisdbotbybit/RUNS/temp"
SYMS = ["SOL", "BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP"]


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def atr_wilder(h, l, c, n=14):
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def wr(g):
    d = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (d.outcome == "tp").mean() if len(d) else float("nan")


def main() -> None:
    df = pd.read_pickle(f"{BASE}/stream_off_v1_lv0_v2_pf.pkl")
    df = df[df.r1_s.notna()].copy()
    df["kc_A"] = np.nan
    df["kc_B"] = np.nan
    for (sym, prof, year), idx in df.groupby(["sym", "prof", "year"]).groups.items():
        tf = "5m" if prof == "tf7" else "30m"
        tfm = 5 if prof == "tf7" else 30
        try:
            dft, _ = load_ltf(tf=tf, since=f"{int(year)}-01-01", until=f"{int(year)}-12-31", symbol=sym)
        except Exception as e:
            print(f"[{sym} {prof} {year}] load fail {e!r}", flush=True)
            continue
        dft.index = pd.DatetimeIndex(dft.index)
        ts = dft.index.to_numpy()
        c = dft["close"]
        e20 = ema(c, 20).to_numpy(float)
        a14 = atr_wilder(dft["high"], dft["low"], c).to_numpy(float)
        cl = c.to_numpy(float)
        for r_i, row in df.loc[idx].iterrows():
            dec = pd.Timestamp(str(row["decision_at"]))
            i0 = int(np.searchsorted(ts, np.datetime64(dec - pd.Timedelta(minutes=tfm)), "right")) - 1
            if i0 < 30:
                continue
            i1 = min(i0 + 1, len(ts) - 1)
            sgn = 1.0 if row["dir"] == "LONG" else -1.0
            if a14[i0] > 0:
                df.at[r_i, "kc_A"] = ((cl[i0] - e20[i0]) / (1.5 * a14[i0])) * sgn
            if a14[i1] > 0:
                df.at[r_i, "kc_B"] = ((cl[i1] - e20[i1]) / (1.5 * a14[i1])) * sgn
        print(f"[{sym} {prof} {int(year)}] done", flush=True)

    df.to_pickle(f"{BASE}/_q_kc_anchor.pkl")
    print("saved _q_kc_anchor.pkl", flush=True)

    fit = df[df.year <= 2023]
    q1 = fit.r1_s.quantile(1 / 3)
    r1low = df.r1_s < q1
    for tag in ("A", "B"):
        kcn = df["kc_" + tag] < 0
        cell = kcn & r1low
        c = df[cell]
        n_only = df[kcn & ~r1low]
        print(f"\n=== якорь {tag} {'(confirm/мой)' if tag=='A' else '(scan-1/со сдвигом)'} ===", flush=True)
        print(f"  KC<0 всего: n={kcn.sum()} ΣR={df[kcn].r_net.sum():+.1f}", flush=True)
        print(f"  клетка KC<0&r1low: n={len(c)} WR={wr(c):.1f}% ΣR={c.r_net.sum():+.1f}", flush=True)
        print(f"  KC<0 & r1 не-low: n={len(n_only)} ΣR={n_only.r_net.sum():+.1f}", flush=True)
        for y, g in df.groupby("year"):
            cc = g[(g['kc_' + tag] < 0) & (g.r1_s < q1)]
            if len(cc) >= 20:
                print(f"    {int(y)}: n={len(cc):4d} ΣR={cc.r_net.sum():+7.1f}", flush=True)
    both = df.kc_A.notna() & df.kc_B.notna()
    flip = ((df.kc_A < 0) != (df.kc_B < 0)) & both
    print(f"\nфлип-рейт KC<0 A→B: {100*flip.sum()/both.sum():.1f}% (как у них 39-48% на старом контуре)", flush=True)


if __name__ == "__main__":
    main()
