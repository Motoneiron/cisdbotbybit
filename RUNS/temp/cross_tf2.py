"""Проверка двух кросс-ТФ находок и строгий тест подтверждения старшим ТФ.

Из cross_tf.py: единый по всем четырём профилям признак ровно один — ширина стопа,
и ещё SHORT устойчиво лучше LONG. Всё остальное (quality_score, psl_probability,
start_range_atr, confirm_on_sweep, ширина базы) меняет знак между профилями, то
есть подогнано под конкретный ТФ.

Здесь:
  1. универсальное правило SHORT + стоп ≥ X на всех четырёх профилях, по годам;
  2. подтверждение в строгой форме — не «был ли сигнал рядом», а «открыта ли
     в этот момент позиция того же направления на старшем профиле»;
  3. корреляция исходов: если tf8 и tf2 стоят в одну сторону по одной паре,
     это одна и та же информация или разная.

Запуск: python cross_tf2.py
"""
from __future__ import annotations

import pickle

import numpy as np
import pandas as pd

from cross_tf import PROF, TPG, signal_anchors, table

HOLD_H = {"tf0": 6, "tf1": 16, "tf2": 24, "tf8": 6}
THRESH = (0.0, 1.0, 1.5, 2.0, 2.5, 3.0)


def universal_rule(tabs: dict[str, pd.DataFrame]) -> None:
    print("1. SHORT + стоп ≥ X: net R (лет в плюсе из 7)\n")
    head = "   порог   " + "".join(p.rjust(22) for p in PROF)
    print(head)
    for th in THRESH:
        line = f"   ≥{th:.1f}%  "
        for p in PROF:
            d = tabs[p]
            g = d[(d.dir == "SHORT") & (d.stop_pct >= th)]
            if len(g) < 100:
                line += "—".rjust(22)
                continue
            pos = sum(1 for y in sorted(g.year.unique()) if g[g.year == y].net.mean() > 0)
            line += f"{g.net.mean():+.4f} n={len(g):<5d} {pos}/7".rjust(22)
        print(line)
    print("\n   для сравнения LONG + стоп ≥ 2.5%:")
    for p in PROF:
        d = tabs[p]
        g = d[(d.dir == "LONG") & (d.stop_pct >= 2.5)]
        if len(g) < 100:
            print(f"     {p}: мало ({len(g)})")
            continue
        pos = sum(1 for y in sorted(g.year.unique()) if g[g.year == y].net.mean() > 0)
        print(f"     {p}: n={len(g):5d} net={g.net.mean():+.4f} лет={pos}/7")


def strict_confirm(tabs: dict[str, pd.DataFrame]) -> None:
    print("\n\n2. Открыта ли в момент входа позиция того же направления на другом ТФ\n")
    for target in ("tf8", "tf2", "tf1"):
        d = tabs[target].copy()
        print(f"  цель {target}: n={len(d)} база net={d.net.mean():+.4f}")
        for src in PROF:
            if src == target:
                continue
            s = tabs[src]
            hold = np.timedelta64(HOLD_H[src], "h")
            # интервалы удержания сделок источника по (пара, направление)
            iv: dict[tuple[str, str], np.ndarray] = {}
            for (sym, dr), g in s.groupby(["sym", "dir"]):
                iv[(sym, dr)] = np.sort(np.array(g.anchor, dtype="datetime64[ns]"))
            same = np.zeros(len(d), dtype=bool)
            opp = np.zeros(len(d), dtype=bool)
            for i, (sym, dr, a) in enumerate(zip(d.sym, d.dir, d.anchor)):
                a64 = np.datetime64(a)
                o = "SHORT" if dr == "LONG" else "LONG"
                for side, dst in ((dr, same), (o, opp)):
                    arr = iv.get((sym, side))
                    if arr is None:
                        continue
                    # позиция источника активна, если её якорь в (a − hold, a]
                    lo = np.searchsorted(arr, a64 - hold, "right")
                    hi = np.searchsorted(arr, a64, "right")
                    dst[i] = hi > lo
            parts = []
            for lbl, m in (("совпад", same & ~opp), ("против", opp & ~same),
                           ("оба", same & opp), ("нет", ~same & ~opp)):
                g = d[m]
                if len(g) < 50:
                    parts.append(f"{lbl} n={len(g)} —")
                    continue
                parts.append(f"{lbl} n={len(g):5d} net={g.net.mean():+.4f}")
            print(f"    источник {src}: " + " | ".join(parts))
        print()


def outcome_corr(tabs: dict[str, pd.DataFrame]) -> None:
    print("\n3. Корреляция исходов пересекающихся сделок разных ТФ\n")
    combos = [("tf8", "tf2"), ("tf8", "tf1"), ("tf1", "tf2"), ("tf0", "tf8")]
    for a_name, b_name in combos:
        A, B = tabs[a_name], tabs[b_name]
        rows = []
        hold = np.timedelta64(HOLD_H[b_name], "h")
        for (sym, dr), ga in A.groupby(["sym", "dir"]):
            gb = B[(B.sym == sym) & (B.dir == dr)]
            if not len(gb):
                continue
            bt = np.array(gb.anchor, dtype="datetime64[ns]")
            order = np.argsort(bt)
            bt, bnet, bsl = bt[order], gb.net.to_numpy()[order], gb.is_sl.to_numpy()[order]
            for a64, anet, asl in zip(np.array(ga.anchor, dtype="datetime64[ns]"),
                                      ga.net.to_numpy(), ga.is_sl.to_numpy()):
                lo = np.searchsorted(bt, a64 - hold, "right")
                hi = np.searchsorted(bt, a64, "right")
                if hi > lo:
                    rows.append((anet, float(np.mean(bnet[lo:hi])),
                                 asl, float(np.mean(bsl[lo:hi]))))
        if len(rows) < 100:
            print(f"  {a_name} ~ {b_name}: пересечений мало ({len(rows)})")
            continue
        r = pd.DataFrame(rows, columns=["a_net", "b_net", "a_sl", "b_sl"])
        print(f"  {a_name} ~ {b_name}: пересечений {len(r)}, "
              f"corr(net)={r.a_net.corr(r.b_net):+.3f}, "
              f"corr(стоп)={r.a_sl.corr(r.b_sl):+.3f}")
        # исход старшего как фильтр для младшего нельзя (будущее), но можно
        # проверить, насколько они вообще про одно и то же
        both_sl = float(((r.a_sl > 0.5) & (r.b_sl > 0.5)).mean())
        exp = float((r.a_sl > 0.5).mean() * (r.b_sl > 0.5).mean())
        print(f"     оба в стоп: факт {both_sl:.3f} против случайного {exp:.3f}")


if __name__ == "__main__":
    try:
        tabs = pickle.load(open(f"{TPG}/cross_tf_tabs.pkl", "rb"))
    except FileNotFoundError:
        tabs = {p: table(p) for p in PROF}
    universal_rule(tabs)
    strict_confirm(tabs)
    outcome_corr(tabs)
