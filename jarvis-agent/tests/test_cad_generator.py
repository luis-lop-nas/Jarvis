"""
tests/test_cad_generator.py

Unit tests for jarvis.tools.cad_generator
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

from jarvis.tools.cad_generator import (
    _detect_llm,
    extract_code,
    inject_output_path,
    load_session,
    make_output_path,
    run_cad_generator,
    save_session,
    validate_code,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_VALID_CAD_CODE = """\
from build123d import *
with BuildPart() as model:
    Box(50, 50, 20)
result_part = model.part
export_stl(result_part, OUTPUT_STL)
"""

_VALID_LLM_RESPONSE = f"```python\n{_VALID_CAD_CODE}\n```"


def _fake_llm() -> Dict[str, Any]:
    return {"provider": "groq", "api_key": "test_key", "model": "llama-3.3-70b-versatile"}


# ---------------------------------------------------------------------------
# extract_code
# ---------------------------------------------------------------------------

class TestExtractCode:

    def test_python_tagged_block(self):
        text = "```python\nprint('hello')\n```"
        result = extract_code(text)
        assert result == "print('hello')"

    def test_generic_block_no_tag(self):
        text = "```\nprint('hello')\n```"
        result = extract_code(text)
        assert result == "print('hello')"

    def test_no_code_block_returns_none(self):
        assert extract_code("Just plain text, no code.") is None

    def test_empty_string_returns_none(self):
        assert extract_code("") is None

    def test_returns_longest_block(self):
        text = (
            "```python\nshort\n```\n"
            "```python\nthis is a much longer block of code\n```"
        )
        result = extract_code(text)
        assert result == "this is a much longer block of code"

    def test_strips_whitespace(self):
        text = "```python\n\n  code here  \n\n```"
        result = extract_code(text)
        assert result == "code here"

    def test_real_cad_block(self):
        result = extract_code(_VALID_LLM_RESPONSE)
        assert result is not None
        assert "from build123d import *" in result
        assert "result_part" in result
        assert "export_stl" in result


# ---------------------------------------------------------------------------
# validate_code
# ---------------------------------------------------------------------------

class TestValidateCode:

    def test_valid_simple_code(self):
        ok, reason = validate_code(_VALID_CAD_CODE)
        assert ok is True
        assert reason == "ok"

    def test_empty_code_returns_false(self):
        ok, reason = validate_code("")
        assert ok is False

    def test_whitespace_only_returns_false(self):
        ok, reason = validate_code("   \n  ")
        assert ok is False

    def test_syntax_error_returns_false(self):
        ok, reason = validate_code("def broken(:\n    pass")
        assert ok is False
        assert "sintaxis" in reason.lower() or "syntax" in reason.lower()

    def test_blocked_import_os(self):
        code = "import os\nresult_part = None\nexport_stl(result_part, OUTPUT_STL)"
        ok, reason = validate_code(code)
        assert ok is False
        assert "os" in reason

    def test_blocked_import_sys(self):
        code = "import sys\nresult_part = None\nexport_stl(result_part, OUTPUT_STL)"
        ok, reason = validate_code(code)
        assert ok is False

    def test_blocked_import_subprocess(self):
        code = "import subprocess\nresult_part = None\nexport_stl(result_part, OUTPUT_STL)"
        ok, reason = validate_code(code)
        assert ok is False

    def test_blocked_from_import_os(self):
        code = "from os import path\nresult_part = None\nexport_stl(result_part, OUTPUT_STL)"
        ok, reason = validate_code(code)
        assert ok is False

    def test_blocked_call_eval(self):
        code = "eval('x=1')\nresult_part = None\nexport_stl(result_part, OUTPUT_STL)"
        ok, reason = validate_code(code)
        assert ok is False
        assert "eval" in reason

    def test_blocked_call_exec(self):
        code = "exec('x=1')\nresult_part = None\nexport_stl(result_part, OUTPUT_STL)"
        ok, reason = validate_code(code)
        assert ok is False
        assert "exec" in reason

    def test_blocked_call_compile(self):
        code = "compile('x=1','','exec')\nresult_part = None\nexport_stl(result_part, OUTPUT_STL)"
        ok, reason = validate_code(code)
        assert ok is False

    def test_blocked_module_attribute_access(self):
        # os.getcwd() → func.value is ast.Name('os') → blocked
        code = "os.getcwd()\nresult_part = None\nexport_stl(result_part, OUTPUT_STL)"
        ok, reason = validate_code(code)
        assert ok is False
        assert "os" in reason

    def test_missing_result_part(self):
        code = (
            "from build123d import *\n"
            "with BuildPart() as model:\n"
            "    Box(50, 50, 20)\n"
            "export_stl(model.part, OUTPUT_STL)"
        )
        ok, reason = validate_code(code)
        assert ok is False
        assert "result_part" in reason

    def test_missing_export_stl(self):
        code = (
            "from build123d import *\n"
            "with BuildPart() as model:\n"
            "    Box(50, 50, 20)\n"
            "result_part = model.part"
        )
        ok, reason = validate_code(code)
        assert ok is False
        assert "export_stl" in reason

    def test_allowed_math_import(self):
        code = (
            "import math\n"
            "from build123d import *\n"
            "r = math.sqrt(50)\n"
            "with BuildPart() as model:\n"
            "    Sphere(radius=r)\n"
            "result_part = model.part\n"
            "export_stl(result_part, OUTPUT_STL)"
        )
        ok, reason = validate_code(code)
        assert ok is True

    def test_from_build123d_import_star(self):
        ok, reason = validate_code(_VALID_CAD_CODE)
        assert ok is True

    def test_unknown_import_is_blocked(self):
        code = "import requests\nresult_part = None\nexport_stl(result_part, OUTPUT_STL)"
        ok, reason = validate_code(code)
        assert ok is False


# ---------------------------------------------------------------------------
# inject_output_path
# ---------------------------------------------------------------------------

class TestInjectOutputPath:

    def test_prepends_output_stl_definition(self):
        result = inject_output_path("some_code()", Path("/tmp/model.stl"))
        assert result.startswith("OUTPUT_STL = ")

    def test_correct_path_value(self):
        path = Path("/tmp/test_model.stl")
        result = inject_output_path("code()", path)
        assert "/tmp/test_model.stl" in result

    def test_original_code_preserved(self):
        code = "from build123d import *\nBox(10, 10, 10)"
        result = inject_output_path(code, Path("/tmp/x.stl"))
        assert "from build123d import *" in result
        assert "Box(10, 10, 10)" in result

    def test_forward_slashes_in_first_line(self):
        path = Path("/some/dir/model.stl")
        result = inject_output_path("code", path)
        first_line = result.splitlines()[0]
        assert "\\" not in first_line

    def test_output_stl_before_code(self):
        result = inject_output_path("result_code_here()", Path("/tmp/out.stl"))
        lines = [l for l in result.splitlines() if l.strip()]
        assert lines[0].startswith("OUTPUT_STL")


# ---------------------------------------------------------------------------
# make_output_path
# ---------------------------------------------------------------------------

class TestMakeOutputPath:

    def test_returns_path_object(self, tmp_path):
        with patch("jarvis.tools.cad_generator._MODELS_DIR", tmp_path):
            result = make_output_path("un cubo de 50mm")
        assert isinstance(result, Path)

    def test_stl_extension(self, tmp_path):
        with patch("jarvis.tools.cad_generator._MODELS_DIR", tmp_path):
            result = make_output_path("cube 50mm")
        assert result.suffix == ".stl"

    def test_sanitizes_special_chars(self, tmp_path):
        with patch("jarvis.tools.cad_generator._MODELS_DIR", tmp_path):
            result = make_output_path("A cube! With holes? (big ones)")
        assert "!" not in result.stem
        assert "?" not in result.stem
        assert "(" not in result.stem

    def test_description_appears_in_filename(self, tmp_path):
        with patch("jarvis.tools.cad_generator._MODELS_DIR", tmp_path):
            result = make_output_path("cube 50mm")
        assert "cube" in result.stem or "50mm" in result.stem

    def test_has_timestamp(self, tmp_path):
        import re
        with patch("jarvis.tools.cad_generator._MODELS_DIR", tmp_path):
            result = make_output_path("box")
        assert re.search(r"\d{8}_\d{6}", result.stem)

    def test_different_descriptions_produce_different_filenames(self, tmp_path):
        with patch("jarvis.tools.cad_generator._MODELS_DIR", tmp_path):
            p1 = make_output_path("box")
            p2 = make_output_path("cylinder")
        assert p1.stem != p2.stem


# ---------------------------------------------------------------------------
# load_session / save_session
# ---------------------------------------------------------------------------

class TestSessionPersistence:

    @pytest.fixture
    def session_dir(self, tmp_path):
        session_file = tmp_path / ".cad_sessions.json"
        with (
            patch("jarvis.tools.cad_generator._MODELS_DIR", tmp_path),
            patch("jarvis.tools.cad_generator._SESSION_FILE", session_file),
        ):
            yield tmp_path, session_file

    def test_load_nonexistent_returns_none(self, session_dir):
        result = load_session("nonexistent-id")
        assert result is None

    def test_save_and_load_roundtrip(self, session_dir):
        sid = str(uuid.uuid4())
        data = {"code": "some_code", "description": "A box", "iterations": 1}
        save_session(sid, data)
        loaded = load_session(sid)
        assert loaded is not None
        assert loaded["code"] == "some_code"
        assert loaded["description"] == "A box"

    def test_save_updates_existing_session(self, session_dir):
        sid = str(uuid.uuid4())
        save_session(sid, {"iterations": 1})
        save_session(sid, {"iterations": 2})
        loaded = load_session(sid)
        assert loaded["iterations"] == 2

    def test_multiple_sessions_coexist(self, session_dir):
        sid1 = str(uuid.uuid4())
        sid2 = str(uuid.uuid4())
        save_session(sid1, {"desc": "session1"})
        save_session(sid2, {"desc": "session2"})
        assert load_session(sid1)["desc"] == "session1"
        assert load_session(sid2)["desc"] == "session2"

    def test_load_unknown_id_returns_none(self, session_dir):
        sid = str(uuid.uuid4())
        save_session(sid, {"data": "x"})
        assert load_session("totally-different-id") is None

    def test_corrupted_json_returns_none(self, session_dir):
        _, session_file = session_dir
        session_file.write_text("NOT_VALID_JSON", encoding="utf-8")
        assert load_session("any-id") is None


# ---------------------------------------------------------------------------
# _detect_llm
# ---------------------------------------------------------------------------

class TestDetectLlm:

    def _clean_env(self):
        return {
            "ANTHROPIC_API_KEY": "",
            "GROQ_API_KEY": "",
            "GEMINI_API_KEY": "",
            "USE_CLAUDE": "false",
            "USE_GROQ": "false",
            "USE_GEMINI": "false",
        }

    def test_no_env_vars_returns_none(self):
        with patch.dict(os.environ, self._clean_env(), clear=False):
            result = _detect_llm()
        assert result is None

    def test_claude_active_returns_claude(self):
        env = {**self._clean_env(), "ANTHROPIC_API_KEY": "sk-test", "USE_CLAUDE": "true"}
        with patch.dict(os.environ, env, clear=False):
            result = _detect_llm()
        assert result is not None
        assert result["provider"] == "claude"
        assert result["api_key"] == "sk-test"

    def test_groq_active_returns_groq(self):
        env = {**self._clean_env(), "GROQ_API_KEY": "gsk_test", "USE_GROQ": "true"}
        with patch.dict(os.environ, env, clear=False):
            result = _detect_llm()
        assert result is not None
        assert result["provider"] == "groq"

    def test_gemini_active_returns_gemini(self):
        env = {**self._clean_env(), "GEMINI_API_KEY": "gem_test", "USE_GEMINI": "true"}
        with patch.dict(os.environ, env, clear=False):
            result = _detect_llm()
        assert result is not None
        assert result["provider"] == "gemini"

    def test_claude_priority_over_groq(self):
        env = {
            **self._clean_env(),
            "ANTHROPIC_API_KEY": "sk-test",
            "USE_CLAUDE": "true",
            "GROQ_API_KEY": "gsk_test",
            "USE_GROQ": "true",
        }
        with patch.dict(os.environ, env, clear=False):
            result = _detect_llm()
        assert result["provider"] == "claude"

    def test_fallback_to_anthropic_key_without_use_claude(self):
        env = {**self._clean_env(), "ANTHROPIC_API_KEY": "sk-fallback"}
        with patch.dict(os.environ, env, clear=False):
            result = _detect_llm()
        assert result is not None
        assert result["provider"] == "claude"
        assert result["api_key"] == "sk-fallback"

    def test_fallback_to_groq_key_without_use_groq(self):
        env = {**self._clean_env(), "GROQ_API_KEY": "gsk_fallback"}
        with patch.dict(os.environ, env, clear=False):
            result = _detect_llm()
        assert result is not None
        assert result["provider"] == "groq"


# ---------------------------------------------------------------------------
# run_cad_generator (integration with mocks)
# ---------------------------------------------------------------------------

class TestRunCadGenerator:

    @pytest.fixture
    def tmp_models_dir(self, tmp_path):
        session_file = tmp_path / ".cad_sessions.json"
        with (
            patch("jarvis.tools.cad_generator._MODELS_DIR", tmp_path),
            patch("jarvis.tools.cad_generator._SESSION_FILE", session_file),
        ):
            yield tmp_path

    def _make_stl(self, tmp_path: Path, name: str = "box.stl", size: int = 300) -> Path:
        p = tmp_path / name
        p.write_bytes(b"X" * size)
        return p

    # ── Error cases (no mocking needed for LLM) ──────────────────────────────

    def test_missing_description_returns_error(self, tmp_models_dir):
        result = run_cad_generator({})
        assert result["ok"] is False
        assert "description" in result["error"].lower()

    def test_empty_description_returns_error(self, tmp_models_dir):
        result = run_cad_generator({"description": "   "})
        assert result["ok"] is False

    def test_no_llm_configured_returns_error(self, tmp_models_dir):
        env = {
            "ANTHROPIC_API_KEY": "", "GROQ_API_KEY": "", "GEMINI_API_KEY": "",
            "USE_CLAUDE": "false", "USE_GROQ": "false", "USE_GEMINI": "false",
        }
        with patch.dict(os.environ, env, clear=False):
            result = run_cad_generator({"description": "a box"})
        assert result["ok"] is False

    # ── Happy path ────────────────────────────────────────────────────────────

    def test_successful_generation_returns_ok_true(self, tmp_models_dir):
        stl = self._make_stl(tmp_models_dir)
        with (
            patch("jarvis.tools.cad_generator._detect_llm", return_value=_fake_llm()),
            patch("jarvis.tools.cad_generator._call_llm", return_value=_VALID_LLM_RESPONSE),
            patch("jarvis.tools.cad_generator.execute_cad_code", return_value=(True, "")),
            patch("jarvis.tools.cad_generator.make_output_path", return_value=stl),
            patch("jarvis.tools.cad_generator.save_session"),
        ):
            result = run_cad_generator({"description": "a simple box"})
        assert result["ok"] is True
        assert "stl_path" in result
        assert "session_id" in result
        assert "code" in result
        assert result["attempts"] >= 1

    def test_successful_generation_includes_model_size(self, tmp_models_dir):
        stl = self._make_stl(tmp_models_dir, size=1024)
        with (
            patch("jarvis.tools.cad_generator._detect_llm", return_value=_fake_llm()),
            patch("jarvis.tools.cad_generator._call_llm", return_value=_VALID_LLM_RESPONSE),
            patch("jarvis.tools.cad_generator.execute_cad_code", return_value=(True, "")),
            patch("jarvis.tools.cad_generator.make_output_path", return_value=stl),
            patch("jarvis.tools.cad_generator.save_session"),
        ):
            result = run_cad_generator({"description": "a box"})
        assert result["ok"] is True
        assert result["model_size_kb"] == 1.0

    def test_successful_generation_includes_llm_provider(self, tmp_models_dir):
        stl = self._make_stl(tmp_models_dir)
        with (
            patch("jarvis.tools.cad_generator._detect_llm", return_value=_fake_llm()),
            patch("jarvis.tools.cad_generator._call_llm", return_value=_VALID_LLM_RESPONSE),
            patch("jarvis.tools.cad_generator.execute_cad_code", return_value=(True, "")),
            patch("jarvis.tools.cad_generator.make_output_path", return_value=stl),
            patch("jarvis.tools.cad_generator.save_session"),
        ):
            result = run_cad_generator({"description": "a box"})
        assert result["llm_provider"] == "groq"

    def test_custom_session_id_echoed_back(self, tmp_models_dir):
        stl = self._make_stl(tmp_models_dir)
        my_session = "my-custom-session-id"
        with (
            patch("jarvis.tools.cad_generator._detect_llm", return_value=_fake_llm()),
            patch("jarvis.tools.cad_generator._call_llm", return_value=_VALID_LLM_RESPONSE),
            patch("jarvis.tools.cad_generator.execute_cad_code", return_value=(True, "")),
            patch("jarvis.tools.cad_generator.make_output_path", return_value=stl),
            patch("jarvis.tools.cad_generator.save_session"),
        ):
            result = run_cad_generator({"description": "a box", "session_id": my_session})
        assert result["session_id"] == my_session

    # ── Failure paths ─────────────────────────────────────────────────────────

    def test_llm_exception_returns_ok_false(self, tmp_models_dir):
        stl = tmp_models_dir / "x.stl"
        with (
            patch("jarvis.tools.cad_generator._detect_llm", return_value=_fake_llm()),
            patch("jarvis.tools.cad_generator._call_llm", side_effect=Exception("LLM timeout")),
            patch("jarvis.tools.cad_generator.make_output_path", return_value=stl),
        ):
            result = run_cad_generator({"description": "a box", "max_retries": 1})
        assert result["ok"] is False
        assert "error" in result

    def test_no_code_block_in_response_returns_ok_false(self, tmp_models_dir):
        stl = tmp_models_dir / "x.stl"
        with (
            patch("jarvis.tools.cad_generator._detect_llm", return_value=_fake_llm()),
            patch("jarvis.tools.cad_generator._call_llm", return_value="Sure! I'll help you."),
            patch("jarvis.tools.cad_generator.make_output_path", return_value=stl),
        ):
            result = run_cad_generator({"description": "a box", "max_retries": 1})
        assert result["ok"] is False

    def test_validation_failure_exhausts_retries(self, tmp_models_dir):
        malicious = (
            "```python\n"
            "import os\n"
            "result_part = None\n"
            "export_stl(result_part, OUTPUT_STL)\n"
            "```"
        )
        stl = tmp_models_dir / "x.stl"
        with (
            patch("jarvis.tools.cad_generator._detect_llm", return_value=_fake_llm()),
            patch("jarvis.tools.cad_generator._call_llm", return_value=malicious),
            patch("jarvis.tools.cad_generator.make_output_path", return_value=stl),
        ):
            result = run_cad_generator({"description": "a box", "max_retries": 2})
        assert result["ok"] is False

    # ── Retry logic ───────────────────────────────────────────────────────────

    def test_execution_failure_then_retry_success(self, tmp_models_dir):
        stl = self._make_stl(tmp_models_dir)
        call_count = {"n": 0}

        def exec_side_effect(code, path, timeout=120):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return False, "OCC geometry error"
            return True, ""

        with (
            patch("jarvis.tools.cad_generator._detect_llm", return_value=_fake_llm()),
            patch("jarvis.tools.cad_generator._call_llm", return_value=_VALID_LLM_RESPONSE),
            patch("jarvis.tools.cad_generator.execute_cad_code", side_effect=exec_side_effect),
            patch("jarvis.tools.cad_generator.make_output_path", return_value=stl),
            patch("jarvis.tools.cad_generator.save_session"),
        ):
            result = run_cad_generator({"description": "a box", "max_retries": 3})
        assert result["ok"] is True
        assert result["attempts"] == 2

    def test_all_retries_fail_returns_ok_false(self, tmp_models_dir):
        stl = tmp_models_dir / "x.stl"
        with (
            patch("jarvis.tools.cad_generator._detect_llm", return_value=_fake_llm()),
            patch("jarvis.tools.cad_generator._call_llm", return_value=_VALID_LLM_RESPONSE),
            patch("jarvis.tools.cad_generator.execute_cad_code", return_value=(False, "OCC error")),
            patch("jarvis.tools.cad_generator.make_output_path", return_value=stl),
        ):
            result = run_cad_generator({"description": "a box", "max_retries": 2})
        assert result["ok"] is False
        assert result["attempts"] == 2

    # ── Session / iteration ───────────────────────────────────────────────────

    def test_iteration_sends_existing_code_to_llm(self, tmp_models_dir):
        session_file = tmp_models_dir / ".cad_sessions.json"
        existing_sid = str(uuid.uuid4())
        session_data = {
            "sessions": {existing_sid: {"code": "old_code_here()", "iterations": 1}}
        }
        session_file.write_text(json.dumps(session_data), encoding="utf-8")

        stl = self._make_stl(tmp_models_dir)
        captured_prompts = []

        def capture_llm(system, user, llm):
            captured_prompts.append(user)
            return _VALID_LLM_RESPONSE

        with (
            patch("jarvis.tools.cad_generator._detect_llm", return_value=_fake_llm()),
            patch("jarvis.tools.cad_generator._call_llm", side_effect=capture_llm),
            patch("jarvis.tools.cad_generator.execute_cad_code", return_value=(True, "")),
            patch("jarvis.tools.cad_generator.make_output_path", return_value=stl),
            patch("jarvis.tools.cad_generator.save_session"),
        ):
            result = run_cad_generator({
                "description": "make it taller",
                "session_id": existing_sid,
            })
        assert result["ok"] is True
        # LLM must receive the existing code in the iteration prompt
        assert any("old_code_here()" in p for p in captured_prompts)

    # ── open_viewer ───────────────────────────────────────────────────────────

    def test_open_viewer_calls_popen(self, tmp_models_dir):
        stl = self._make_stl(tmp_models_dir)
        with (
            patch("jarvis.tools.cad_generator._detect_llm", return_value=_fake_llm()),
            patch("jarvis.tools.cad_generator._call_llm", return_value=_VALID_LLM_RESPONSE),
            patch("jarvis.tools.cad_generator.execute_cad_code", return_value=(True, "")),
            patch("jarvis.tools.cad_generator.make_output_path", return_value=stl),
            patch("jarvis.tools.cad_generator.save_session"),
            patch("subprocess.Popen") as mock_popen,
        ):
            result = run_cad_generator({"description": "a box", "open_viewer": True})
        assert result["ok"] is True
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args[0][0]
        assert "open" in call_args

    def test_open_viewer_false_does_not_call_popen(self, tmp_models_dir):
        stl = self._make_stl(tmp_models_dir)
        with (
            patch("jarvis.tools.cad_generator._detect_llm", return_value=_fake_llm()),
            patch("jarvis.tools.cad_generator._call_llm", return_value=_VALID_LLM_RESPONSE),
            patch("jarvis.tools.cad_generator.execute_cad_code", return_value=(True, "")),
            patch("jarvis.tools.cad_generator.make_output_path", return_value=stl),
            patch("jarvis.tools.cad_generator.save_session"),
            patch("subprocess.Popen") as mock_popen,
        ):
            run_cad_generator({"description": "a box", "open_viewer": False})
        mock_popen.assert_not_called()
