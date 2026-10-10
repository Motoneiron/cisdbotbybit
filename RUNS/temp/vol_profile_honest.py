"""Volume Profile на честной базе: va_pos, POC, ширина зоны, объём на пути к тейку.

Архивное наблюдение (журнал §34): va_pos поднимал WR с 60% до 69%, но считался от
`decision_at` — якоря, который на 26–60 минут ПОЗЖЕ входа. Здесь всё считается от
честного якоря (первый 5м-скан после закрытия конфирм-бара) и только по закрытым
старшим барам, на всех четырёх профилях сразу.

Профиль объёма строится на фиксированной сетке логарифма цены за год, поэтому вклад
бара аддитивен и окно из 150 старших баров берётся разностью префиксных сумм — иначе
107 тысяч сделок × 150 баров не посчитать. Допущение прежнее: объём бара распределён
равномерно между его low и high.

Признаки:
  va_pos        — где вход внутри зоны стоимости 70% (0 = низ, 1 = верх, вне = <0 / >1)
  poc_atr       — расстояние от входа до самого объёмного уровня, в ATR старшего ТФ
  va_width_atr  — ширина зоны стоимости в ATR
  block_share   — доля «толстых» уровней в объёме на пути от входа до тейка 1R
                  (гипотеза: плотный объём на пути мешает дойти до тейка)

Запуск: python vol_profile_honest.py
"""
from __future__ import annotations

import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from cross_tf import PROF, TPG, table

NBINS = 400
NWIN = 150
HTF_RULE = {"tf0": "1h", "tf1": "4h", "tf2": "1D", "tf8": "8h"}


def htf_frame(sym: str, year: int, rule: str) -> pd.DataFrame:
    from backtest.data import load_ltf

    src = "1h" if rule in ("4h", "8h", "1D") else "5m"
    d, _ = load_ltf(tf=src, since=f"{year - 1}-12-01", until=f"{year}-12-31", symbol=sym)
    d.index = pd.DatetimeIndex(d.index)
    r = d.resample(rule, label="left", closed="left")
    return pd.DataFrame({"high": r["high"].max(), "low": r["low"].min(),
                         "close": r["close"].last(), "volume": r["volume"].sum()}).dropna()


def build_grid(htf: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Префиксные суммы объёма по сетке log-цены: cum[i] — профиль первых i баров."""
    lo = np.log(htf["low"].to_numpy(float))
    hi = np.log(htf["high"].to_numpy(float))
    vol = htf["volume"].to_numpy(float)
    edges = np.linspace(lo.min(), hi.max(), NBINS + 1)
    cum = np.zeros((len(htf) + 1, NBINS), dtype=np.float32)
    for i in range(len(htf)):
        cum[i + 1] = cum[i]
        v = vol[i]
        if not np.isfinite(v) or v <= 0:
            continue
        b0 = max(0, int(np.searchsorted(edges, lo[i], "right")) - 1)
        b1 = min(NBINS - 1, int(np.searchsorted(edges, hi[i], "left")) - 1)
        if b1 < b0:
            b1 = b0
        cum[i + 1, b0:b1 + 1] += v / (b1 - b0 + 1)
    return cum, edges


def feats(hist: np.ndarray, edges: np.ndarray, entry: float, tp1: float,
          atr: float) -> dict | None:
    tot = hist.sum()
    if tot <= 0 or not np.isfinite(atr) or atr <= 0:
        return None
    centers = (edges[:-1] + edges[1:]) / 2
    poc = float(np.exp(centers[int(np.argmax(hist))]))
    order = np.argsort(hist)[::-1]
    acc, keep = 0.0, []
    for oi in order:
        acc += hist[oi]
        keep.append(int(oi))
        if acc >= 0.7 * tot:
            break
    va_lo, va_hi = float(np.exp(edges[min(keep)])), float(np.exp(edges[max(keep) + 1]))
    le = np.log(entry)
    lo_p, hi_p = (min(le, np.log(tp1)), max(le, np.log(tp1)))
    on_path = (centers >= lo_p) & (centers <= hi_p)
    path = float(hist[on_path].sum())
    pos = hist[hist > 0]
    thick = np.where(hist > 1.5 * float(np.median(pos)), hist, 0.0)
    return {
        "va_pos": (entry - va_lo) / (va_hi - va_lo) if va_hi > va_lo else np.nan,
        "poc_atr": (entry - poc) / atr,
        "va_width_atr": (va_hi - va_lo) / atr,
        "block_share": float(thick[on_path].sum()) / path if path > 0 else np.nan,
    }


def enrich(d: pd.DataFrame, prof: str) -> pd.DataFrame:
    from backtest.sweep_atr_filter import compute_atr14

    rule = HTF_RULE[prof]
    step = pd.Timedelta(rule)
    cols = {c: np.full(len(d), np.nan) for c in
            ("va_pos", "poc_atr", "va_width_atr", "block_share")}
    for (sym, year), g in d.groupby(["sym", "year"]):
        try:
            htf = htf_frame(sym, int(year), rule)
        except Exception:
            continue
        if len(htf) < 40:
            continue
        cum, edges = build_grid(htf)
        atr = compute_atr14(htf).to_numpy(float)
        avail = np.array(htf.index + step, dtype="datetime64[ns]")
        i1 = np.searchsorted(avail, np.array(g.anchor, dtype="datetime64[ns]"), "right")
        rows = d.index.get_indexer(g.index.to_numpy())
        for k, (pos_i, e, st) in enumerate(zip(i1, g.entry, g.stop)):
            if pos_i < 40:
                continue
            i0 = max(0, pos_i - NWIN)
            # тейк 1R: для лонга 2e−st выше входа, для шорта ниже — формула одна
            f = feats(cum[pos_i] - cum[i0], edges, float(e),
                      2 * float(e) - float(st), atr[pos_i - 1])
            if f:
                for c, v in f.items():
                    cols[c][rows[k]] = v
    for c, v in cols.items():
        d[c] = v
    return d


def report(tabs: dict[str, pd.DataFrame]) -> None:
    print("\n1. Квинтили признаков профиля объёма: net R по профилям (Δ Q5−Q1, t)\n")
    print("   " + "признак".ljust(14) + "".join(p.rjust(16) for p in PROF))
    for c in ("va_pos", "poc_atr", "va_width_atr", "block_share"):
        line = "   " + c.ljust(14)
        for p in PROF:
            d = tabs[p][tabs[p][c].notna()]
            if len(d) < 400:
                line += "—".rjust(16)
                continue
            b = pd.qcut(d[c], 5, labels=False, duplicates="drop")
            lo, hi = d[b == b.min()], d[b == b.max()]
            diff = hi.net.mean() - lo.net.mean()
            se = np.sqrt(hi.net.var() / len(hi) + lo.net.var() / len(lo))
            line += f"{diff:+.3f}({diff/se:+.1f})".rjust(16)
        print(line)

    print("\n2. va_pos по зонам (вход относительно зоны стоимости), net R / доля SL\n")
    zones = [(-9, 0, "ниже зоны"), (0, 0.25, "низ зоны"), (0.25, 0.75, "середина"),
             (0.75, 1.0, "верх зоны"), (1.0, 9, "выше зоны")]
    for p in PROF:
        d = tabs[p][tabs[p].va_pos.notna()]
        print(f"   {p} (n={len(d)}, база net={d.net.mean():+.4f}):")
        for lo_, hi_, nm in zones:
            g = d[(d.va_pos >= lo_) & (d.va_pos < hi_)]
            if len(g) < 100:
                continue
            print(f"     {nm:11s} n={len(g):6d} net={g.net.mean():+.4f}"
                  f"±{g.net.std()/np.sqrt(len(g)):.4f} SL={g.is_sl.mean():.3f}")

    print("\n3. Направление × зона (архивное наблюдение было про вход у края зоны)\n")
    for p in PROF:
        d = tabs[p][tabs[p].va_pos.notna()]
        for dr in ("SHORT", "LONG"):
            g0 = d[d.dir == dr]
            edge = g0[(g0.va_pos > 0.75) if dr == "SHORT" else (g0.va_pos < 0.25)]
            mid = g0[(g0.va_pos >= 0.25) & (g0.va_pos <= 0.75)]
            if len(edge) < 100 or len(mid) < 100:
                continue
            diff = edge.net.mean() - mid.net.mean()
            se = np.sqrt(edge.net.var() / len(edge) + mid.net.var() / len(mid))
            print(f"   {p} {dr:5s}: у своего края n={len(edge):5d} net={edge.net.mean():+.4f}"
                  f" | середина n={len(mid):5d} net={mid.net.mean():+.4f}"
                  f" | Δ={diff:+.4f} (t={diff/se:+.1f})")

    print("\n4. Лучшая клетка по годам и вневыборочно\n")
    for p in PROF:
        d = tabs[p][tabs[p].va_pos.notna()]
        for nm, m in (("ниже зоны", d.va_pos < 0),
                      ("выше зоны", d.va_pos > 1),
                      ("вне зоны + стоп≥1.5%",
                       ((d.va_pos < 0) | (d.va_pos > 1)) & (d.stop_pct >= 1.5))):
            g = d[m]
            if len(g) < 300:
                continue
            ins, oos = g[g.year <= 2023], g[g.year >= 2024]
            years = [g[g.year == y].net.mean() for y in sorted(g.year.unique())
                     if len(g[g.year == y]) >= 30]
            pos = sum(1 for v in years if v > 0)
            print(f"   {p} {nm:22s} n={len(g):5d} net={g.net.mean():+.4f} "
                  f"лет={pos}/{len(years)} in={ins.net.mean():+.4f} "
                  f"out={oos.net.mean():+.4f} (n={len(oos)})")


def main() -> None:
    tabs = {}
    for p in PROF:
        tabs[p] = enrich(table(p), p)
        got = tabs[p].va_pos.notna().mean()
        print(f"{p}: {len(tabs[p])} сделок, профиль объёма посчитан у {got*100:.1f}%",
              flush=True)
    report(tabs)
    pickle.dump(tabs, open(f"{TPG}/cross_tf_vp.pkl", "wb"))


if __name__ == "__main__":
    main()
