"""ЯКОРЬ: сверка канонического потока (stream_r1_live.pkl) с кэшами (filters_off_full).

Вопрос: стартует ли окно филла от ЗАКРЫТИЯ конфирм-бара (честно для 30m-confirm)
или раньше (внутри бара = look-ahead)?
Меряем: ts_fill − confirm_bar_time (мин) для tf8. Если < 30 — филл внутри конфирм-бара.
"""
import glob
import pickle

import pandas as pd

st = pd.read_pickle("D:/PYTHON/cisdbotbybit/RUNS/temp/stream_r1_live.pkl")
print("поток:", len(st), "| колонки:", [c for c in st.columns if "ts" in c or "wait" in c or "conf" in c])
st = st[st.prof == "tf8"].copy()
st["ts_fill"] = pd.to_datetime(st.get("ts_fill"), errors="coerce")
st["from_ts"] = pd.to_datetime(st.get("from_ts"), errors="coerce")
st["decision_at"] = pd.to_datetime(st.get("decision_at"), errors="coerce")

# карта (sym, dir, entry) -> confirm_bar_time из кэшей
cbt = {}
for f in sorted(glob.glob("D:/PYTHON/CISDBOT/RUNS/filters_off_full/*_tf8_*.pkl")):
    c = pickle.load(open(f, "rb"))
    sym = c.get("symbol")
    for s in c.get("signals") or []:
        e = s.get("entry")
        if e is None:
            continue
        cbt[(sym, s.get("direction"), round(float(e), 6))] = str(s.get("confirm_bar_time"))
print("сигналов в кэшах:", len(cbt))

rows = []
for r in st.itertuples():
    key = (r.sym, r.dir, round(float(r.entry), 6))
    c = cbt.get(key)
    if not c:
        continue
    rows.append((r.sym, pd.Timestamp(c), r.from_ts, r.ts_fill, r.decision_at, r.fill_wait_min))
df = pd.DataFrame(rows, columns=["sym", "cbt", "from_ts", "ts_fill", "decision_at", "fill_wait_min"])
print("сопоставлено:", len(df))
df["min_cbt_to_from"] = (df.from_ts - df.cbt).dt.total_seconds() / 60
df["min_cbt_to_fill"] = (df.ts_fill - df.cbt).dt.total_seconds() / 60
df["min_from_to_decision"] = (df.decision_at - df.from_ts).dt.total_seconds() / 60
print()
print("--- from_ts − confirm_bar_time (мин): сколько проходит от ОТКРЫТИЯ конфирм-бара до старта окна ---")
print(df.min_cbt_to_from.describe(percentiles=[0.05, 0.5, 0.95]).round(1).to_string())
print()
print("--- ts_fill − confirm_bar_time (мин): когда реально заполнялись ---")
print(df.min_cbt_to_fill.describe(percentiles=[0.05, 0.25, 0.5, 0.75, 0.95]).round(1).to_string())
print()
inside = (df.min_cbt_to_fill < 30).mean()
print(f"доля филлов ВНУТРИ конфирм-бара 30m (ts_fill − cbt < 30 мин): {100*inside:.1f}%  <-- если >0, окно открыто до закрытия бара")
print(f"доля филлов раньше from_ts: {(df.fill_wait_min < 0).mean()*100:.1f}%")
print()
print("--- примеры ---")
print(df.head(8)[["sym", "cbt", "from_ts", "ts_fill", "min_cbt_to_from", "min_cbt_to_fill"]].to_string(index=False))
print()
print("--- минута from_ts (0/5/10/... — сетка 5м?) ---")
print(df.from_ts.dt.minute.value_counts().sort_index().to_dict())
