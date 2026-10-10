"""Кросс-ТФ: общие признаки стоповых сделок и подтверждение одного ТФ другим.

Две части.

A. Ищем признак, который отделяет стопы ОДИНАКОВО на всех четырёх профилях.
   Признак, работающий на одном ТФ, почти всегда подгонка; если градиент
   одного знака на tf0/tf1/tf2/tf8 — это уже свойство сетапа, а не эпохи.
   Временные признаки нормированы по ТФ (доля старшего бара, число баров от
   свипа до конфирма), иначе профили несравнимы.

B. Подтверждение: в момент входа на профиле T смотрим, был ли УЖЕ сигнал на
   другом профиле S по той же паре. Окно только назад ([якорь − W, якорь]),
   иначе это подглядывание в будущее. Считаем отдельно согласные по направлению
   и противоположные — вопрос «подтверждает или наоборот» решается данными.

Запуск: python cross_tf.py
"""
from __future__ import annotations

import glob
import pickle
from collections import defaultdict

import numpy as np
import pandas as pd

TPG = "D:/PYTHON/cisdbotbybit/RUNS/temp"
SIG_OTHER = "D:/PYTHON/CISDBOT/RUNS/2026-09-21/bot_aligned"
SIG_TF8 = "D:/PYTHON/CISDBOT/RUNS/filters_off_full_aligned"
PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]
# профиль: (основной ТФ, мин; старший ТФ, мин; канонический hold из таблицы)
PROF = {
    "tf0": (5, 60, 6),
    "tf1": (15, 240, 16),
    "tf2": (60, 1440, 24),
    "tf8": (30, 480, 6),
}


def anchor_of(cbt: pd.Timestamp, main_min: int) -> pd.Timestamp:
    """Якорь решения: первый 5m-скан после закрытия конфирм-бара."""
    return (pd.Timestamp(cbt) + pd.Timedelta(minutes=main_min)).ceil("5min")


def _sig_files(prof: str) -> list[str]:
    pat = (f"{SIG_TF8}/*_tf8_*.pkl" if prof == "tf8"
           else f"{SIG_OTHER}/*_{prof}_*.pkl")
    return glob.glob(pat)


def load_signals(prof: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in _sig_files(prof):
        for s in pickle.load(open(f, "rb")).get("signals") or []:
            out[str(s.get("hash"))] = s
    return out


def signal_anchors(prof: str) -> dict[tuple[str, str], np.ndarray]:
    """(пара, направление) -> отсортированные якоря ВСЕХ сигналов профиля.

    Берём сигналы, а не сделки: подтверждение существует в момент решения
    независимо от того, заполнилась ли лимитка на том профиле.
    Символа внутри сигнала нет, поэтому читаем его из имени файла.
    """
    main_min = PROF[prof][0]
    acc: dict[tuple[str, str], list] = defaultdict(list)
    for f in _sig_files(prof):
        sym = f.replace("\\", "/").rsplit("/", 1)[-1].split("_")[0]
        for s in pickle.load(open(f, "rb")).get("signals") or []:
            acc[(sym, str(s.get("direction")))].append(
                anchor_of(pd.Timestamp(str(s.get("confirm_bar_time"))), main_min)
            )
    return {k: np.sort(np.array(v, dtype="datetime64[ns]")) for k, v in acc.items()}


def load_trades(prof: str) -> list[dict]:
    pat = (f"{TPG}/tp_grid/*_*.pkl" if prof == "tf8"
           else f"{TPG}/tp_grid_other/*_{prof}_*.pkl")
    hold = PROF[prof][2]
    out = []
    for f in glob.glob(pat):
        for r in pickle.load(open(f, "rb")):
            if int(r.get("hold", -1)) == hold:
                out.append(r)
    return out


def table(prof: str) -> pd.DataFrame:
    main_min, htf_min, _ = PROF[prof]
    sig = load_signals(prof)
    rows = []
    for t in load_trades(prof):
        s = sig.get(str(t["hash"]))
        if not s:
            continue
        e, st = float(s.get("entry") or 0), float(s.get("stop") or 0)
        r = abs(e - st)
        if r <= 0 or e <= 0:
            continue
        long = str(s.get("direction")) == "LONG"
        sw = float(s.get("htf_sweep_level") or 0)
        bh, bl = s.get("base_high"), s.get("base_low")
        cbt = pd.Timestamp(str(s.get("confirm_bar_time")))
        a = anchor_of(cbt, main_min)
        q = s.get("quality") or {}
        row = {
            "prof": prof, "sym": t["sym"], "year": int(t["year"]),
            "dir": t["dir"], "anchor": a,
            "hash": str(t["hash"]), "entry": e, "stop": st,
            "stop_pct": float(t["stop_pct"]),
            "sweep_depth": abs(sw - e) / r,
            "prior_touches": s.get("prior_touches"),
            "start_range_atr": q.get("start_range_atr"),
            "quality_score": s.get("quality_score"),
            "psl_probability": s.get("psl_probability"),
            "confirm_on_sweep": bool(s.get("confirm_on_sweep")),
            "one_bar": bool(s.get("one_bar_sweep_cisd")),
            "htf_frac": (a - pd.Timestamp(str(s.get("htf_time")))) / pd.Timedelta(minutes=htf_min),
            "sw2cf_bars": (cbt - pd.Timestamp(str(s.get("trigger_bar_time"))))
            / pd.Timedelta(minutes=main_min),
            "hour": a.hour,
            "is_sl": 1.0 if t["out_1.0"] == "sl" else 0.0,
            "is_tp": 1.0 if t["out_1.0"] == "tp" else 0.0,
            "net": float(t["r_1.0"]) - float(t["fee_mix"]),
            "mfe": float(t["mfe_r"]), "mae": float(t["mae_r"]),
        }
        if bh is not None and bl is not None:
            w = abs(float(bh) - float(bl))
            row["base_w"] = w / r
            if w > 0:
                row["entry_in_base"] = ((e - float(bl)) / w if long
                                        else (float(bh) - e) / w)
        rows.append(row)
    return pd.DataFrame(rows)


def grad(d: pd.DataFrame, col: str, q: int = 5) -> tuple[float, float, float, int]:
    """Δnet и ΔSL между крайними квинтилями + t-стат по net."""
    d = d[d[col].notna()]
    if len(d) < 400:
        return np.nan, np.nan, np.nan, len(d)
    try:
        b = pd.qcut(d[col].astype(float), q, labels=False, duplicates="drop")
    except ValueError:
        return np.nan, np.nan, np.nan, len(d)
    lo, hi = d[b == b.min()], d[b == b.max()]
    dn = hi.net.mean() - lo.net.mean()
    se = np.sqrt(hi.net.var() / len(hi) + lo.net.var() / len(lo))
    return dn, dn / se if se > 0 else np.nan, hi.is_sl.mean() - lo.is_sl.mean(), len(d)


def part_a(tabs: dict[str, pd.DataFrame]) -> None:
    cols = ["stop_pct", "sweep_depth", "base_w", "entry_in_base", "prior_touches",
            "start_range_atr", "quality_score", "psl_probability",
            "htf_frac", "sw2cf_bars", "hour"]
    print("A. Признак против стопов: Δnet (t) между крайними квинтилями по профилям")
    print("   одинаковый знак на всех четырёх = свойство сетапа, а не эпохи\n")
    print("   " + "признак".ljust(17) + "".join(p.rjust(16) for p in PROF) + "   вердикт")
    for c in cols:
        line, signs = "   " + c.ljust(17), []
        for p in PROF:
            dn, t, dsl, n = grad(tabs[p], c)
            if np.isnan(dn):
                line += "—".rjust(16)
                signs.append(0)
            else:
                line += f"{dn:+.3f}({t:+.1f})".rjust(16)
                signs.append(np.sign(dn) if abs(t) >= 2 else 0)
        ok = len({s for s in signs if s != 0}) == 1 and all(s != 0 for s in signs)
        line += "   ЕДИНЫЙ" if ok else ""
        print(line)

    print("\n   булевы классы (доля SL / net R):")
    for c in ("confirm_on_sweep", "one_bar"):
        print(f"   {c}:")
        for p in PROF:
            d = tabs[p]
            a, b = d[d[c]], d[~d[c]]
            if len(a) < 50:
                print(f"     {p}: мало случаев ({len(a)})")
                continue
            print(f"     {p}: True n={len(a):5d} SL={a.is_sl.mean():.3f} net={a.net.mean():+.4f}"
                  f" | False n={len(b):5d} SL={b.is_sl.mean():.3f} net={b.net.mean():+.4f}")

    print("\n   направление:")
    for p in PROF:
        d = tabs[p]
        for dr, g in d.groupby("dir"):
            print(f"     {p} {dr:5s} n={len(g):6d} SL={g.is_sl.mean():.3f} "
                  f"net={g.net.mean():+.4f} mfe−mae={g.mfe.mean()-g.mae.mean():+.3f}")


def part_b(tabs: dict[str, pd.DataFrame]) -> None:
    idx = {p: signal_anchors(p) for p in PROF}

    print("\n\nB. Подтверждение другим ТФ (окно назад от якоря, только прошлое)\n")
    for target in ("tf2", "tf8"):
        d = tabs[target]
        print(f"  цель {target}: n={len(d)}, база net={d.net.mean():+.4f}, "
              f"SL={d.is_sl.mean():.3f}")
        for W in (2, 6, 24):
            w = np.timedelta64(W, "h")
            same_cnt = np.zeros(len(d), dtype=int)
            opp_cnt = np.zeros(len(d), dtype=int)
            for src in PROF:
                if src == target:
                    continue
                for i, (sym, dr, a) in enumerate(zip(d.sym, d.dir, d.anchor)):
                    a64 = np.datetime64(a)
                    opp = "SHORT" if dr == "LONG" else "LONG"
                    for side, dst in ((dr, same_cnt), (opp, opp_cnt)):
                        arr = idx[src].get((sym, side))
                        if arr is None:
                            continue
                        dst[i] += int(np.searchsorted(arr, a64, "right")
                                      - np.searchsorted(arr, a64 - w, "left"))
            dd = d.copy()
            dd["same"], dd["opp"] = same_cnt, opp_cnt
            print(f"    окно {W:2d}ч:")
            for lbl, g in (
                ("только согласные", dd[(dd.same > 0) & (dd.opp == 0)]),
                ("только против",    dd[(dd.same == 0) & (dd.opp > 0)]),
                ("и те и те",        dd[(dd.same > 0) & (dd.opp > 0)]),
                ("ничего рядом",     dd[(dd.same == 0) & (dd.opp == 0)]),
            ):
                if len(g) < 30:
                    print(f"      {lbl:17s} n={len(g):5d}  —")
                    continue
                se = g.net.std() / np.sqrt(len(g))
                print(f"      {lbl:17s} n={len(g):5d} SL={g.is_sl.mean():.3f} "
                      f"net={g.net.mean():+.4f}±{se:.4f} mfe−mae={g.mfe.mean()-g.mae.mean():+.3f}")
        print()


if __name__ == "__main__":
    tabs = {}
    for p in PROF:
        tabs[p] = table(p)
        print(f"{p}: {len(tabs[p])} сделок, net {tabs[p].net.mean():+.4f}, "
              f"SL {tabs[p].is_sl.mean():.3f}", flush=True)
    print()
    part_a(tabs)
    part_b(tabs)
    pickle.dump(tabs, open(f"{TPG}/cross_tf_tabs.pkl", "wb"))
