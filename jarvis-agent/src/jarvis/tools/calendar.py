"""
calendar.py

Acceso al calendario de macOS.
- Path rápido: EventKit via PyObjC (<80ms, sin osascript)
- Fallback:    AppleScript (si EventKit no disponible o permisos denegados)
"""

from __future__ import annotations

import subprocess
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

# ── EventKit store (singleton, inicializado lazy) ─────────────────────────────

_store_lock = threading.Lock()
_store: Optional[Any] = None        # EKEventStore
_events_granted: bool = False
_reminders_granted: bool = False


def _get_store() -> Optional[Any]:
    """Devuelve el EKEventStore singleton con permisos de eventos, o None si no disponible."""
    global _store, _events_granted
    with _store_lock:
        if _store is not None:
            return _store if _events_granted else None
        try:
            import EventKit  # type: ignore[import]
            store = EventKit.EKEventStore.alloc().init()
            sem = threading.Semaphore(0)

            def _cb(granted: bool, err: Any) -> None:
                global _events_granted
                _events_granted = bool(granted)
                sem.release()

            # macOS 14+ requiere requestFullAccessToEventsWithCompletion_
            if hasattr(store, "requestFullAccessToEventsWithCompletion_"):
                store.requestFullAccessToEventsWithCompletion_(_cb)
            else:
                store.requestAccessToEntityType_completion_(0, _cb)  # EKEntityTypeEvent = 0

            sem.acquire(timeout=5)
            _store = store
        except Exception:
            _store = None
            _events_granted = False
        return _store if _events_granted else None


def _get_reminders_store() -> Optional[Any]:
    """Devuelve el EKEventStore con permisos de reminders, o None."""
    global _store, _reminders_granted
    with _store_lock:
        if _store is None:
            _get_store.__wrapped__ = True  # fuerza inicialización
        try:
            import EventKit  # type: ignore[import]
            if _store is None:
                return None
            if not _reminders_granted:
                sem = threading.Semaphore(0)

                def _cb_rem(granted: bool, err: Any) -> None:
                    global _reminders_granted
                    _reminders_granted = bool(granted)
                    sem.release()

                if hasattr(_store, "requestFullAccessToRemindersWithCompletion_"):
                    _store.requestFullAccessToRemindersWithCompletion_(_cb_rem)
                else:
                    _store.requestAccessToEntityType_completion_(1, _cb_rem)  # EKEntityTypeReminder = 1
                sem.acquire(timeout=5)
            return _store if _reminders_granted else None
        except Exception:
            return None


# ── EventKit fast path ────────────────────────────────────────────────────────

def _eventkit_events_for_range(start_dt: datetime, end_dt: datetime) -> list:
    """
    Devuelve lista de strings "HH:MM - Nombre" usando EventKit.
    Lanza cualquier excepción si algo falla (el caller hace fallback).
    """
    import EventKit  # type: ignore[import]
    from Foundation import NSDate  # type: ignore[import]

    store = _get_store()
    if store is None:
        raise RuntimeError("EventKit no disponible")

    start_ns = NSDate.dateWithTimeIntervalSince1970_(start_dt.timestamp())
    end_ns = NSDate.dateWithTimeIntervalSince1970_(end_dt.timestamp())

    pred = store.predicateForEventsWithStartDate_endDate_calendars_(start_ns, end_ns, None)
    events = store.eventsMatchingPredicate_(pred)

    results = []
    for evt in events:
        start = evt.startDate()
        ts = start.timeIntervalSince1970()
        dt = datetime.fromtimestamp(ts)
        results.append(f"{dt.hour:02d}:{dt.minute:02d} - {evt.title()}")
    results.sort()
    return results


def _eventkit_create_event(
    title: str,
    start_dt: datetime,
    end_dt: datetime,
    notes: str = "",
) -> Dict[str, Any]:
    """Crea un evento usando EventKit. Lanza excepción si falla."""
    import EventKit  # type: ignore[import]
    from Foundation import NSDate  # type: ignore[import]

    store = _get_store()
    if store is None:
        raise RuntimeError("EventKit no disponible")

    evt = EventKit.EKEvent.eventWithEventStore_(store)
    evt.setTitle_(title)
    evt.setStartDate_(NSDate.dateWithTimeIntervalSince1970_(start_dt.timestamp()))
    evt.setEndDate_(NSDate.dateWithTimeIntervalSince1970_(end_dt.timestamp()))
    if notes:
        evt.setNotes_(notes)
    evt.setCalendar_(store.defaultCalendarForNewEvents())

    err_ptr = None
    ok = store.saveEvent_span_commit_error_(evt, 0, True, err_ptr)  # EKSpanThisEvent = 0
    if not ok:
        raise RuntimeError("saveEvent falló")
    return {"ok": True, "result": f"✅ Evento creado: {title}"}


def _eventkit_reminders_today() -> list:
    """Devuelve recordatorios pendientes de hoy usando EventKit."""
    import EventKit  # type: ignore[import]
    from Foundation import NSDate  # type: ignore[import]

    store = _get_reminders_store()
    if store is None:
        raise RuntimeError("EventKit reminders no disponible")

    today_end = datetime.now().replace(hour=23, minute=59, second=59)
    end_ns = NSDate.dateWithTimeIntervalSince1970_(today_end.timestamp())

    pred = store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(
        None, end_ns, None
    )

    results_holder: list = []
    done = threading.Semaphore(0)

    def _cb(reminders: Any) -> None:
        if reminders:
            for r in reminders:
                name = r.title()
                if name:
                    results_holder.append(name)
        done.release()

    store.fetchRemindersMatchingPredicate_completion_(pred, _cb)
    done.acquire(timeout=5)
    return results_holder


# ── AppleScript fallbacks ─────────────────────────────────────────────────────

def _escape_applescript_text(value: str) -> str:
    return (value or "").replace("\\", "\\\\").replace('"', '\\"')


def _applescript_events_today() -> list:
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
            capture_output=True, text=True, timeout=5
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


def _applescript_reminders_today() -> list:
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
            capture_output=True, text=True, timeout=5
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


def _applescript_create_event(
    title: str,
    dt: datetime,
    duration_minutes: int,
    notes: str,
) -> Dict[str, Any]:
    safe_title = _escape_applescript_text(title)
    safe_notes = _escape_applescript_text(notes or "")
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
            capture_output=True, text=True, timeout=6,
        )
        if result.returncode != 0:
            return {"ok": False, "error": result.stderr.strip() or "Error creando evento"}
        return {"ok": True, "result": result.stdout.strip() or "Evento creado"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Timeout creando evento de calendario"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ── API pública ───────────────────────────────────────────────────────────────

def get_calendar_events_today() -> list:
    """
    Lee eventos de Calendar.app para hoy.
    Usa EventKit si disponible (<80ms), fallback a AppleScript.
    Retorna lista de strings "HH:MM - Nombre evento" ordenados por hora.
    """
    try:
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return _eventkit_events_for_range(today, today + timedelta(days=1))
    except Exception:
        return _applescript_events_today()


def get_reminders_today() -> list:
    """
    Lee recordatorios pendientes de Reminders.app.
    Usa EventKit si disponible, fallback a AppleScript.
    """
    try:
        return _eventkit_reminders_today()
    except Exception:
        return _applescript_reminders_today()


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

    duration_minutes = max(5, int(duration_minutes))
    end_dt = dt + timedelta(minutes=duration_minutes)

    try:
        return _eventkit_create_event(title, dt, end_dt, notes)
    except Exception:
        return _applescript_create_event(title, dt, duration_minutes, notes)


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

                set output to "📅 Eventos de hoy:\n"
                repeat with evt in eventList
                    set eventTime to time string of start date of evt
                    set eventName to summary of evt
                    set output to output & "  • " & eventTime & " - " & eventName & "\n"
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

                set output to "📅 Eventos de mañana:\n"
                repeat with evt in eventList
                    set eventTime to time string of start date of evt
                    set eventName to summary of evt
                    set output to output & "  • " & eventTime & " - " & eventName & "\n"
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

                set output to "📅 Eventos de esta semana: " & (count of eventList) & " eventos\n"

                return output
            end tell
            '''

        elif action == "create":
            if not query:
                return {"ok": False, "error": "Necesito un título para el recordatorio"}
            safe_query = _escape_applescript_text(query)
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
                ),
            }

        # Ejecutar AppleScript
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode != 0:
            return {
                "ok": False,
                "error": result.stderr.strip() or "Error accediendo al calendario",
            }

        output = result.stdout.strip()
        return {"ok": True, "result": output or "Consulta ejecutada"}

    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Timeout consultando calendario"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
