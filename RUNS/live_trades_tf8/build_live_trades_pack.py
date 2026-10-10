"""Сборка понятного набора живых сделок бота (tf8, 30m→8H, Bybit SHADOW) для анализа другим агентом."""
import json
import shutil
from collections import Counter

import pandas as pd

D = "D:/PYTHON/cisdbotbybit/RUNS/live_trades_tf8"
trades = json.load(open(f"{D}/shadow_trades.json", encoding="utf-8"))
pos = json.load(open(f"{D}/shadow_positions.json", encoding="utf-8"))
events = [json.loads(x) for x in open(f"{D}/trades_2026-09.jsonl", encoding="utf-8").read().strip().split("\n") if x.strip()]

# понятные копии «сырья»
for src, dst in (("shadow_trades.json", "LIVE_raw_shadow_trades.json"),
                 ("shadow_positions.json", "LIVE_raw_shadow_positions.json"),
                 ("trades_2026-09.jsonl", "LIVE_raw_events_journal_2026-09.jsonl")):
    shutil.copyfile(f"{D}/{src}", f"{D}/{dst}")

# открытые позиции: их нет в trades-файле (он только про закрытые) — добавляем из positions
tr_ids = {str(t.get("id")) for t in trades}
extra = [p for p in pos if str(p.get("id")) not in tr_ids and str(p.get("status")) == "open"]
df = pd.DataFrame(trades)
if extra:
    df = pd.concat([df, pd.DataFrame(extra)], ignore_index=True)
cols = ["id", "trade_num", "tf", "symbol_key", "direction", "status", "signal_category",
        "entry_kind", "signal_entry", "cisd_level", "sweep_level", "price_at_creation",
        "entry_price", "stop_price", "tp_price", "contracts",
        "pending_created_at", "entry_time", "exit_time", "close_price", "exit_src",
        "pnl", "fees", "pnl_net", "htf_time", "sig_hash"]
for c in cols:
    if c not in df.columns:
        df[c] = None
df = df[cols].sort_values("entry_time")
df.to_csv(f"{D}/LIVE_TRADES_tf8_30m-8H.csv", index=False, encoding="utf-8")

closed = df[df.status.astype(str).str.startswith("closed")]
open_ = df[~df.status.astype(str).str.startswith("closed")]
t0 = str(df.entry_time.min())[:16]
t1 = str(df.entry_time.max())[:16]
summ = {
    "период_UTC": f"{t0} → {t1}",
    "всего_сделок": len(df),
    "закрытых": len(closed),
    "открытых": len(open_),
    "исходы": dict(Counter(closed.status)),
    "pnl_net_сумма_USDT": round(float(closed.pnl_net.sum()), 3),
    "fees_сумма_USDT": round(float(closed.fees.sum()), 3),
    "WR_TP_vs_SL": f"{100*int((closed.status=='closed_tp').sum())/max(1,int((closed.status=='closed_tp').sum())+int((closed.status=='closed_sl').sum())):.1f}%",
    "по_ногам": {k: int(v) for k, v in Counter(closed.direction).items()},
    "по_парам": {k: int(v) for k, v in Counter(closed.symbol_key).items()},
    "ср_стоп_%": round(float(((closed.stop_price - closed.entry_price).abs() / closed.entry_price * 100).mean()), 3),
    "события_в_журнале": len(events),
    "типы_событий": dict(Counter(e.get("event") for e in events)),
    "позиций_в_истории": len(pos),
}
json.dump(summ, open(f"{D}/LIVE_TRADES_tf8_summary.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(json.dumps(summ, ensure_ascii=False, indent=2))
