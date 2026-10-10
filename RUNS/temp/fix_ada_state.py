"""Разовая правка состояния SHADOW: отменить фантомное закрытие ADA (Lecdf997a).

Сделка реально НЕ закрывалась (стоп 0.1921 не тронут: 1m min после входа = 0.1937).
Позиция возвращается в open, запись о её закрытии убирается из shadow_trades.json
(от неё зависят paper_balance и /stats), в журнал добавляется пометка close_voided.

Значения экстремумов взяты из фактов Bybit 1m: [02:43:53 → 06:05 UTC] min=0.1937 max=0.1967.
"""
import json
import shutil
import datetime
from pathlib import Path

BASE = Path("/opt/cisdbotbybit")
PID = "Lecdf997a"

pos_f = BASE / "shadow_positions.json"
trd_f = BASE / "shadow_trades.json"

# 1. бэкапы
shutil.copy(pos_f, BASE / "shadow_positions.json.bak_pre_adafix")
shutil.copy(trd_f, BASE / "shadow_trades.json.ada_phantom_20260916")

# 2. позиция -> open
positions = json.loads(pos_f.read_text(encoding="utf-8"))
hit = 0
for p in positions:
    if p.get("id") == PID:
        p["status"] = "open"
        for k in ("close_price", "pnl", "fees", "pnl_net"):
            p[k] = None
        p["closed_bar_at"] = "2026-09-16 02:00:00"   # последний закрытый 30m-бар на момент входа
        p["px_min_since_entry"] = 0.1937             # факт 1m Bybit с момента входа
        p["px_max_since_entry"] = 0.1967
        hit += 1
assert hit == 1, f"позиция {PID} не найдена: {hit}"
pos_f.write_text(json.dumps(positions, indent=2, ensure_ascii=False), encoding="utf-8")

# 3. убрать фантомную закрытую сделку (баланс и /stats считаются из этого файла)
trades = json.loads(trd_f.read_text(encoding="utf-8"))
kept = [t for t in trades if t.get("id") != PID]
removed = len(trades) - len(kept)
trd_f.write_text(json.dumps(kept, indent=2, ensure_ascii=False), encoding="utf-8")

# 4. пометка в журнале (история не переписывается, добавляется событие)
jf = BASE / "trade_logs" / "trades_2026-09.jsonl"
note = {
    "event": "close_voided",
    "id": PID,
    "symbol": "ADA",
    "tf": "tf8",
    "direction": "LONG",
    "mode": "shadow",
    "reason": "ложный стоп: экстремум бара 02:00-02:30 (low=0.1921) проторгован ДО входа 02:43:53",
    "fix_commit": "8730b70",
    "position_status": "open",
    "logged_at": datetime.datetime.utcnow().isoformat(),
}
with jf.open("a", encoding="utf-8") as f:
    f.write(json.dumps(note, ensure_ascii=False) + "\n")

print(f"positions: id={PID} -> open (правок: {hit})")
print(f"trades: удалено записей {removed}, осталось {len(kept)}")
print(f"journal: добавлен close_voided в {jf.name}")
