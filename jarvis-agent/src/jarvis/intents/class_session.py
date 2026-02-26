from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CLASS_DIR = PROJECT_ROOT / "data" / "class_sessions"
TASKS_FILE = CLASS_DIR / "class_tasks.json"
SESSIONS_FILE = CLASS_DIR / "sessions.json"


@dataclass
class ClassTask:
    title: str
    description: str = ""
    due_date: Optional[str] = None
    due_time: Optional[str] = None
    kind: str = "task"


@dataclass
class ClassSessionResult:
    transcript: str
    summary: str
    tasks: List[ClassTask]
    calendar_created: int
    transcript_path: Path


def _ensure_storage() -> None:
    CLASS_DIR.mkdir(parents=True, exist_ok=True)


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


def _extract_json_block(text: str) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return None

    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", text, re.IGNORECASE)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except Exception:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            return None
    return None


def _normalize_date(raw: str) -> Optional[str]:
    val = (raw or "").strip()
    if not val:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", val):
        return val
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", val)
    if not m:
        return None
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if year < 100:
        year += 2000
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _normalize_time(raw: str) -> Optional[str]:
    val = (raw or "").strip().lower()
    if not val:
        return None
    m24 = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", val)
    if m24:
        return f"{int(m24.group(1)):02d}:{m24.group(2)}"
    m12 = re.fullmatch(r"([1-9]|1[0-2])(?::([0-5]\d))?\s*(am|pm)", val)
    if not m12:
        return None
    hour = int(m12.group(1))
    minute = int(m12.group(2) or "00")
    suffix = m12.group(3)
    if suffix == "pm" and hour != 12:
        hour += 12
    if suffix == "am" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


def _tasks_from_transcript_fallback(transcript: str) -> List[ClassTask]:
    items: List[ClassTask] = []
    for line in transcript.splitlines():
        ln = line.strip()
        if not ln:
            continue
        if not re.search(r"\b(examen|entrega|ejercicio|tarea|pr[aó]ctica)\b", ln, re.IGNORECASE):
            continue
        date_match = re.search(r"\b(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})\b", ln)
        time_match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", ln)
        items.append(
            ClassTask(
                title=ln[:140],
                description=ln,
                due_date=_normalize_date(date_match.group(1)) if date_match else None,
                due_time=time_match.group(0) if time_match else None,
                kind="detected",
            )
        )
    return items[:6]


def _summarize_transcript(agent: Any, transcript: str) -> str:
    prompt = (
        "Resume esta clase en espanol.\n"
        "Formato obligatorio:\n"
        "1) Temas clave (max 5 bullets)\n"
        "2) Conceptos importantes\n"
        "3) Dudas o puntos para repasar\n\n"
        f"TRANSCRIPCION:\n{transcript}"
    )
    out = (agent.run(prompt) or "").strip()
    if out:
        return out
    return "No se pudo generar resumen automatico."


def _extract_tasks_with_llm(agent: Any, transcript: str) -> List[ClassTask]:
    prompt = (
        "Extrae tareas academicas y fechas de esta transcripcion.\n"
        "Devuelve SOLO JSON valido con este formato exacto:\n"
        "{\n"
        '  "tasks": [\n'
        "    {\n"
        '      "title": "string",\n'
        '      "description": "string",\n'
        '      "kind": "exam|homework|exercise|project|other",\n'
        '      "due_date": "YYYY-MM-DD o null",\n'
        '      "due_time": "HH:MM o null"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Si no hay tareas, devuelve tasks vacio.\n\n"
        f"TRANSCRIPCION:\n{transcript}"
    )
    raw = agent.run(prompt)
    parsed = _extract_json_block(raw or "")
    if not parsed or not isinstance(parsed.get("tasks"), list):
        return _tasks_from_transcript_fallback(transcript)

    tasks: List[ClassTask] = []
    for item in parsed["tasks"]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        tasks.append(
            ClassTask(
                title=title[:140],
                description=str(item.get("description", "")).strip(),
                due_date=_normalize_date(str(item.get("due_date", "")).strip()),
                due_time=_normalize_time(str(item.get("due_time", "")).strip()),
                kind=str(item.get("kind", "other")).strip() or "other",
            )
        )
    return tasks


def _create_calendar_entries(tasks: List[ClassTask]) -> int:
    from jarvis.tools.calendar import calendar_query, create_calendar_event

    created = 0
    for task in tasks:
        if not task.title:
            continue

        if task.due_date:
            out = create_calendar_event(
                title=task.title,
                due_date=task.due_date,
                due_time=task.due_time or "09:00",
                notes=task.description,
            )
        else:
            payload = task.title
            out = calendar_query({"action": "create", "query": payload})

        if out.get("ok"):
            created += 1
    return created


def _merge_tasks(existing: List[Dict[str, Any]], new_tasks: List[ClassTask]) -> List[Dict[str, Any]]:
    now = datetime.now().isoformat(timespec="seconds")
    seen = {
        (str(item.get("title", "")).strip().lower(), str(item.get("due_date", "")).strip())
        for item in existing
        if isinstance(item, dict)
    }
    merged = list(existing)
    for task in new_tasks:
        key = (task.title.strip().lower(), (task.due_date or "").strip())
        if key in seen:
            continue
        seen.add(key)
        merged.append(
            {
                "title": task.title,
                "description": task.description,
                "due_date": task.due_date,
                "due_time": task.due_time,
                "kind": task.kind,
                "status": "pending",
                "created_at": now,
                "source": "class_session",
            }
        )
    return merged


def get_pending_class_tasks(limit: int = 5) -> List[str]:
    _ensure_storage()
    items = _read_json(TASKS_FILE, default=[])
    if not isinstance(items, list):
        return []
    pending = [item for item in items if isinstance(item, dict) and item.get("status") == "pending"]
    pending = pending[: max(0, int(limit))]
    out: List[str] = []
    for item in pending:
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        due_date = str(item.get("due_date", "")).strip()
        due_time = str(item.get("due_time", "")).strip()
        if due_date and due_time:
            out.append(f"{title} (fecha {due_date} a las {due_time})")
        elif due_date:
            out.append(f"{title} (fecha {due_date})")
        else:
            out.append(title)
    return out


def process_class_session(
    *,
    settings: Any,
    seconds: float,
    class_title: Optional[str] = None,
    audio_path: Optional[Path] = None,
    sync_calendar: bool = True,
) -> ClassSessionResult:
    from jarvis.agent.tool_agent import tool_agent_from_settings
    from jarvis.voice.stt import STT, STTConfig

    _ensure_storage()

    stt_cfg = STTConfig(
        engine=getattr(settings, "stt_engine", "groq"),
        groq_api_key=getattr(settings, "groq_api_key", ""),
        groq_model=getattr(settings, "stt_groq_model", "whisper-large-v3-turbo"),
        whisper_model=getattr(settings, "stt_whisper_model", "small"),
    )
    stt = STT(stt_cfg)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    title_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", (class_title or "clase").strip())[:40] or "clase"
    wav_path = CLASS_DIR / f"{stamp}_{title_slug}.wav"
    transcript_path = CLASS_DIR / f"{stamp}_{title_slug}.txt"

    if audio_path:
        wav_in = Path(audio_path).expanduser().resolve()
    else:
        wav_in = stt.record_to_wav(wav_path, seconds=seconds)

    transcript = stt.transcribe_wav(wav_in).strip()
    transcript_path.write_text(transcript, encoding="utf-8")

    agent = tool_agent_from_settings(settings)
    summary = _summarize_transcript(agent, transcript)
    tasks = _extract_tasks_with_llm(agent, transcript)
    calendar_created = _create_calendar_entries(tasks) if sync_calendar else 0

    sessions = _read_json(SESSIONS_FILE, default=[])
    if not isinstance(sessions, list):
        sessions = []
    sessions.append(
        {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "class_title": class_title or "Clase",
            "transcript_path": str(transcript_path),
            "summary": summary,
            "tasks_detected": len(tasks),
            "calendar_created": calendar_created,
        }
    )
    _write_json(SESSIONS_FILE, sessions)

    existing_tasks = _read_json(TASKS_FILE, default=[])
    if not isinstance(existing_tasks, list):
        existing_tasks = []
    merged_tasks = _merge_tasks(existing_tasks, tasks)
    _write_json(TASKS_FILE, merged_tasks)

    return ClassSessionResult(
        transcript=transcript,
        summary=summary,
        tasks=tasks,
        calendar_created=calendar_created,
        transcript_path=transcript_path,
    )
