"""
calendar.py

Acceso al calendario de macOS usando AppleScript.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta
from typing import Any, Dict


def calendar_query(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Consulta eventos del calendario de macOS.

    Args:
        args: dict con claves:
            - "action": "today", "tomorrow", "week", "create"
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
            
            # Crear recordatorio en la app Recordatorios
            script = f'''
            tell application "Reminders"
                tell list "Reminders"
                    make new reminder with properties {{name:"{query}"}}
                end tell
            end tell
            return "✅ Recordatorio creado: {query}"
            '''
        
        else:
            return {
                "ok": False,
                "error": f"Acción desconocida: {action}. Usa: today, tomorrow, week, create"
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
