"""
routines.py

Gestión del horario y rutinas personales del usuario.
Fichero fuente: data/routines.json (editable manualmente o por Jarvis vía voz).

Estructura del JSON:
{
  "version": "1.0",
  "schedule": {
    "monday": ["Gimnasio 8:00", "Clase Electro 16:00"],
    "tuesday": [...],
    ...
  },
  "daily_routines": ["Revisar email", "Meditación 10min"],
  "notes": "..."
}
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# jarvis-agent/src/jarvis/tools/routines.py → parents[3] = jarvis-agent/
_ROUTINES_FILE = Path(__file__).resolve().parents[3] / "data" / "routines.json"

_DAY_NAMES_ES = {
    "monday": "lunes", "tuesday": "martes", "wednesday": "miércoles",
    "thursday": "jueves", "friday": "viernes", "saturday": "sábado", "sunday": "domingo"
}
_WEEKDAY_KEYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _read_routines() -> Dict[str, Any]:
    if not _ROUTINES_FILE.exists():
        return {"version": "1.0", "schedule": {}, "daily_routines": []}
    try:
        return json.loads(_ROUTINES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"version": "1.0", "schedule": {}, "daily_routines": []}


def _write_routines(data: Dict[str, Any]) -> None:
    _ROUTINES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _ROUTINES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_routines_for_today() -> List[str]:
    """Retorna la lista de rutinas/actividades para el día de hoy."""
    data = _read_routines()
    today_key = _WEEKDAY_KEYS[datetime.now().weekday()]
    today_items: List[str] = list(data.get("schedule", {}).get(today_key, []))
    daily: List[str] = list(data.get("daily_routines", []))
    return today_items + daily


def routines_tool(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Gestiona el horario y rutinas personales.

    Acciones:
    - "get"         → obtiene rutinas de hoy (o del día especificado en "day")
    - "set_day"     → reemplaza las rutinas de un día ("day", "items": ["...", ...])
    - "add"         → añade una rutina a un día ("day", "item") o a las diarias ("daily": true)
    - "remove"      → elimina una rutina de un día ("day", "item") o de las diarias
    - "list_all"    → muestra todo el horario semanal
    """
    action = str(args.get("action", "get")).lower().strip()
    data = _read_routines()
    schedule = data.setdefault("schedule", {})
    daily = data.setdefault("daily_routines", [])

    if action == "get":
        day_key = str(args.get("day", "")).lower().strip()
        if not day_key or day_key == "today":
            day_key = _WEEKDAY_KEYS[datetime.now().weekday()]
        items = list(schedule.get(day_key, [])) + list(daily)
        day_es = _DAY_NAMES_ES.get(day_key, day_key)
        if not items:
            return {"ok": True, "result": f"No tienes rutinas registradas para {day_es}."}
        formatted = "\n".join(f"  • {i}" for i in items)
        return {"ok": True, "result": f"Rutinas del {day_es}:\n{formatted}"}

    elif action == "set_day":
        day_key = str(args.get("day", "")).lower().strip()
        items = args.get("items", [])
        if not day_key or day_key not in _WEEKDAY_KEYS:
            return {"ok": False, "error": f"Día no válido: {day_key}. Usa: {', '.join(_WEEKDAY_KEYS)}"}
        schedule[day_key] = [str(i).strip() for i in items]
        _write_routines(data)
        day_es = _DAY_NAMES_ES[day_key]
        return {"ok": True, "result": f"Rutinas del {day_es} actualizadas ({len(items)} elementos)."}

    elif action == "add":
        item = str(args.get("item", "")).strip()
        if not item:
            return {"ok": False, "error": "Falta 'item' con la rutina a añadir."}
        if args.get("daily"):
            if item not in daily:
                daily.append(item)
                data["daily_routines"] = daily
                _write_routines(data)
            return {"ok": True, "result": f"Rutina diaria añadida: «{item}»"}
        day_key = str(args.get("day", "")).lower().strip()
        if not day_key or day_key == "today":
            day_key = _WEEKDAY_KEYS[datetime.now().weekday()]
        day_items = schedule.setdefault(day_key, [])
        if item not in day_items:
            day_items.append(item)
            _write_routines(data)
        day_es = _DAY_NAMES_ES.get(day_key, day_key)
        return {"ok": True, "result": f"Añadido al {day_es}: «{item}»"}

    elif action == "remove":
        item = str(args.get("item", "")).strip()
        if not item:
            return {"ok": False, "error": "Falta 'item' con la rutina a eliminar."}
        removed = False
        if args.get("daily"):
            if item in daily:
                daily.remove(item)
                data["daily_routines"] = daily
                _write_routines(data)
                removed = True
        else:
            day_key = str(args.get("day", "")).lower().strip()
            if not day_key or day_key == "today":
                day_key = _WEEKDAY_KEYS[datetime.now().weekday()]
            day_items = schedule.get(day_key, [])
            if item in day_items:
                day_items.remove(item)
                _write_routines(data)
                removed = True
        msg = f"Eliminado: «{item}»" if removed else f"No encontré «{item}» para eliminar."
        return {"ok": True, "result": msg}

    elif action == "list_all":
        lines = []
        for key in _WEEKDAY_KEYS:
            items = schedule.get(key, [])
            day_es = _DAY_NAMES_ES[key]
            if items:
                lines.append(f"{day_es.capitalize()}: {', '.join(items)}")
            else:
                lines.append(f"{day_es.capitalize()}: libre")
        if daily:
            lines.append(f"Diario: {', '.join(daily)}")
        return {"ok": True, "result": "\n".join(lines)}

    return {"ok": False, "error": f"Acción desconocida: {action}. Usa: get, set_day, add, remove, list_all"}
