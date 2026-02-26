from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from jarvis.intents.class_session import get_pending_class_tasks
from jarvis.tools.calendar import get_calendar_events_today, get_reminders_today
from jarvis.tools.routines import get_routines_for_today

# ============================================================
# CONFIG BÁSICA (ajusta rutas si tu proyecto usa otra estructura)
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent  # jarvis-agent/
DATA_DIR = BASE_DIR / "data"
STATE_DIR = BASE_DIR / "state"

STATE_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

MORNING_STATE_FILE = STATE_DIR / "morning_state.json"
JARVIS_TODO_FILE = STATE_DIR / "jarvis_todo.json"

# Si luego quieres moverlos a JSON, por ahora van embebidos para que funcione ya.
COMPLIMENTS: List[str] = [
    "Espero que haya descansado bien.",
    "Siempre es un placer asistirle.",
    "Confío en que hoy tendrá un gran día.",
    "Se le nota enfoque incluso a esta hora.",
    "Hoy vuelve a empezar con muy buena presencia.",
    "Tiene usted una energía muy sólida para arrancar el día.",
    "Da gusto verle empezar con esa calma.",
    "Como siempre, transmite determinación.",
    "Hoy tiene porte de día productivo, señor.",
    "Se le ve con la mente despierta.",
]

RANDOM_FACTS: List[Dict[str, str]] = [
    {
        "id": "squirrel_fall",
        "fact": "Dato del día: una ardilla puede sobrevivir a caídas muy altas por su baja masa corporal.",
        "explanation": "Porque su cuerpo pequeño y ligero reduce la velocidad terminal, así que el impacto suele ser mucho menor que en animales grandes."
    },
    {
        "id": "octopus_hearts",
        "fact": "Dato del día: los pulpos tienen tres corazones.",
        "explanation": "Dos corazones bombean sangre a las branquias y el tercero al resto del cuerpo."
    },
    {
        "id": "honey_no_expire",
        "fact": "Dato del día: la miel puede durar muchísimo tiempo sin estropearse si está bien cerrada.",
        "explanation": "Tiene muy poca agua y un entorno químico que dificulta el crecimiento de bacterias y hongos."
    },
]


# ============================================================
# MODELOS
# ============================================================

@dataclass
class MorningBriefingResult:
    text: str
    blocks: List[str]


# ============================================================
# UTILIDADES DE ESTADO / JSON
# ============================================================

def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _today_key() -> str:
    # Si luego quieres zona horaria local exacta, la conectamos a tu sistema
    return datetime.now().strftime("%Y-%m-%d")


def _weekday_key_es() -> str:
    # Lunes=0 ... Domingo=6
    idx = datetime.now().weekday()
    names = [
        "monday", "tuesday", "wednesday", "thursday",
        "friday", "saturday", "sunday"
    ]
    return names[idx]


# ============================================================
# SERVICIOS MVP (stubs / mocks)
# Luego los cambiaremos por integraciones reales
# ============================================================

def get_random_compliment() -> str:
    return random.choice(COMPLIMENTS)


def get_today_weather_summary() -> str:
    """
    MVP (mock):
    Más adelante lo conectamos a API real de tiempo.
    """
    return "Hoy hará fresco por la mañana y más templado por la tarde. No se esperan lluvias importantes."


def get_pending_reminders() -> List[str]:
    """
    Pendientes combinados:
    - recordatorios de Reminders.app (con fecha hoy/atrasados + 3 sin fecha)
    - tareas detectadas en sesiones de clase
    - TODOs internos de Jarvis
    """
    reminders: List[str] = []
    # Real Reminders.app
    reminders.extend(get_reminders_today())
    # Clase sessions (si el módulo está disponible)
    try:
        reminders.extend(get_pending_class_tasks(limit=3))
    except Exception:
        pass
    # Jarvis TODOs internos
    for todo in get_jarvis_todos(limit=2):
        text = str(todo.get("text", "")).strip()
        if text and text not in reminders:
            reminders.append(text)
    return reminders[:6]


def get_relevant_notes_for_today() -> List[str]:
    """
    MVP (mock):
    Luego conectamos app de Notas / fuente real.
    """
    return []


def get_random_fact() -> Dict[str, str]:
    return random.choice(RANDOM_FACTS)


def explain_fact_by_id(fact_id: str) -> Optional[str]:
    for item in RANDOM_FACTS:
        if item["id"] == fact_id:
            return item["explanation"]
    return None


# ============================================================
# TODO DE JARVIS (cuando no puede hacer algo)
# ============================================================

def add_to_jarvis_todo(task_text: str) -> None:
    todos = _read_json(JARVIS_TODO_FILE, default=[])
    todos.append({
        "text": task_text.strip(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": "pending",
        "source": "voice",
    })
    _write_json(JARVIS_TODO_FILE, todos)


def get_jarvis_todos(limit: int = 5) -> List[Dict[str, Any]]:
    todos = _read_json(JARVIS_TODO_FILE, default=[])
    pending = [t for t in todos if t.get("status") == "pending"]
    return pending[:limit]


# ============================================================
# GENERACIÓN DEL BRIEFING
# ============================================================

def _build_salute_block() -> str:
    compliment = get_random_compliment()
    return f"Buenos días, señor. {compliment}"


def _build_weather_block() -> str:
    weather = get_today_weather_summary()
    return weather


def _build_calendar_block() -> str:
    """Lee eventos reales de Calendar.app + rutinas del día."""
    events = get_calendar_events_today()
    routines = get_routines_for_today()

    parts = []

    if events:
        if len(events) == 1:
            parts.append(f"En el calendario tiene {events[0]}.")
        else:
            joined = ", ".join(events[:-1]) + f" y {events[-1]}"
            parts.append(f"En el calendario tiene {joined}.")
    else:
        parts.append("Hoy no tiene eventos en el calendario.")

    if routines:
        joined_r = ", ".join(routines[:3])
        parts.append(f"En rutinas: {joined_r}.")

    return " ".join(parts)


def _build_tasks_block() -> str:
    reminders = get_pending_reminders()
    notes = get_relevant_notes_for_today()

    items = reminders + notes
    if not items:
        return "No veo pendientes importantes para hoy."

    # Resumen corto (no soltar 20 cosas)
    top_items = items[:3]
    if len(top_items) == 1:
        return f"En pendientes, {top_items[0]}"
    return "En pendientes: " + " ".join(
        [f"{item}" if item.endswith(".") else f"{item}." for item in top_items]
    )


def _build_fact_block() -> Dict[str, str]:
    fact = get_random_fact()
    return fact


def _build_final_question_block() -> str:
    return "¿Quiere que le organice lo importante de hoy?"


def _save_morning_state(today_key: str, fact: Dict[str, str]) -> None:
    state = {
        "last_morning_briefing_date": today_key,
        "last_random_fact_id": fact["id"],
        "last_random_fact_text": fact["fact"],
        "today_briefing_done": True,
    }
    _write_json(MORNING_STATE_FILE, state)


def _get_morning_state() -> Dict[str, Any]:
    return _read_json(MORNING_STATE_FILE, default={
        "last_morning_briefing_date": None,
        "last_random_fact_id": None,
        "last_random_fact_text": None,
        "today_briefing_done": False,
    })


def run_morning_briefing(force_full: bool = False) -> MorningBriefingResult:
    """
    Genera el briefing completo o una versión corta si ya se dio hoy.
    """
    state = _get_morning_state()
    today = _today_key()

    already_done_today = (
        state.get("today_briefing_done") is True
        and state.get("last_morning_briefing_date") == today
    )

    if already_done_today and not force_full:
        blocks = [
            "Buenos días otra vez, señor.",
            "Ya le di el briefing de hoy.",
            "¿Quiere resumen rápido o algo concreto?"
        ]
        return MorningBriefingResult(text="\n".join(blocks), blocks=blocks)

    salute = _build_salute_block()
    weather = _build_weather_block()
    calendar_block = _build_calendar_block()
    tasks = _build_tasks_block()
    fact = _build_fact_block()
    final_q = _build_final_question_block()

    blocks = [
        salute,
        weather,
        calendar_block,
        tasks,
        fact["fact"],
        final_q
    ]

    _save_morning_state(today, fact)

    return MorningBriefingResult(text="\n".join(blocks), blocks=blocks)


# ============================================================
# SEGUIMIENTO DE CONVERSACIÓN (ej. "¿por qué?" tras dato random)
# ============================================================

FOLLOW_UP_PATTERNS = [
    "por qué", "porque", "cómo", "como", "eso es verdad", "explícame", "explicame"
]


def can_handle_fact_follow_up(user_text: str) -> bool:
    txt = (user_text or "").strip().lower()
    return any(p in txt for p in FOLLOW_UP_PATTERNS)


def answer_fact_follow_up(user_text: str) -> Optional[str]:
    """
    Si el usuario pregunta por el dato random, responde usando el último fact guardado.
    """
    if not can_handle_fact_follow_up(user_text):
        return None

    state = _get_morning_state()
    fact_id = state.get("last_random_fact_id")
    if not fact_id:
        return "No tengo un dato reciente en contexto, señor."

    explanation = explain_fact_by_id(fact_id)
    if not explanation:
        return "No encuentro la explicación del dato anterior, señor."

    return explanation


# ============================================================
# FALLBACK ÚTIL (si Jarvis no puede hacer algo)
# ============================================================

def handle_unavailable_action(task_request: str) -> str:
    """
    Úsalo cuando el sistema no pueda ejecutar una acción concreta.
    """
    clean = (task_request or "").strip()
    if not clean:
        clean = "Tarea sin descripción"
    add_to_jarvis_todo(clean)
    return "No puedo hacerlo directamente ahora mismo, señor, pero lo he añadido a su lista de pendientes."


# ============================================================
# TEST MANUAL (puedes ejecutar este archivo directamente)
# ============================================================

if __name__ == "__main__":
    result = run_morning_briefing()
    print("\n--- BRIEFING ---")
    print(result.text)

    print("\n--- FOLLOW-UP DEMO ---")
    print(answer_fact_follow_up("¿por qué?"))

    print("\n--- TODO DEMO ---")
    print(handle_unavailable_action("Recordarme revisar la práctica de métodos numéricos"))
    print(get_jarvis_todos())
