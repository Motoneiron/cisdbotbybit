"""Синтетика: PAPER SL/TP не срабатывает по бару, закрытому до входа."""
import importlib.util
import sys
from datetime import datetime

sys.path.insert(0, r"D:/PYTHON/cisdbotbybit")

spec = importlib.util.spec_from_file_location("cisdbot_mod", "D:/PYTHON/cisdbotbybit/cisdbot.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def _pos(**kw):
    p = m.Position(
        pos_id="t1",
        direction=kw.get("direction", "LONG"),
        entry_price=kw.get("entry_price", 100),
        stop_price=kw.get("stop_price", 99),
        tp_price=kw.get("tp_price", 110),
        contracts=1,
        entry_time=kw.get("entry_time", datetime(2026, 9, 16, 10, 5, 0)),
        exit_time=datetime(2026, 9, 16, 14, 5, 0),
        tf="tf8",
        trade_num=1,
    )
    p.closed_bar_at = kw.get("closed_bar_at", "2026-09-16 10:00:00")
    p.px_min_since_entry = kw.get("px_min", 100.0)
    p.px_max_since_entry = kw.get("px_max", 100.0)
    return p


failed = 0


def check(name, cond, detail=""):
    global failed
    mark = "OK" if cond else "FAIL"
    if not cond:
        failed += 1
    extra = f"  {detail}" if detail else ""
    print(f"{mark}: {name}{extra}")


# 1) бар, уже закрытый на входе → SL не срабатывает (кейс ADA)
p = _pos()
cached_old = {"time": "2026-09-16 10:00:00", "low": 98.5, "high": 101.0}
check("gate старый бар", m._shadow_ohlc_usable_for_position(p, cached_old) is False)
tp, sl, src, bar_t = m._paper_position_level_hits(p, 100.5, cached_old)
check("SL по старому бару выключен", sl is False and tp is False, f"sl={sl} src={src}")

# 2) бар целиком после входа → SL срабатывает
cached_new = {"time": "2026-09-16 10:30:00", "low": 98.5, "high": 101.0}
check("gate новый бар", m._shadow_ohlc_usable_for_position(p, cached_new) is True)
tp, sl, src, bar_t = m._paper_position_level_hits(p, 100.5, cached_new)
check("SL по новому бару", sl is True and src == "bar", f"sl={sl} src={src} bar_t={bar_t}")
check("exit_bar_time нового бара", bar_t == "2026-09-16 10:30:00")

# 3) экстремум live с момента входа → SL, живая цена ещё не у стопа
p3 = _pos(px_min=98.9, px_max=100.5)
tp, sl, src, bar_t = m._paper_position_level_hits(p3, 100.5, cached_old)
check("SL по px_min_since_entry", sl is True and src == "since_entry", f"sl={sl} src={src}")

# 4) старая запись без closed_bar_at → OHLC выключена
p4 = _pos()
p4.closed_bar_at = ""
check("gate без closed_bar_at", m._shadow_ohlc_usable_for_position(p4, cached_old) is False)
tp, sl, src, bar_t = m._paper_position_level_hits(p4, 100.5, cached_old)
check("нет ложного SL без closed_bar_at", sl is False, f"sl={sl} src={src}")

# ADA-подобный: 30m бар 02:00, вход 02:43, low = стоп
ada = _pos(
    entry_price=0.1946,
    stop_price=0.1921,
    tp_price=0.1990,
    entry_time=datetime(2026, 9, 16, 2, 43, 53),
    closed_bar_at="2026-09-16 02:00:00",
    px_min=0.1937,
    px_max=0.1946,
)
ada_bar = {"time": "2026-09-16 02:00:00", "low": 0.1921, "high": 0.1950}
tp, sl, src, bar_t = m._paper_position_level_hits(ada, 0.1940, ada_bar)
check("ADA: нет мгновенного SL по бару до входа", sl is False, f"sl={sl} src={src}")

# roundtrip to_dict / from_dict
d = p3.to_dict()
check("to_dict closed_bar_at", d.get("closed_bar_at") == "2026-09-16 10:00:00")
check("to_dict px_min", d.get("px_min_since_entry") == 98.9)
p3.exit_src = "since_entry"
p3.exit_bar_time = None
d2 = p3.to_dict()
restored = m.Position.from_dict(d2)
check("from_dict closed_bar_at", restored.closed_bar_at == "2026-09-16 10:00:00")
check("from_dict px_min", restored.px_min_since_entry == 98.9)
check("from_dict exit_src", restored.exit_src == "since_entry")

rec = m._position_journal_record(p3, event="closed")
check("journal exit_src", rec.get("exit_src") == "since_entry")
check("journal exit_bar_time ключ есть", "exit_bar_time" in rec)

# старый dict без новых полей не падает
legacy = p.to_dict()
legacy.pop("closed_bar_at", None)
legacy.pop("px_min_since_entry", None)
legacy.pop("px_max_since_entry", None)
legacy.pop("exit_src", None)
legacy.pop("exit_bar_time", None)
old = m.Position.from_dict(legacy)
check("legacy from_dict", old.closed_bar_at == "" and old.px_min_since_entry == 0.0)

if failed:
    print(f"\nFAILED: {failed}")
    sys.exit(1)
print("\nALL OK")
