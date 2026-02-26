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
from jarvis.tools.weather import run_weather

# ============================================================
# CONFIG
# ============================================================

HOME_CITY = "Madrid"

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STATE_DIR = BASE_DIR / "state"

STATE_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

MORNING_STATE_FILE = STATE_DIR / "morning_state.json"
JARVIS_TODO_FILE = STATE_DIR / "jarvis_todo.json"

# ============================================================
# SALUDOS — semana vs. fin de semana
# ============================================================

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
    "Un placer verle empezar otro día con tanta energía.",
    "Cada mañana es una nueva oportunidad, y usted lo aprovecha bien.",
]

COMPLIMENTS_WEEKEND: List[str] = [
    "Es fin de semana, espero que pueda descansar a fondo.",
    "Hoy toca desconectar un poco, señor.",
    "Nada en el horizonte que no pueda esperar al lunes.",
    "Ojalá sea un día tranquilo y agradable.",
    "El descanso también es productividad, señor.",
    "Un buen fin de semana es el mejor combustible para la semana.",
    "Espero que tenga planes que le recarguen las pilas.",
]

# ============================================================
# HECHOS ALEATORIOS (23)
# ============================================================

RANDOM_FACTS: List[Dict[str, str]] = [
    {
        "id": "squirrel_fall",
        "fact": "Dato del día: una ardilla puede sobrevivir a caídas muy altas por su baja masa corporal.",
        "explanation": "Su cuerpo pequeño y ligero reduce la velocidad terminal, así que el impacto suele ser mucho menor que en animales grandes.",
    },
    {
        "id": "octopus_hearts",
        "fact": "Dato del día: los pulpos tienen tres corazones.",
        "explanation": "Dos corazones bombean sangre a las branquias y el tercero al resto del cuerpo.",
    },
    {
        "id": "honey_no_expire",
        "fact": "Dato del día: la miel puede durar miles de años sin estropearse si está bien cerrada.",
        "explanation": "Tiene muy poca agua y un entorno químico que dificulta el crecimiento de bacterias y hongos.",
    },
    {
        "id": "cleopatra_moon",
        "fact": "Dato del día: Cleopatra vivió más cerca en el tiempo de la llegada a la Luna que de la construcción de las pirámides.",
        "explanation": "Las pirámides se construyeron hace unos 4.500 años; Cleopatra vivió hace unos 2.000, y la Luna se pisó hace 55. El tiempo antiguo es más largo de lo que parece.",
    },
    {
        "id": "bananas_radioactive",
        "fact": "Dato del día: los plátanos son ligeramente radiactivos.",
        "explanation": "Contienen potasio-40, un isótopo radiactivo natural. La dosis es completamente inocua, pero existe.",
    },
    {
        "id": "oxford_aztecs",
        "fact": "Dato del día: la Universidad de Oxford es más antigua que el Imperio Azteca.",
        "explanation": "Oxford empezó a impartir clases alrededor del año 1096. Los aztecas fundaron Tenochtitlán en 1325.",
    },
    {
        "id": "sharks_older_trees",
        "fact": "Dato del día: los tiburones llevan más tiempo en la Tierra que los árboles.",
        "explanation": "Los tiburones existen desde hace unos 450 millones de años; los árboles aparecieron hace unos 350 millones.",
    },
    {
        "id": "star_atoms",
        "fact": "Dato del día: cada átomo de hierro en su sangre fue forjado en el interior de una estrella.",
        "explanation": "Los elementos más pesados que el hidrógeno y el helio se sintetizan en núcleos estelares y se dispersan cuando la estrella explota como supernova.",
    },
    {
        "id": "hot_water_freezes",
        "fact": "Dato del día: en ciertas condiciones, el agua caliente puede congelarse más rápido que la fría.",
        "explanation": "Se llama efecto Mpemba. Las causas exactas aún se debaten, pero se cree que intervienen la evaporación, la convección y los gases disueltos.",
    },
    {
        "id": "wombat_poop",
        "fact": "Dato del día: los wombats producen heces cuadradas, únicos en el reino animal.",
        "explanation": "Su intestino tiene zonas de distinta elasticidad que moldean las heces en cubos, lo que les ayuda a marcar territorio sin que rueden.",
    },
    {
        "id": "venus_day",
        "fact": "Dato del día: un día en Venus dura más que un año en Venus.",
        "explanation": "Venus tarda 243 días terrestres en girar sobre sí mismo, pero solo 225 días en orbitar al Sol. Su día es más largo que su año.",
    },
    {
        "id": "mantis_shrimp",
        "fact": "Dato del día: el camarón mantis puede ver 16 tipos de colores distintos.",
        "explanation": "Los humanos tenemos 3 tipos de receptores de color (rojo, verde, azul). El camarón mantis tiene 16, aunque procesa la información de forma muy diferente.",
    },
    {
        "id": "ant_strength",
        "fact": "Dato del día: las hormigas pueden cargar hasta 50 veces su propio peso.",
        "explanation": "Gracias a su tamaño pequeño, la relación entre fuerza muscular y masa corporal les favorece enormemente respecto a los animales grandes.",
    },
    {
        "id": "lightning_twice",
        "fact": "Dato del día: el rayo sí cae dos veces en el mismo sitio, y de hecho es bastante común.",
        "explanation": "Los rayos buscan el camino de menor resistencia, y si una estructura ya condujo un rayo, probablemente lo hará de nuevo. El Empire State recibe unos 20 rayos al año.",
    },
    {
        "id": "saturn_float",
        "fact": "Dato del día: Saturno es tan poco denso que flotaría en agua.",
        "explanation": "Su densidad media es de 0,687 g/cm³, menor que la del agua. Es el único planeta del Sistema Solar más ligero que el agua.",
    },
    {
        "id": "dog_nose",
        "fact": "Dato del día: la nariz húmeda de los perros les ayuda a detectar de dónde viene un olor.",
        "explanation": "La humedad atrapa moléculas olorosas y les permite comparar la concentración entre ambas fosas nasales para triangular la dirección del olfato.",
    },
    {
        "id": "oldest_tree",
        "fact": "Dato del día: el árbol vivo más antiguo conocido tiene más de 5.000 años.",
        "explanation": "Es un pino llamado Matusalén, en California. Su ubicación exacta se mantiene en secreto para protegerlo.",
    },
    {
        "id": "smell_memory",
        "fact": "Dato del día: el olfato es el sentido más directamente conectado a la memoria.",
        "explanation": "Las señales olfativas van directamente al hipocampo y la amígdala, regiones clave en la memoria y las emociones, sin pasar por el tálamo como el resto de sentidos.",
    },
    {
        "id": "crying_stress",
        "fact": "Dato del día: llorar libera toxinas del estrés del organismo.",
        "explanation": "Las lágrimas emocionales contienen cortisol y otras hormonas de estrés. Eliminarlas tiene un efecto fisiológico calmante real.",
    },
    {
        "id": "spoken_languages",
        "fact": "Dato del día: se hablan unas 7.000 lenguas en el mundo, y la mitad podrían desaparecer en este siglo.",
        "explanation": "Muchas lenguas tienen solo decenas de hablantes ancianos. Cuando mueren sin transmitirse, se pierde con ellas una forma única de ver el mundo.",
    },
    {
        "id": "fingernails_dominant",
        "fact": "Dato del día: las uñas de la mano dominante crecen más rápido.",
        "explanation": "La mayor circulación sanguínea y el uso frecuente de esa mano aceleran ligeramente el crecimiento. También crecen más rápido en verano y durante el día.",
    },
    {
        "id": "snails_sleep",
        "fact": "Dato del día: los caracoles pueden dormir hasta tres años seguidos.",
        "explanation": "En épocas de sequía o frío extremo entran en un estado de hibernación prolongada para sobrevivir sin agua ni alimento.",
    },
    {
        "id": "universe_age",
        "fact": "Dato del día: si la historia del universo fuera un año, toda la historia humana cabría en los últimos 10 segundos.",
        "explanation": "El universo tiene 13.800 millones de años. Los humanos modernos llevan unos 300.000 años. La proporción es abrumadora.",
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
# UTILIDADES
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
    return datetime.now().strftime("%Y-%m-%d")


def _weekday_key_es() -> str:
    names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    return names[datetime.now().weekday()]


def _is_weekend() -> bool:
    return datetime.now().weekday() >= 5  # sábado=5, domingo=6


# ============================================================
# SERVICIOS
# ============================================================

def get_random_compliment() -> str:
    pool = COMPLIMENTS_WEEKEND if _is_weekend() else COMPLIMENTS
    return random.choice(pool)


def get_today_weather_summary() -> str:
    """Consulta el clima real en Madrid via wttr.in."""
    try:
        result = run_weather({"city": HOME_CITY, "days": 0})
        if not result.get("ok"):
            return "No he podido obtener el tiempo ahora mismo."
        c = result["current"]
        temp = c["temp_c"]
        feels = c["feels_like_c"]
        desc = c["description"]
        wind = c["wind_kmh"]

        summary = f"En {HOME_CITY}, {temp} grados, {desc}."
        if feels != temp:
            summary += f" Sensación térmica de {feels} grados."
        if wind >= 30:
            summary += f" Viento de {wind} kilómetros por hora."
        return summary
    except Exception:
        return "No he podido obtener el tiempo ahora mismo."


def get_pending_reminders() -> List[str]:
    """
    Pendientes combinados:
    - recordatorios de Reminders.app (con fecha hoy/atrasados + 3 sin fecha)
    - tareas detectadas en sesiones de clase (solo días laborables)
    - TODOs internos de Jarvis
    """
    reminders: List[str] = []
    reminders.extend(get_reminders_today())
    if not _is_weekend():
        try:
            reminders.extend(get_pending_class_tasks(limit=3))
        except Exception:
            pass
    for todo in get_jarvis_todos(limit=2):
        text = str(todo.get("text", "")).strip()
        if text and text not in reminders:
            reminders.append(text)
    return reminders[:6]


def get_relevant_notes_for_today() -> List[str]:
    return []


def get_random_fact() -> Dict[str, str]:
    return random.choice(RANDOM_FACTS)


def explain_fact_by_id(fact_id: str) -> Optional[str]:
    for item in RANDOM_FACTS:
        if item["id"] == fact_id:
            return item["explanation"]
    return None


# ============================================================
# TODO DE JARVIS
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
# BLOQUES DEL BRIEFING
# ============================================================

def _build_salute_block() -> str:
    compliment = get_random_compliment()
    return f"Buenos días, señor. {compliment}"


def _build_weather_block() -> str:
    return get_today_weather_summary()


def _build_calendar_block() -> str:
    """Eventos de Calendar.app + rutinas del día."""
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
        if _is_weekend():
            parts.append("Agenda libre hoy.")
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
        if _is_weekend():
            return "Sin pendientes urgentes. Puede descansar tranquilo."
        return "No veo pendientes importantes para hoy."

    top_items = items[:3]
    if len(top_items) == 1:
        return f"En pendientes, {top_items[0]}"
    return "En pendientes: " + " ".join(
        [f"{item}" if item.endswith(".") else f"{item}." for item in top_items]
    )


def _build_fact_block() -> Dict[str, str]:
    return get_random_fact()


def _build_final_question_block() -> str:
    if _is_weekend():
        return "¿Tiene algún plan para hoy?"
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


# ============================================================
# BRIEFING PRINCIPAL
# ============================================================

def run_morning_briefing(force_full: bool = False) -> MorningBriefingResult:
    """
    Genera el briefing completo o una versión corta si ya se dio hoy.
    En fin de semana el tono es más relajado y se omiten tareas de clase.
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
    fact = _build_fact_block()
    final_q = _build_final_question_block()

    blocks = [salute, weather, calendar_block]

    # En fin de semana solo mostramos tareas si hay pendientes reales con fecha
    if _is_weekend():
        # Solo Reminders con fecha (no backlog ni class tasks)
        dated = get_reminders_today()
        if dated:
            top = dated[:2]
            tasks_text = "Tiene pendientes para hoy: " + ", ".join(top) + "."
            blocks.append(tasks_text)
    else:
        blocks.append(_build_tasks_block())

    blocks.append(fact["fact"])
    blocks.append(final_q)

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
    """Si el usuario pregunta por el dato random, responde con la explicación guardada."""
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
    clean = (task_request or "").strip() or "Tarea sin descripción"
    add_to_jarvis_todo(clean)
    return "No puedo hacerlo directamente ahora mismo, señor, pero lo he añadido a su lista de pendientes."


# ============================================================
# TEST MANUAL
# ============================================================

if __name__ == "__main__":
    result = run_morning_briefing(force_full=True)
    print("\n--- BRIEFING ---")
    print(result.text)

    print("\n--- FOLLOW-UP DEMO ---")
    print(answer_fact_follow_up("¿por qué?"))
