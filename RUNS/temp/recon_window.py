"""Сравнение бэктеста и живого бота на одном окне 16–21.09.2026 + разбор промахов.

Первая сверка считала совпадения по всему прогону (25.08–22.09), поэтому число
сделок бэктеста было несопоставимо с живыми. Здесь режем бэктест по htf_time на
тот же отрезок, что и живые сделки, и сравниваем размер популяции и исходы.

Запуск: python recon_window.py
"""
from __future__ import annotations

import pickle

import pandas as pd

BASE = "D:/PYTHON/cisdbotbybit/RUNS/temp"
LIVE = "D:/PYTHON/cisdbotbybit/RUNS/live_trades_tf8/LIVE_TRADES_tf8_30m-8H.csv"
W0, W1 = pd.Timestamp("2026-09-16"), pd.Timestamp("2026-09-21 08:00")
MISSED = ["Lb01d697c", "L674d0bb5", "Lb61ab375"]


def main() -> None:
    bt = pickle.load(open(f"{BASE}/recon_live_bt.pkl", "rb"))
    live = pd.read_csv(LIVE)
    live["pending_created_at"] = pd.to_datetime(live["pending_created_at"])

    rows = []
    for sym, d in bt.items():
        for t in d["trades"]:
            ht = pd.Timestamp(str(t.get("htf_time")))
            if W0 <= ht <= W1:
                rows.append({"sym": sym, "dir": t["direction"], "kind": t["entry_kind"],
                             "out": t["outcome"], "r": t["r_net"], "sp": t["sp"],
                             "htf": ht, "hash": t["hash"]})
    b = pd.DataFrame(rows)
    print(f"бэктест на окне {W0.date()}..{W1.date()}: сделок {len(b)}")
    print("  исходы:", dict(b.out.value_counts()))
    print(f"  SumR {b.r.sum():+.1f}, AvgR {b.r.mean():+.3f}, "
          f"средний стоп {b.sp.mean()*100:.2f}%")
    print("  по типу входа:", dict(b.kind.value_counts()))
    print("  только LIMIT (как в бою): n=%d AvgR=%+.3f | MARKET: n=%d AvgR=%+.3f"
          % (len(b[b.kind == "LIMIT"]), b[b.kind == "LIMIT"].r.mean(),
             len(b[b.kind == "MARKET"]), b[b.kind == "MARKET"].r.mean()))

    lv = live[live.status != "open"]
    print(f"\nживые на том же окне: закрытых {len(lv)}")
    print("  исходы:", dict(lv.status.str.replace("closed_", "").value_counts()))
    r = lv["pnl_net"] / (lv["pnl_net"].abs().where(lv.status == "closed_sl").mean() or 1)
    print(f"  net {lv.pnl_net.sum():+.2f} USDT при риске 1% на сделку "
          f"≈ {lv.pnl_net.sum()/1.0:+.1f}R на депозит 100 USDT")

    print("\nтри живые сделки, которых нет в сигналах бэктеста:")
    for mid in MISSED:
        t = live[live.id == mid].iloc[0]
        sym = t["symbol_key"]
        lvl, t0 = float(t["cisd_level"]), t["pending_created_at"]
        print(f"\n  {mid} {sym} {t['direction']} уровень {lvl} якорь {t0}")
        cand = []
        for s in bt[sym]["signals"]:
            cbt = pd.Timestamp(str(s.get("confirm_bar_time")))
            a = (cbt + pd.Timedelta(minutes=30)).ceil("5min")
            if abs(a - t0) <= pd.Timedelta(hours=6):
                cand.append((a, s.get("direction"), float(s.get("entry") or 0),
                             float(s.get("htf_sweep_level") or 0), s.get("htf_time")))
        if not cand:
            print("    рядом (±6ч) сигналов вообще нет")
        for a, dr, e, sw, ht in sorted(cand):
            dev = (e - lvl) / lvl * 100
            print(f"    {a} {dr:5s} вход {e:<12.6g} ({dev:+.2f}% от живого) "
                  f"свип {sw:<12.6g} htf {ht}")


if __name__ == "__main__":
    main()
