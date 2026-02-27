"""
test_web_agent.py

Tests unitarios para la tool web_agent.
El navegador y las llamadas al LLM se mockean completamente.

Run with:
    cd jarvis-agent
    source .venv/bin/activate
    PYTHONPATH=src pytest tests/test_web_agent.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


from jarvis.tools.web_agent import (
    _is_sensitive,
    _format_elements,
    _parse_json_response,
    _detect_llm_config,
    _execute_action,
    PlaywrightTimeout,
    run_web_agent,
)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _mock_page(url: str = "https://example.com", title: str = "Example") -> MagicMock:
    """Crea un Page mock con comportamiento básico."""
    page = MagicMock()
    page.url = url
    page.title.return_value = title
    page.evaluate.return_value = []
    page.screenshot.return_value = b"\x89PNG\r\n"
    return page


# ── _is_sensitive ────────────────────────────────────────────────────────────

class TestIsSensitive:
    def test_comprar(self):
        assert _is_sensitive("quiero comprar un producto")

    def test_buy(self):
        assert _is_sensitive("click the buy now button")

    def test_purchase(self):
        assert _is_sensitive("purchase this item")

    def test_checkout(self):
        assert _is_sensitive("proceed to checkout")

    def test_login(self):
        assert _is_sensitive("log in with your credentials")

    def test_sign_in(self):
        assert _is_sensitive("sign-in to your account")

    def test_submit_form(self):
        assert _is_sensitive("submit form data")

    def test_delete(self):
        assert _is_sensitive("delete the record")

    def test_borrar(self):
        assert _is_sensitive("voy a borrar este archivo")

    def test_transferencia(self):
        assert _is_sensitive("hacer una transferencia bancaria")

    def test_password(self):
        assert _is_sensitive("enter your password")

    def test_contraseña(self):
        assert _is_sensitive("introduce tu contraseña")

    def test_safe_navigate(self):
        assert not _is_sensitive("navigate to amazon.com")

    def test_safe_search(self):
        assert not _is_sensitive("search for iphone prices")

    def test_safe_extract(self):
        assert not _is_sensitive("extract prices from the page")

    def test_safe_click(self):
        assert not _is_sensitive("click the search button")

    def test_safe_scroll(self):
        assert not _is_sensitive("scroll down the page")

    def test_empty_string(self):
        assert not _is_sensitive("")

    def test_case_insensitive(self):
        assert _is_sensitive("COMPRAR ahora")
        assert _is_sensitive("Buy NOW")

    def test_confirmar_pedido(self):
        assert _is_sensitive("confirmar pedido de 50 euros")

    def test_place_order(self):
        assert _is_sensitive("place order now")


# ── _format_elements ─────────────────────────────────────────────────────────

class TestFormatElements:
    def test_empty_list(self):
        result = _format_elements([])
        assert "sin elementos" in result.lower()

    def test_single_button(self):
        elements = [{"tag": "button", "text": "Comprar ahora", "selector": "#buy-btn", "href": ""}]
        result = _format_elements(elements)
        assert "button" in result
        assert "Comprar ahora" in result
        assert "#buy-btn" in result

    def test_link_shows_href(self):
        elements = [{"tag": "a", "text": "Ver más", "selector": "a.more", "href": "https://example.com/more"}]
        result = _format_elements(elements)
        assert "example.com/more" in result

    def test_limit_respected(self):
        elements = [{"tag": "button", "text": f"Btn{i}", "selector": f"#b{i}", "href": ""} for i in range(50)]
        result = _format_elements(elements, limit=5)
        assert result.count("[button]") == 5

    def test_no_text_element_skipped(self):
        elements = [
            {"tag": "button", "text": "", "selector": "#empty", "href": ""},
            {"tag": "a", "text": "Inicio", "selector": "#home", "href": ""},
        ]
        result = _format_elements(elements)
        # El botón sin texto no aparece, el link sí
        assert "#empty" not in result
        assert "Inicio" in result


# ── _parse_json_response ─────────────────────────────────────────────────────

class TestParseJsonResponse:
    def test_clean_json(self):
        raw = '{"action":"navigate","url":"https://amazon.es"}'
        result = _parse_json_response(raw)
        assert result == {"action": "navigate", "url": "https://amazon.es"}

    def test_json_with_markdown(self):
        raw = "```json\n{\"action\":\"done\",\"result\":\"Precio: 599€\"}\n```"
        result = _parse_json_response(raw)
        assert result is not None
        assert result["action"] == "done"

    def test_json_with_extra_text(self):
        raw = "Aquí está la acción: {\"action\":\"click\",\"selector\":\"#btn\"}"
        result = _parse_json_response(raw)
        assert result == {"action": "click", "selector": "#btn"}

    def test_invalid_json(self):
        result = _parse_json_response("esto no es json")
        assert result is None

    def test_empty_string(self):
        result = _parse_json_response("")
        assert result is None

    def test_nested_json(self):
        raw = '{"action":"type","selector":"#q","text":"iPhone","clear_first":true}'
        result = _parse_json_response(raw)
        assert result["text"] == "iPhone"
        assert result["clear_first"] is True


# ── _detect_llm_config ───────────────────────────────────────────────────────

class TestDetectLlmConfig:
    def test_claude_when_enabled(self):
        env = {
            "USE_CLAUDE": "true",
            "ANTHROPIC_API_KEY": "sk-test",
            "ANTHROPIC_MODEL": "claude-sonnet-4-6",
            "USE_GROQ": "false",
            "GROQ_API_KEY": "",
            "USE_GEMINI": "false",
            "GEMINI_API_KEY": "",
        }
        with patch.dict("os.environ", env, clear=False):
            cfg = _detect_llm_config()
        assert cfg is not None
        assert cfg["provider"] == "claude"
        assert cfg["vision"] is True
        assert cfg["api_key"] == "sk-test"

    def test_groq_when_enabled(self):
        env = {
            "USE_CLAUDE": "false",
            "ANTHROPIC_API_KEY": "",
            "USE_GROQ": "true",
            "GROQ_API_KEY": "gsk_test",
            "GROQ_MODEL": "llama-3.3-70b-versatile",
            "USE_GEMINI": "false",
            "GEMINI_API_KEY": "",
        }
        with patch.dict("os.environ", env, clear=False):
            cfg = _detect_llm_config()
        assert cfg is not None
        assert cfg["provider"] == "groq"
        assert cfg["vision"] is False

    def test_no_config_returns_none(self):
        env = {
            "USE_CLAUDE": "false",
            "ANTHROPIC_API_KEY": "",
            "USE_GROQ": "false",
            "GROQ_API_KEY": "",
            "USE_GEMINI": "false",
            "GEMINI_API_KEY": "",
        }
        with patch.dict("os.environ", env, clear=False):
            cfg = _detect_llm_config()
        assert cfg is None

    def test_claude_priority_over_groq(self):
        env = {
            "USE_CLAUDE": "true",
            "ANTHROPIC_API_KEY": "sk-claude",
            "USE_GROQ": "true",
            "GROQ_API_KEY": "gsk_groq",
            "USE_GEMINI": "false",
            "GEMINI_API_KEY": "",
        }
        with patch.dict("os.environ", env, clear=False):
            cfg = _detect_llm_config()
        assert cfg["provider"] == "claude"

    def test_gemini_when_enabled(self):
        env = {
            "USE_CLAUDE": "false",
            "ANTHROPIC_API_KEY": "",
            "USE_GEMINI": "true",
            "GEMINI_API_KEY": "aig-test",
            "GEMINI_MODEL": "gemini-2.0-flash",
            "USE_GROQ": "false",
            "GROQ_API_KEY": "",
        }
        with patch.dict("os.environ", env, clear=False):
            cfg = _detect_llm_config()
        assert cfg["provider"] == "gemini"
        assert cfg["vision"] is True

    def test_fallback_to_any_anthropic_key(self):
        env = {
            "USE_CLAUDE": "false",
            "ANTHROPIC_API_KEY": "sk-fallback",
            "USE_GROQ": "false",
            "GROQ_API_KEY": "",
            "USE_GEMINI": "false",
            "GEMINI_API_KEY": "",
        }
        with patch.dict("os.environ", env, clear=False):
            cfg = _detect_llm_config()
        assert cfg is not None
        assert cfg["provider"] == "claude"


# ── _execute_action ──────────────────────────────────────────────────────────

class TestExecuteAction:
    def test_navigate_success(self):
        page = _mock_page(url="https://amazon.es")
        page.goto.return_value = None
        ok, msg = _execute_action(page, {"action": "navigate", "url": "https://amazon.es"})
        assert ok is True
        assert "amazon.es" in msg
        page.goto.assert_called_once()

    def test_navigate_no_url(self):
        page = _mock_page()
        ok, msg = _execute_action(page, {"action": "navigate", "url": ""})
        assert ok is False
        assert "URL" in msg

    def test_navigate_adds_https(self):
        page = _mock_page()
        ok, msg = _execute_action(page, {"action": "navigate", "url": "amazon.es"})
        args, _ = page.goto.call_args
        assert args[0].startswith("https://")

    def test_google_search(self):
        page = _mock_page()
        page.goto.return_value = None
        ok, msg = _execute_action(page, {"action": "google_search", "query": "iPhone precio"})
        assert ok is True
        assert "iPhone precio" in msg
        called_url = page.goto.call_args[0][0]
        assert "google.com/search" in called_url
        assert "iPhone" in called_url

    def test_google_search_no_query(self):
        page = _mock_page()
        ok, msg = _execute_action(page, {"action": "google_search", "query": ""})
        assert ok is False

    def test_click_by_selector(self):
        page = _mock_page()
        ok, msg = _execute_action(page, {
            "action": "click",
            "selector": "#buy-btn",
            "fallback_text": "Comprar",
            "description": "botón comprar",
        })
        assert ok is True
        page.click.assert_called_once_with("#buy-btn", timeout=5_000)

    def test_click_fallback_text_when_selector_fails(self):
        page = _mock_page()
        page.click.side_effect = PlaywrightTimeout("timeout")

        locator_mock = MagicMock()
        page.get_by_text.return_value = locator_mock
        locator_mock.first = locator_mock

        ok, msg = _execute_action(page, {
            "action": "click",
            "selector": "#bad-selector",
            "fallback_text": "Comprar ahora",
            "description": "botón comprar",
        })
        assert ok is True
        page.get_by_text.assert_called_once()

    def test_click_not_found(self):
        page = _mock_page()
        page.click.side_effect = PlaywrightTimeout("timeout")

        loc = MagicMock()
        loc.first.click.side_effect = PlaywrightTimeout("timeout")
        page.get_by_text.return_value = loc
        page.get_by_role.return_value = loc

        ok, msg = _execute_action(page, {
            "action": "click",
            "selector": "#missing",
            "fallback_text": "Ghost Button",
            "description": "ghost",
        })
        assert ok is False

    def test_scroll_down(self):
        page = _mock_page()
        ok, msg = _execute_action(page, {"action": "scroll", "direction": "down", "pixels": 300})
        assert ok is True
        assert "down" in msg
        page.evaluate.assert_called_with("window.scrollBy(0, 300)")

    def test_scroll_up(self):
        page = _mock_page()
        ok, msg = _execute_action(page, {"action": "scroll", "direction": "up", "pixels": 200})
        assert ok is True
        page.evaluate.assert_called_with("window.scrollBy(0, -200)")

    def test_wait_capped_at_5s(self):
        page = _mock_page()
        ok, msg = _execute_action(page, {"action": "wait", "seconds": 999})
        assert ok is True
        page.wait_for_timeout.assert_called_with(5_000)

    def test_extract_returns_content(self):
        page = _mock_page()
        page.evaluate.return_value = "Precio: 599€"
        ok, msg = _execute_action(page, {"action": "extract", "description": "precios"})
        assert ok is True
        assert "599" in msg

    def test_extract_empty_page(self):
        page = _mock_page()
        page.evaluate.return_value = None
        ok, msg = _execute_action(page, {"action": "extract", "description": "algo"})
        assert ok is False
        assert "no se encontró" in msg.lower() or "No se encontró" in msg

    def test_press_enter(self):
        page = _mock_page()
        ok, msg = _execute_action(page, {"action": "press_enter", "selector": "#search"})
        assert ok is True
        page.press.assert_called_once_with("#search", "Enter", timeout=5_000)

    def test_press_enter_no_selector(self):
        page = _mock_page()
        ok, msg = _execute_action(page, {"action": "press_enter"})
        assert ok is True
        page.keyboard.press.assert_called_once_with("Enter")

    def test_done_action(self):
        page = _mock_page()
        ok, msg = _execute_action(page, {"action": "done", "result": "El iPhone más barato cuesta 499€"})
        assert ok is True
        assert "499" in msg

    def test_ask_confirmation_action(self):
        page = _mock_page()
        ok, msg = _execute_action(page, {"action": "ask_confirmation", "message": "¿Confirmas la compra?"})
        assert ok is True
        assert "compra" in msg.lower()

    def test_unknown_action(self):
        page = _mock_page()
        ok, msg = _execute_action(page, {"action": "teleport"})
        assert ok is False
        assert "teleport" in msg

    def test_playwright_timeout_handled(self):
        page = _mock_page()
        page.goto.side_effect = PlaywrightTimeout("nav timeout")
        ok, msg = _execute_action(page, {"action": "navigate", "url": "https://slow.example.com"})
        assert ok is False
        assert "Timeout" in msg


# ── run_web_agent ─────────────────────────────────────────────────────────────

class TestRunWebAgent:
    def test_no_playwright(self):
        with patch("jarvis.tools.web_agent._PLAYWRIGHT_AVAILABLE", False):
            result = run_web_agent({"task": "busca algo"})
        assert result["ok"] is False
        assert "playwright" in result["error"].lower()

    def test_missing_task(self):
        with patch("jarvis.tools.web_agent._PLAYWRIGHT_AVAILABLE", True):
            result = run_web_agent({})
        assert result["ok"] is False
        assert "task" in result["error"].lower()

    def test_empty_task(self):
        with patch("jarvis.tools.web_agent._PLAYWRIGHT_AVAILABLE", True):
            result = run_web_agent({"task": "  "})
        assert result["ok"] is False

    def test_no_llm_config(self):
        env = {
            "USE_CLAUDE": "false", "ANTHROPIC_API_KEY": "",
            "USE_GROQ": "false", "GROQ_API_KEY": "",
            "USE_GEMINI": "false", "GEMINI_API_KEY": "",
        }
        with patch("jarvis.tools.web_agent._PLAYWRIGHT_AVAILABLE", True):
            with patch.dict("os.environ", env, clear=False):
                result = run_web_agent({"task": "busca algo"})
        assert result["ok"] is False
        assert "llm" in result["error"].lower() or "configurado" in result["error"].lower()

    def _setup_playwright_mock(self, mock_pw, url="https://google.com", title="Google"):
        """Configura un mock completo del entorno Playwright."""
        mock_browser = MagicMock()
        mock_ctx = MagicMock()
        mock_page = MagicMock()
        mock_page.url = url
        mock_page.title.return_value = title
        mock_page.evaluate.return_value = []
        mock_page.screenshot.return_value = b"\x89PNG"

        mock_pw.return_value.__enter__.return_value.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_ctx
        mock_ctx.new_page.return_value = mock_page
        return mock_browser, mock_page

    def _pw_env(self):
        return {"USE_GROQ": "true", "GROQ_API_KEY": "gsk_test",
                "USE_CLAUDE": "false", "ANTHROPIC_API_KEY": ""}

    def test_successful_task(self):
        """Simula una tarea completa con mock del LLM y del navegador."""
        mock_action_sequence = [
            {"action": "google_search", "query": "iPhone precio Amazon"},
            {"action": "click", "selector": "a.result", "fallback_text": "Amazon iPhone", "description": "resultado"},
            {"action": "done", "result": "iPhone 15 desde 799€"},
        ]

        call_count = [0]
        def fake_llm(*args, **kwargs):
            if call_count[0] < len(mock_action_sequence):
                action = mock_action_sequence[call_count[0]]
                call_count[0] += 1
                return action
            return {"action": "done", "result": "fin"}

        with patch("jarvis.tools.web_agent._PLAYWRIGHT_AVAILABLE", True):
            with patch.dict("os.environ", self._pw_env(), clear=False):
                with patch("jarvis.tools.web_agent.sync_playwright") as mock_pw:
                    self._setup_playwright_mock(mock_pw)
                    with patch("jarvis.tools.web_agent._get_next_action", side_effect=fake_llm):
                        result = run_web_agent({"task": "busca el iPhone más barato en Amazon"})

        assert result["ok"] is True
        assert "iPhone" in result["result"] or result["steps_taken"] > 0
        assert result["llm_provider"] == "groq"

    def test_requires_confirmation_on_sensitive(self):
        """El agente debe pedir confirmación ante una acción sensible."""
        def fake_llm(*args, **kwargs):
            return {
                "action": "click",
                "selector": "#checkout",
                "description": "checkout button to buy now",
                "fallback_text": "buy now",
            }

        with patch("jarvis.tools.web_agent._PLAYWRIGHT_AVAILABLE", True):
            with patch.dict("os.environ", self._pw_env(), clear=False):
                with patch("jarvis.tools.web_agent.sync_playwright") as mock_pw:
                    self._setup_playwright_mock(mock_pw, url="https://amazon.es/cart", title="Amazon Cart")
                    with patch("jarvis.tools.web_agent._get_next_action", side_effect=fake_llm):
                        result = run_web_agent({"task": "compra el iPhone"})

        assert result["ok"] is True
        assert result["requires_confirmation"] is not None

    def test_force_sensitive_bypasses_confirmation(self):
        """Con force_sensitive=True, las acciones sensibles se ejecutan sin pedir confirmación."""
        call_count = [0]
        def fake_llm(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] >= 3:
                return {"action": "done", "result": "Compra realizada"}
            return {
                "action": "click",
                "selector": "#buy-now",
                "description": "buy now button",
                "fallback_text": "buy now",
            }

        with patch("jarvis.tools.web_agent._PLAYWRIGHT_AVAILABLE", True):
            with patch.dict("os.environ", self._pw_env(), clear=False):
                with patch("jarvis.tools.web_agent.sync_playwright") as mock_pw:
                    self._setup_playwright_mock(mock_pw, url="https://amazon.es", title="Amazon")
                    with patch("jarvis.tools.web_agent._get_next_action", side_effect=fake_llm):
                        result = run_web_agent({
                            "task": "compra el iPhone",
                            "force_sensitive": True,
                        })

        assert result["ok"] is True
        assert result["requires_confirmation"] is None

    def test_ask_confirmation_from_llm(self):
        """Si el LLM devuelve ask_confirmation, el agente lo devuelve al usuario."""
        def fake_llm(*args, **kwargs):
            return {
                "action": "ask_confirmation",
                "message": "Voy a iniciar sesión con tus credenciales. ¿Confirmas?",
            }

        with patch("jarvis.tools.web_agent._PLAYWRIGHT_AVAILABLE", True):
            with patch.dict("os.environ", self._pw_env(), clear=False):
                with patch("jarvis.tools.web_agent.sync_playwright") as mock_pw:
                    self._setup_playwright_mock(mock_pw, url="https://example.com/login", title="Login")
                    with patch("jarvis.tools.web_agent._get_next_action", side_effect=fake_llm):
                        result = run_web_agent({"task": "loguéate en example.com"})

        assert result["ok"] is True
        assert result["requires_confirmation"] is not None
        assert "credenciales" in result["requires_confirmation"].lower()

    def test_llm_failure_stops_after_3(self):
        """Si el LLM falla 3 veces seguidas, el agente se detiene."""
        def fake_llm(*args, **kwargs):
            return None  # LLM siempre falla

        with patch("jarvis.tools.web_agent._PLAYWRIGHT_AVAILABLE", True):
            with patch.dict("os.environ", self._pw_env(), clear=False):
                with patch("jarvis.tools.web_agent.sync_playwright") as mock_pw:
                    self._setup_playwright_mock(mock_pw)
                    with patch("jarvis.tools.web_agent._get_next_action", side_effect=fake_llm):
                        result = run_web_agent({"task": "busca algo", "max_steps": 10})

        assert result["ok"] is True  # No es un error del sistema
        assert result["steps_taken"] <= 3  # Se detuvo rápido

    def test_result_contains_llm_provider(self):
        def fake_llm(*args, **kwargs):
            return {"action": "done", "result": "terminado"}

        with patch("jarvis.tools.web_agent._PLAYWRIGHT_AVAILABLE", True):
            with patch.dict("os.environ", self._pw_env(), clear=False):
                with patch("jarvis.tools.web_agent.sync_playwright") as mock_pw:
                    self._setup_playwright_mock(mock_pw)
                    with patch("jarvis.tools.web_agent._get_next_action", side_effect=fake_llm):
                        result = run_web_agent({"task": "test"})

        assert "llm_provider" in result
        assert result["llm_provider"] == "groq"

    def test_headless_false_by_default(self):
        """El navegador debe ser visible (headless=False) por defecto."""
        def fake_llm(*args, **kwargs):
            return {"action": "done", "result": "ok"}

        with patch("jarvis.tools.web_agent._PLAYWRIGHT_AVAILABLE", True):
            with patch.dict("os.environ", self._pw_env(), clear=False):
                with patch("jarvis.tools.web_agent.sync_playwright") as mock_pw:
                    self._setup_playwright_mock(mock_pw)
                    with patch("jarvis.tools.web_agent._get_next_action", side_effect=fake_llm):
                        run_web_agent({"task": "test"})

                    launch_call = mock_pw.return_value.__enter__.return_value.chromium.launch
                    launch_kwargs = launch_call.call_args[1]
                    assert launch_kwargs.get("headless") is False

    def test_initial_url_navigated(self):
        """Si se pasa url, el agente navega a ella al inicio."""
        def fake_llm(*args, **kwargs):
            return {"action": "done", "result": "ok"}

        with patch("jarvis.tools.web_agent._PLAYWRIGHT_AVAILABLE", True):
            with patch.dict("os.environ", self._pw_env(), clear=False):
                with patch("jarvis.tools.web_agent.sync_playwright") as mock_pw:
                    _, mock_page = self._setup_playwright_mock(
                        mock_pw, url="https://amazon.es", title="Amazon"
                    )
                    with patch("jarvis.tools.web_agent._get_next_action", side_effect=fake_llm):
                        run_web_agent({"task": "busca iPhone", "url": "https://amazon.es"})

                    # Debe haberse llamado goto con la URL inicial
                    mock_page.goto.assert_called()
                    first_call_url = mock_page.goto.call_args_list[0][0][0]
                    assert "amazon.es" in first_call_url
