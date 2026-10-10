"""Пометить позиции, удалённые из статистики, статусом voided_invalid_setup.

Запускать при ОСТАНОВЛЕННОМ боте (иначе работающий процесс перезапишет файл из памяти).
"""
import json
from pathlib import Path

BASE = Path("/opt/cisdbotbybit")
IDS = {
    "Lda3dab24": "DOGE: свип не подтверждён (триггер не экстремум окна)",
    "L8fd48273": "LINK: свип не подтверждён (триггер не экстремум окна)",
    "Lc4cb392b": "ETH: свип не подтверждён (триггер не экстремум окна)",
    "L4b526ad9": "XRP: цена при создании уже за уровнем (неявный MARKET)",
    "L0bae85a6": "BNB: в окне сетапа не было 30m-закрытия за уровнем",
    "L14c5f5b1": "ADA: окно свипа закрылось ниже уровня",
    "L738ecc5e": "KAS: окно свипа закрылось ниже уровня",
    "L3c6a10b1": "LTC: окно свипа закрылось ниже уровня",
}

f = BASE / "shadow_positions.json"
pos = json.loads(f.read_text(encoding="utf-8"))
n = 0
for p in pos:
    if p.get("id") in IDS and str(p.get("status", "")).startswith("closed"):
        p["status"] = "voided_invalid_setup"
        p["void_reason"] = IDS[p["id"]]
        p["void_at"] = "2026-09-16T22:15:00"
        n += 1
f.write_text(json.dumps(pos, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"помечено: {n}")
print("осталось closed_*:", sum(1 for p in pos if str(p.get("status", "")).startswith("closed")))
