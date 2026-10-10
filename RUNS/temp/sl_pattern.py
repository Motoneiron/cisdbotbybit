"""Есть ли общий признак у стоповых сделок: гипотезы с живых, проверка на 15k базе.

32 закрытые живые сделки статистически ничего не доказывают (14 SL против 10 TP:
разница в один-два случая переворачивает любую метрику). Поэтому порядок такой:
геометрию сетапа считаем одинаково для живых и для честной базы бэктеста, на живых
смотрим направление, а решение принимаем по базе, где 15 382 сделки.

Геометрия (всё в единицах R, R = |вход − стоп|):
  sweep_depth   |уровень свипа − уровень CISD| / R — насколько глубоко вход
                относительно проколотого экстремума
  stop_out      |стоп − уровень свипа| / R со знаком: >0 стоп ЗА экстремумом,
                <0 стоп внутри (цене достаточно вернуться к свипу, чтобы выбить)
  base_w        |base_high − base_low| / R — ширина структурной базы
  entry_in_base где вход внутри базы: 0 = на дальнем крае, 1 = на ближнем
  lag_min       минуты от постановки лимитки до заполнения (только живые)
  gap_r         (цена при постановке − вход) / R со знаком: сколько цене надо
                пройти до уровня
  htf_age_h     часов от начала 8H-бара до входа

Запуск: python sl_pattern.py
"""
from __future__ import annotations

import glob
import pickle

import numpy as np
import pandas as pd

BASE = "D:/PYTHON/cisdbotbybit/RUNS/temp"
ALIGNED = "D:/PYTHON/CISDBOT/RUNS/filters_off_full_aligned"
LIVE = "D:/PYTHON/cisdbotbybit/RUNS/live_trades_tf8/LIVE_TRADES_tf8_30m-8H.csv"
PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]


def geom(direction: str, entry: float, stop: float, sweep: float,
         base_hi: float | None, base_lo: float | None) -> dict:
    r = abs(entry - stop)
    if r <= 0 or not np.isfinite(r):
        return {}
    sgn = 1.0 if direction == "LONG" else -1.0
    out = {
        "stop_pct": r / entry * 100.0,
        "sweep_depth": abs(sweep - entry) / r,
        # для LONG свип снизу: стоп должен быть НИЖЕ свипа ⇒ (sweep − stop)/r
        "stop_out": (sweep - stop) / r if sgn > 0 else (stop - sweep) / r,
    }
    if base_hi is not None and base_lo is not None and np.isfinite(base_hi) and np.isfinite(base_lo):
        w = abs(base_hi - base_lo)
        out["base_w"] = w / r
        if w > 0:
            out["entry_in_base"] = (
                (entry - base_lo) / w if sgn > 0 else (base_hi - entry) / w
            )
    return out


def live_table() -> pd.DataFrame:
    d = pd.read_csv(LIVE)
    d = d[d.status != "open"].copy()
    d["pending_created_at"] = pd.to_datetime(d["pending_created_at"])
    d["entry_time"] = pd.to_datetime(d["entry_time"])
    d["htf_time"] = pd.to_datetime(d["htf_time"])
    rows = []
    for _, t in d.iterrows():
        g = geom(t["direction"], float(t["entry_price"]), float(t["stop_price"]),
                 float(t["sweep_level"]), None, None)
        r = abs(float(t["entry_price"]) - float(t["stop_price"]))
        sgn = 1.0 if t["direction"] == "LONG" else -1.0
        g.update({
            "id": t["id"], "sym": t["symbol_key"], "dir": t["direction"],
            "outcome": t["status"].replace("closed_", ""),
            "lag_min": (t["entry_time"] - t["pending_created_at"]).total_seconds() / 60,
            "gap_r": sgn * (float(t["price_at_creation"]) - float(t["entry_price"])) / r,
            "htf_age_h": (t["entry_time"] - t["htf_time"]).total_seconds() / 3600,
            "hour": t["entry_time"].hour,
            "pnl_net": float(t["pnl_net"]),
        })
        rows.append(g)
    return pd.DataFrame(rows)


def base_table() -> pd.DataFrame:
    tr = []
    for sym in PAIRS:
        for f in glob.glob(f"{BASE}/tp_grid/{sym}_*.pkl"):
            tr += [r for r in pickle.load(open(f, "rb")) if r.get("hold") == 6]
    t = pd.DataFrame(tr)
    sig = {}
    for sym in PAIRS:
        for f in glob.glob(f"{ALIGNED}/{sym}_tf8_*.pkl"):
            for s in pickle.load(open(f, "rb")).get("signals") or []:
                sig[str(s.get("hash"))] = s
    rows = []
    for h in t["hash"]:
        s = sig.get(str(h))
        if not s:
            rows.append({"hash": h})
            continue
        g = geom(str(s.get("direction")), float(s.get("entry") or 0),
                 float(s.get("stop") or 0), float(s.get("htf_sweep_level") or 0),
                 s.get("base_high"), s.get("base_low"))
        g["hash"] = h
        g["prior_touches"] = s.get("prior_touches")
        g["late_retest"] = s.get("late_retest")
        g["confirm_on_sweep"] = s.get("confirm_on_sweep")
        q = s.get("quality") or {}
        g["start_range_atr"] = q.get("start_range_atr")
        cbt = pd.Timestamp(str(s.get("confirm_bar_time")))
        htf = pd.Timestamp(str(s.get("htf_time")))
        g["htf_age_h"] = (cbt + pd.Timedelta(minutes=30) - htf).total_seconds() / 3600
        g["hour"] = (cbt + pd.Timedelta(minutes=30)).hour
        trig = pd.Timestamp(str(s.get("trigger_bar_time")))
        g["sweep_to_confirm_h"] = (cbt - trig).total_seconds() / 3600
        rows.append(g)
    # stop_pct уже есть в tp_grid — свой не тащим, иначе merge даст _x/_y
    g = pd.DataFrame(rows).drop(columns=["stop_pct"], errors="ignore")
    df = t.merge(g, on="hash", how="left")
    df["is_sl"] = (df["out_1.0"] == "sl").astype(float)
    df["net"] = df["r_1.0"] - df["fee_mix"]
    return df


def cmp_live(d: pd.DataFrame, cols: list[str]) -> None:
    print("живые сделки: средние по исходу (n в скобках)")
    grp = d.groupby("outcome")
    hdr = "  " + "фича".ljust(16) + "".join(f"{k}({len(v):2d})".rjust(12) for k, v in grp)
    print(hdr)
    for c in cols:
        line = "  " + c.ljust(16)
        for _, v in grp:
            line += f"{v[c].mean():+12.3f}"
        print(line)


def screen_base(df: pd.DataFrame, col: str, q: int = 5) -> None:
    d = df[df[col].notna()]
    if len(d) < 500:
        print(f"  {col:18s} мало данных ({len(d)})")
        return
    try:
        b = pd.qcut(d[col].astype(float), q, labels=False, duplicates="drop")
    except ValueError:
        print(f"  {col:18s} не делится")
        return
    parts = []
    for k in sorted(pd.unique(b)):
        g = d[b == k]
        parts.append(f"{g.is_sl.mean():.3f}/{g.net.mean():+.3f}")
    lo, hi = d[b == b.min()], d[b == b.max()]
    diff = hi.net.mean() - lo.net.mean()
    sd = np.sqrt(hi.net.var() / len(hi) + lo.net.var() / len(lo))
    print(f"  {col:18s} n={len(d):5d} Δnet={diff:+.3f} t={diff/sd:+.1f} | " + "  ".join(parts))


if __name__ == "__main__":
    lv = live_table()
    cols = ["stop_pct", "sweep_depth", "stop_out", "lag_min", "gap_r", "htf_age_h", "hour"]
    print(f"живых закрытых: {len(lv)} "
          f"({(lv.outcome=='tp').sum()} TP / {(lv.outcome=='sl').sum()} SL / "
          f"{(lv.outcome=='time').sum()} TIME)\n")
    cmp_live(lv, cols)

    print("\nчестная база бэктеста: квинтили фичи → доля SL / net R\n")
    df = base_table()
    print(f"  сделок {len(df)}, доля SL {df.is_sl.mean():.3f}, net {df.net.mean():+.4f}\n")
    for c in ["stop_pct", "sweep_depth", "stop_out", "base_w", "entry_in_base",
              "prior_touches", "start_range_atr", "htf_age_h", "sweep_to_confirm_h", "hour"]:
        screen_base(df, c)
    for c in ["late_retest", "confirm_on_sweep"]:
        d = df[df[c].notna()]
        print(f"\n  {c}:")
        for v, g in d.groupby(c):
            print(f"    {str(v):6s} n={len(g):5d} SL={g.is_sl.mean():.3f} net={g.net.mean():+.4f}")
    lv.to_csv(f"{BASE}/sl_pattern_live.csv", index=False)
