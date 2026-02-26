"""
calendar.py

Acceso al calendario de macOS usando AppleScript.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from typing import Any, Dict


def _escape_applescript_text(value: str) -> str:
    return (value or "").replace("\\", "\\\\").replace('"', '\\"')


def create_calendar_event(
    *,
    title: str,
    due_date: str,
    due_time: str = "09:00",
    duration_minutes: int = 60,
    notes: str = "",
) -> Dict[str, Any]:
    title = str(title or "").strip()
    if not title:
        return {"ok": False, "error": "Título de evento vacío"}

    try:
        dt = datetime.strptime(f"{due_date} {due_time}", "%Y-%m-%d %H:%M")
    except ValueError:
        return {"ok": False, "error": "Fecha/hora inválida (usa YYYY-MM-DD y HH:MM)"}

    safe_title = _escape_applescript_text(title)
    safe_notes = _escape_applescript_text(notes or "")
    duration_minutes = max(5, int(duration_minutes))

    script = f'''
    set startDate to current date
    set year of startDate to {dt.year}
    set month of startDate to {dt.month}
    set day of startDate to {dt.day}
    set time of startDate to ({dt.hour} * hours + {dt.minute} * minutes)
    set endDate to startDate + ({duration_minutes} * minutes)

    tell application "Calendar"
        set targetCalendar to first calendar
        tell targetCalendar
            make new event with properties {{summary:"{safe_title}", start date:startDate, end date:endDate, description:"{safe_notes}"}}
        end tell
    end tell

    return "✅ Evento creado: {safe_title}"
    '''

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr.strip() or "Error creando evento"}
        return {"ok": True, "result": result.stdout.strip() or "Evento creado"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Timeout creando evento de calendario"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def get_calendar_events_today() -> list:
    """
    Lee eventos de Calendar.app para hoy.
    Retorna lista de strings "HH:MM - Nombre evento" ordenados por hora.
    Retorna [] si hay error o no hay eventos.
    """
    script = '''
    tell application "Calendar"
        set todayStart to current date
        set time of todayStart to 0
        set todayEnd to todayStart + (1 * days)
        set output to ""
        set eventList to {}
        repeat with cal in calendars
            set calEvents to (every event of cal whose start date >= todayStart and start date < todayEnd)
            set eventList to eventList & calEvents
        end repeat
        repeat with evt in eventList
            set h to hours of start date of evt
            set m to minutes of start date of evt
            set mStr to m as string
            if m < 10 then set mStr to "0" & mStr
            set output to output & (h as string) & ":" & mStr & "|||" & summary of evt & "~~~"
        end repeat
        return output
    end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        events = []
        for chunk in result.stdout.strip().split("~~~"):
            chunk = chunk.strip()
            if "|||" in chunk:
                time_str, name = chunk.split("|||", 1)
                events.append(f"{time_str.strip()} - {name.strip()}")
        events.sort()
        return events
    except Exception:
        return []


def get_reminders_today() -> list:
    """
    Lee recordatorios pendientes de Reminders.app.
    - Con fecha: los que vencen hoy o están atrasados (due <= fin de hoy)
    - Sin fecha: hasta 3 (los más recientes, como backlog)
    Retorna [] si hay error.
    """
    script = '''
    tell application "Reminders"
        set todayEnd to current date
        set time of todayEnd to (23 * hours + 59 * minutes + 59)
        set datedOut to ""
        set undatedOut to ""
        set undatedCount to 0
        repeat with aList in lists
            try
                repeat with r in (every reminder of aList whose completed is false)
                    try
                        set d to due date of r
                        if d <= todayEnd then
                            set datedOut to datedOut & (name of r) & "~~~"
                        end if
                    on error
                        if undatedCount < 3 then
                            set undatedOut to undatedOut & (name of r) & "~~~"
                            set undatedCount to undatedCount + 1
                        end if
                    end try
                end repeat
            end try
        end repeat
        return datedOut & "|||UNDATED|||" & undatedOut
    end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        raw = result.stdout.strip()
        dated_part, _, undated_part = raw.partition("|||UNDATED|||")
        reminders = []
        for chunk in dated_part.split("~~~"):
            chunk = chunk.strip()
            if chunk:
                reminders.append(chunk)
        for chunk in undated_part.split("~~~"):
            chunk = chunk.strip()
            if chunk:
                reminders.append(chunk)
        return reminders
    except Exception:
        return []


def calendar_query(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Consulta eventos del calendario de macOS.

    Args:
        args: dict con claves:
            - "action": "today", "tomorrow", "week", "create", "create_event"
            - "query": texto para búsqueda o título del recordatorio

    Returns:
        Dict con ok, result o error
    """
    action = str(args.get("action", "today")).lower().strip()
    query = str(args.get("query", ""))
    
    try:
        if action == "today":
            script = '''
            tell application "Calendar"
                set todayStart to current date
                set time of todayStart to 0
                set todayEnd to todayStart + (1 * days)
                
                set eventList to {}
                repeat with cal in calendars
                    set calEvents to (every event of cal whose start date ≥ todayStart and start date < todayEnd)
                    set eventList to eventList & calEvents
                end repeat
                
                if (count of eventList) = 0 then
                    return "📅 No hay eventos hoy"
                end if
                
                set output to "📅 Eventos de hoy:
"
                repeat with evt in eventList
                    set eventTime to time string of start date of evt
                    set eventName to summary of evt
                    set output to output & "  • " & eventTime & " - " & eventName & "
"
                end repeat
                
                return output
            end tell
            '''
        
        elif action == "tomorrow":
            script = '''
            tell application "Calendar"
                set tomorrowStart to (current date) + (1 * days)
                set time of tomorrowStart to 0
                set tomorrowEnd to tomorrowStart + (1 * days)
                
                set eventList to {}
                repeat with cal in calendars
                    set calEvents to (every event of cal whose start date ≥ tomorrowStart and start date < tomorrowEnd)
                    set eventList to eventList & calEvents
                end repeat
                
                if (count of eventList) = 0 then
                    return "📅 No hay eventos mañana"
                end if
                
                set output to "📅 Eventos de mañana:
"
                repeat with evt in eventList
                    set eventTime to time string of start date of evt
                    set eventName to summary of evt
                    set output to output & "  • " & eventTime & " - " & eventName & "
"
                end repeat
                
                return output
            end tell
            '''
        
        elif action == "week":
            script = '''
            tell application "Calendar"
                set weekStart to current date
                set time of weekStart to 0
                set weekEnd to weekStart + (7 * days)
                
                set eventList to {}
                repeat with cal in calendars
                    set calEvents to (every event of cal whose start date ≥ weekStart and start date < weekEnd)
                    set eventList to eventList & calEvents
                end repeat
                
                if (count of eventList) = 0 then
                    return "📅 No hay eventos esta semana"
                end if
                
                set output to "📅 Eventos de esta semana: " & (count of eventList) & " eventos
"
                
                return output
            end tell
            '''
        
        elif action == "create":
            if not query:
                return {
                    "ok": False,
                    "error": "Necesito un título para el recordatorio"
                }
            safe_query = _escape_applescript_text(query)
            
            # Crear recordatorio en la app Recordatorios
            script = f'''
            tell application "Reminders"
                tell list "Reminders"
                    make new reminder with properties {{name:"{safe_query}"}}
                end tell
            end tell
            return "✅ Recordatorio creado: {safe_query}"
            '''

        elif action == "create_event":
            return create_calendar_event(
                title=query,
                due_date=str(args.get("date", "")).strip(),
                due_time=str(args.get("time", "09:00")).strip() or "09:00",
                duration_minutes=int(args.get("duration_minutes", 60)),
                notes=str(args.get("notes", "")),
            )
        
        else:
            return {
                "ok": False,
                "error": (
                    f"Acción desconocida: {action}. Usa: "
                    "today, tomorrow, week, create, create_event"
                )
            }
        
        # Ejecutar AppleScript
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=15,
        )
        
        if result.returncode != 0:
            return {
                "ok": False,
                "error": result.stderr.strip() or "Error accediendo al calendario"
            }
        
        output = result.stdout.strip()
        return {
            "ok": True,
            "result": output or "Consulta ejecutada"
        }
    
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Timeout consultando calendario"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
