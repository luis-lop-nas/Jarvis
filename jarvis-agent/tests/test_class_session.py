from __future__ import annotations

from pathlib import Path

from jarvis.intents import class_session as cs


def test_extract_json_block_from_fenced_text() -> None:
    raw = 'respuesta\n```json\n{"tasks":[{"title":"Examen parcial"}]}\n```'
    parsed = cs._extract_json_block(raw)
    assert parsed is not None
    assert parsed["tasks"][0]["title"] == "Examen parcial"


def test_normalize_date_variants() -> None:
    assert cs._normalize_date("2026-03-15") == "2026-03-15"
    assert cs._normalize_date("15/03/2026") == "2026-03-15"
    assert cs._normalize_date("15/03/26") == "2026-03-15"
    assert cs._normalize_date("32/03/2026") is None


def test_normalize_time_variants() -> None:
    assert cs._normalize_time("9:05") == "09:05"
    assert cs._normalize_time("9 pm") == "21:00"
    assert cs._normalize_time("12 am") == "00:00"
    assert cs._normalize_time("25:00") is None


def test_merge_tasks_deduplicates_by_title_and_date() -> None:
    existing = [{"title": "Examen de algebra", "due_date": "2026-03-20", "status": "pending"}]
    merged = cs._merge_tasks(
        existing,
        [
            cs.ClassTask(title="Examen de algebra", due_date="2026-03-20"),
            cs.ClassTask(title="Ejercicios tema 4", due_date="2026-03-21"),
        ],
    )
    assert len(merged) == 2
    assert merged[1]["title"] == "Ejercicios tema 4"


def test_get_pending_class_tasks_reads_storage(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cs, "CLASS_DIR", tmp_path / "class_sessions")
    monkeypatch.setattr(cs, "TASKS_FILE", tmp_path / "class_sessions" / "class_tasks.json")

    cs._write_json(
        cs.TASKS_FILE,
        [
            {"title": "Examen de calculo", "due_date": "2026-03-10", "status": "pending"},
            {"title": "Trabajo final", "status": "done"},
        ],
    )

    items = cs.get_pending_class_tasks(limit=5)
    assert len(items) == 1
    assert "Examen de calculo" in items[0]


def test_create_calendar_entries_uses_event_when_date(monkeypatch) -> None:
    calls = {"events": 0, "reminders": 0}

    def fake_create_event(**kwargs):
        calls["events"] += 1
        assert kwargs["due_date"] == "2026-03-21"
        return {"ok": True}

    def fake_calendar_query(args):
        calls["reminders"] += 1
        assert args["action"] == "create"
        return {"ok": True}

    from jarvis.tools import calendar as calendar_mod

    monkeypatch.setattr(calendar_mod, "create_calendar_event", fake_create_event)
    monkeypatch.setattr(calendar_mod, "calendar_query", fake_calendar_query)

    created = cs._create_calendar_entries(
        [
            cs.ClassTask(title="Examen fisica", due_date="2026-03-21", due_time="10:00"),
            cs.ClassTask(title="Leer capitulo 2"),
        ]
    )

    assert created == 2
    assert calls["events"] == 1
    assert calls["reminders"] == 1
