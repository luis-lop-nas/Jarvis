"""
datetime_tool.py

Tool: datetime
Información de fecha y hora actual, con zona horaria.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict

# Nombres de días y meses en español
_DAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def run_datetime(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Args:
      - format: "full" (detallado) | "time" (solo hora) | "date" (solo fecha) | "timestamp" (unix)
        Default: "full"

    Returns: dict con fecha y hora en múltiples formatos.
    """
    fmt = str(args.get("format", "full")).lower().strip()

    now = datetime.now()
    utcnow = datetime.utcnow()

    # Timezone local
    tz_offset_sec = -time.timezone if time.daylight == 0 else -time.altzone
    tz_hours = tz_offset_sec // 3600
    tz_str = f"UTC{'+' if tz_hours >= 0 else ''}{tz_hours:d}"

    day_name = _DAYS_ES[now.weekday()]
    month_name = _MONTHS_ES[now.month - 1]

    result: Dict[str, Any] = {"ok": True, "format": fmt}

    if fmt in ("full", "time"):
        result["time"] = now.strftime("%H:%M:%S")
        result["time_12h"] = now.strftime("%I:%M %p")

    if fmt in ("full", "date"):
        result["date"] = now.strftime("%Y-%m-%d")
        result["date_human"] = f"{day_name} {now.day} de {month_name} de {now.year}"
        result["day_of_week"] = day_name
        result["day"] = now.day
        result["month"] = now.month
        result["month_name"] = month_name
        result["year"] = now.year
        result["week_number"] = now.isocalendar()[1]
        result["day_of_year"] = now.timetuple().tm_yday

    if fmt == "full":
        result["datetime"] = now.strftime("%Y-%m-%d %H:%M:%S")
        result["timezone"] = tz_str
        result["timezone_name"] = time.tzname[time.daylight]
        result["utc"] = utcnow.strftime("%Y-%m-%d %H:%M:%S")

    if fmt == "timestamp":
        result["unix_timestamp"] = int(now.timestamp())
        result["iso_8601"] = now.isoformat()

    return result
