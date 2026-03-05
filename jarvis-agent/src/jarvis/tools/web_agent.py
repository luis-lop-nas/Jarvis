"""
web_agent.py

Tool: web_agent
Agente de navegación web autónoma usando Playwright + LLM.

Capacidades:
- Navegar a URLs específicas
- Buscar en Google y navegar a resultados
- Hacer clic en elementos por descripción o selector CSS
- Rellenar formularios (con confirmación para datos personales)
- Extraer información de páginas (precios, textos, tablas)
- Hacer scroll y navegar entre páginas
- Tomar screenshots de lo que ve

Casos de uso:
- "Ve a Amazon y busca el iPhone más barato"
- "Rellena el formulario de contacto de esta web"
- "Extrae los precios de esta página"
- "Loguéate en [web] con estas credenciales"

Instalación:
    pip install playwright
    playwright install chromium
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

try:
    from playwright.sync_api import (
        sync_playwright,
        Browser,
        BrowserContext,
        Page,
        TimeoutError as PlaywrightTimeout,
    )
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False
    sync_playwright = None  # type: ignore[assignment]

    class PlaywrightTimeout(Exception):  # type: ignore[no-redef]
        """Stub para cuando Playwright no está instalado."""

# ---------------------------------------------------------------------------
# Browser pool — instancia persistente de Chromium entre llamadas
# ---------------------------------------------------------------------------

import threading as _threading

_browser_lock = _threading.Lock()
_pw_ctx: Any = None          # sync_playwright().__enter__()
_browser: Optional[Any] = None  # Browser activo
_pw_func_ref: Any = None     # Referencia a sync_playwright usada al crear _browser


def _get_or_create_browser(headless: bool = True) -> Any:
    """
    Devuelve el Browser singleton reutilizable, lanzando Chromium solo la primera vez
    (o si se ha desconectado / sync_playwright fue reemplazado por un mock en tests).
    Ahorra 2-5s de startup por llamada en producción.
    """
    global _pw_ctx, _browser, _pw_func_ref
    with _browser_lock:
        # Detectar si sync_playwright fue patcheado (tests) o el browser se desconectó
        pw_changed = (_pw_func_ref is not sync_playwright)
        browser_dead = (_browser is None or not _browser.is_connected())
        if pw_changed or browser_dead:
            if _pw_ctx is not None:
                try:
                    _pw_ctx.__exit__(None, None, None)
                except Exception:
                    pass
            _pw_func_ref = sync_playwright
            _pw_ctx = sync_playwright().__enter__()
            _browser = _pw_ctx.chromium.launch(
                headless=headless,
                args=[
                    f"--window-size={_VIEWPORT_W},{_VIEWPORT_H}",
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            )
        return _browser


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_GLOBAL_TIMEOUT_SEC = 120       # Timeout máximo por tarea
_DEFAULT_MAX_STEPS   = 20       # Pasos máximos del agente
_VIEWPORT_W          = 1440
_VIEWPORT_H          = 900
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

# Patrones que indican acciones sensibles que requieren confirmación del usuario
_SENSITIVE_PATTERNS: List[str] = [
    r"\bcomprar?\b",
    r"\bbuy\b",
    r"\bpurchase\b",
    r"\bcheckout\b",
    r"\bpagar?\b",
    r"\bpay\b",
    r"\bconfirm.*order\b",
    r"\bconfirmar.*pedido\b",
    r"\bsubmit.*form\b",
    r"\benviar.*formulario\b",
    r"\bplace.*order\b",
    r"\bsign[- ]?in\b",
    r"\blog[- ]?in\b",
    r"\biniciar.*sesi[oó]n\b",
    r"\btransfer(?:encia)?\b",
    r"\bdelete\b",
    r"\bborrar\b",
    r"\beliminar\b",
    r"\bpassword\b",
    r"\bcontrase[ñn]a\b",
]

# ---------------------------------------------------------------------------
# Prompt del sistema para el mini-agente de navegación
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a web navigation agent integrated into JARVIS, an AI assistant for macOS.
Your job is to accomplish the user's task by controlling a Chromium browser step by step.

Each turn you receive:
- The current TASK
- Current URL and page TITLE
- A list of INTERACTIVE ELEMENTS visible on the page (tag, text, CSS selector)
- Optionally a SCREENSHOT (if a vision-capable LLM is used)

Respond with EXACTLY ONE JSON object — no markdown, no explanation, just JSON.

AVAILABLE ACTIONS:
  {"action":"navigate","url":"https://..."}
  {"action":"google_search","query":"search terms"}
  {"action":"click","selector":"css_selector","fallback_text":"visible text","description":"what you click"}
  {"action":"type","selector":"css_selector","text":"text to type","clear_first":true,"description":"field label"}
  {"action":"press_enter","selector":"css_selector"}
  {"action":"scroll","direction":"down","pixels":500}
  {"action":"wait","seconds":1}
  {"action":"extract","description":"what info to extract (prices, text, table…)"}
  {"action":"screenshot"}
  {"action":"ask_confirmation","message":"Human-readable message describing the sensitive action"}
  {"action":"done","result":"The final answer or extracted data to report to the user"}

RULES:
1. Return ONLY valid JSON — nothing else.
2. ALWAYS use "ask_confirmation" before: making purchases, logging in, submitting forms, deleting data.
3. If a selector fails, try fallback_text. If both fail, scroll down and retry once.
4. Prefer specific selectors: #id > [name=x] > [placeholder=x] > text match.
5. When the task is complete or you have the requested information, use "done" immediately.
6. If stuck after 3 consecutive failures, use "done" with whatever partial result you found.
7. For data extraction tasks, use "extract" and describe what you want in plain language.
8. When searching on Google, click the most relevant result using its text.
"""

# ---------------------------------------------------------------------------
# Detección de acciones sensibles
# ---------------------------------------------------------------------------

def _is_sensitive(text: str) -> bool:
    """Devuelve True si el texto contiene keywords de acciones sensibles."""
    lower = text.lower()
    return any(re.search(p, lower) for p in _SENSITIVE_PATTERNS)


# ---------------------------------------------------------------------------
# Extracción de estado de la página
# ---------------------------------------------------------------------------

_EXTRACT_ELEMENTS_JS = """\
() => {
    const results = [];
    const seen = new Set();
    const query = [
        'a[href]', 'button', 'input', 'select', 'textarea',
        '[role="button"]', '[role="link"]', '[role="menuitem"]',
        '[role="option"]', '[tabindex="0"]'
    ].join(',');

    document.querySelectorAll(query).forEach((el) => {
        const rect = el.getBoundingClientRect();
        if (rect.width < 1 || rect.height < 1) return;
        if (rect.top < -100 || rect.top > window.innerHeight + 100) return;

        const text = (
            el.innerText ||
            el.value ||
            el.placeholder ||
            el.getAttribute('aria-label') ||
            el.getAttribute('title') ||
            el.getAttribute('alt') ||
            ''
        ).trim().slice(0, 80);

        // Build a reliable CSS selector
        let sel = '';
        const id = el.id ? el.id.trim() : '';
        const name = el.getAttribute('name') || '';
        const testid = el.getAttribute('data-testid') || '';
        const placeholder = el.getAttribute('placeholder') || '';
        const ariaLabel = el.getAttribute('aria-label') || '';

        if (id) {
            sel = '#' + CSS.escape(id);
        } else if (testid) {
            sel = '[data-testid="' + testid + '"]';
        } else if (name) {
            sel = el.tagName.toLowerCase() + '[name="' + name + '"]';
        } else if (placeholder) {
            sel = el.tagName.toLowerCase() + '[placeholder="' + placeholder + '"]';
        } else if (ariaLabel) {
            sel = '[aria-label="' + ariaLabel + '"]';
        } else {
            const parent = el.parentElement;
            if (parent) {
                const idx = Array.from(parent.children).indexOf(el);
                sel = el.tagName.toLowerCase() + ':nth-child(' + (idx + 1) + ')';
            }
        }

        const key = sel + '||' + text;
        if (!seen.has(key)) {
            seen.add(key);
            results.push({
                tag: el.tagName.toLowerCase(),
                type: el.getAttribute('type') || '',
                text: text,
                href: el.href || '',
                selector: sel,
            });
        }
    });

    return results.slice(0, 60);
}
"""

_EXTRACT_CONTENT_JS = """\
() => {
    const candidates = [
        'main', 'article', '[role="main"]', '#content', '.content',
        '#main', '.main', '.results', '#results', 'body'
    ];
    for (const sel of candidates) {
        const el = document.querySelector(sel);
        if (el && el.innerText && el.innerText.trim().length > 50) {
            return el.innerText.trim().slice(0, 4000);
        }
    }
    return document.body.innerText.trim().slice(0, 4000);
}
"""


def _get_page_elements(page: "Page") -> List[Dict]:
    """Extrae elementos interactivos visibles de la página via JS."""
    try:
        return page.evaluate(_EXTRACT_ELEMENTS_JS) or []
    except Exception:
        return []


def _take_screenshot(page: "Page") -> Optional[str]:
    """Captura screenshot de la página. Devuelve base64 PNG o None."""
    try:
        data = page.screenshot(type="png", full_page=False)
        return base64.b64encode(data).decode()
    except Exception:
        return None


def _extract_content(page: "Page") -> str:
    """Extrae texto de contenido principal de la página."""
    try:
        return page.evaluate(_EXTRACT_CONTENT_JS) or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Detección de LLM disponible
# ---------------------------------------------------------------------------

def _detect_llm_config() -> Optional[Dict]:
    """
    Detecta qué LLM usar para las decisiones de navegación.
    Prioridad: Claude (visión) > Gemini (visión) > Groq (texto)
    """
    # Claude
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    use_claude = os.getenv("USE_CLAUDE", "false").lower() == "true"
    if anthropic_key and use_claude:
        return {
            "provider": "claude",
            "api_key": anthropic_key,
            "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
            "vision": True,
        }

    # Gemini
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    use_gemini = os.getenv("USE_GEMINI", "false").lower() == "true"
    if gemini_key and use_gemini:
        return {
            "provider": "gemini",
            "api_key": gemini_key,
            "model": os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
            "vision": True,
        }

    # Groq (texto, sin visión)
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    use_groq = os.getenv("USE_GROQ", "false").lower() == "true"
    if groq_key and use_groq:
        return {
            "provider": "groq",
            "api_key": groq_key,
            "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            "vision": False,
        }

    # Fallback: cualquier key disponible
    if anthropic_key:
        return {
            "provider": "claude",
            "api_key": anthropic_key,
            "model": "claude-sonnet-4-6",
            "vision": True,
        }
    if groq_key:
        return {
            "provider": "groq",
            "api_key": groq_key,
            "model": "llama-3.3-70b-versatile",
            "vision": False,
        }

    return None


# ---------------------------------------------------------------------------
# Construcción de mensajes para el LLM
# ---------------------------------------------------------------------------

def _format_elements(elements: List[Dict], limit: int = 40) -> str:
    """Formatea la lista de elementos para incluir en el prompt."""
    lines = []
    for el in elements[:limit]:
        tag = el.get("tag", "")
        text = el.get("text", "")
        sel = el.get("selector", "")
        href = el.get("href", "")
        if text or href:
            extra = f" → {href[:60]}" if href and tag == "a" else ""
            lines.append(f"  [{tag}] '{text}'{extra}  ↦ {sel}")
    return "\n".join(lines) if lines else "  (sin elementos interactivos visibles)"


def _build_user_message(
    task: str,
    page_state: Dict,
    history: List[Dict],
    screenshot_b64: Optional[str],
    use_vision: bool,
) -> Any:
    """
    Construye el contenido del mensaje de usuario.
    Con visión devuelve lista de bloques (texto + imagen).
    Sin visión devuelve string.
    """
    elements_str = _format_elements(page_state.get("elements", []))
    text = (
        f"TASK: {task}\n"
        f"URL: {page_state['url']}\n"
        f"TITLE: {page_state['title']}\n"
        f"INTERACTIVE ELEMENTS:\n{elements_str}\n"
    )
    if history:
        last = history[-1]
        text += f"\nLAST ACTION: {json.dumps(last['action'])}\nRESULT: {last['result']}\n"

    if use_vision and screenshot_b64:
        return [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": screenshot_b64,
                },
            },
            {"type": "text", "text": text},
        ]
    return text


# ---------------------------------------------------------------------------
# Llamadas al LLM
# ---------------------------------------------------------------------------

def _parse_json_response(raw: str) -> Optional[Dict]:
    """Extrae y parsea un objeto JSON de una respuesta de texto."""
    raw = raw.strip()
    # Intenta JSON directo
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Busca el primer { ... } en el texto
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def _call_claude(
    task: str,
    page_state: Dict,
    history: List[Dict],
    screenshot_b64: Optional[str],
    api_key: str,
    model: str,
) -> Optional[Dict]:
    """Llama a Claude con soporte de visión."""
    try:
        from anthropic import Anthropic  # type: ignore

        client = Anthropic(api_key=api_key)

        # Historial compacto (últimas 4 interacciones)
        messages: List[Dict] = []
        for item in history[-4:]:
            messages.append({"role": "user", "content": json.dumps(item["action"])})
            messages.append({"role": "assistant", "content": f"Result: {item['result']}"})

        user_content = _build_user_message(task, page_state, [], screenshot_b64, use_vision=True)
        messages.append({"role": "user", "content": user_content})

        resp = client.messages.create(
            model=model,
            max_tokens=512,
            system=_SYSTEM_PROMPT,
            messages=messages,
        )
        return _parse_json_response(resp.content[0].text)
    except Exception as e:
        print(f"[WebAgent/Claude] Error: {e}")
        return None


def _call_groq(
    task: str,
    page_state: Dict,
    history: List[Dict],
    api_key: str,
    model: str,
) -> Optional[Dict]:
    """Llama a Groq (sin visión, texto puro)."""
    try:
        import requests  # type: ignore

        messages: List[Dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]

        # Historial compacto
        for item in history[-6:]:
            messages.append({"role": "assistant", "content": json.dumps(item["action"])})
            if item.get("result"):
                messages.append({"role": "user", "content": f"Action result: {item['result']}"})

        user_text = _build_user_message(task, page_state, [], None, use_vision=False)
        messages.append({"role": "user", "content": user_text})

        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "temperature": 0.1,
                "max_tokens": 512,
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return _parse_json_response(content)
    except Exception as e:
        print(f"[WebAgent/Groq] Error: {e}")
        return None


def _call_gemini(
    task: str,
    page_state: Dict,
    history: List[Dict],
    screenshot_b64: Optional[str],
    api_key: str,
    model: str,
) -> Optional[Dict]:
    """Llama a Gemini con soporte de visión."""
    try:
        import requests  # type: ignore

        parts: List[Dict] = []
        if screenshot_b64:
            parts.append({
                "inline_data": {
                    "mime_type": "image/png",
                    "data": screenshot_b64,
                }
            })
        user_text = _build_user_message(task, page_state, history[-3:], None, use_vision=False)
        parts.append({"text": user_text})

        payload = {
            "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 512},
        }

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        content = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        return _parse_json_response(content)
    except Exception as e:
        print(f"[WebAgent/Gemini] Error: {e}")
        return None


def _get_next_action(
    task: str,
    page_state: Dict,
    history: List[Dict],
    screenshot_b64: Optional[str],
    llm_config: Dict,
) -> Optional[Dict]:
    """Solicita al LLM la siguiente acción de navegación."""
    provider = llm_config["provider"]
    api_key  = llm_config["api_key"]
    model    = llm_config["model"]

    if provider == "claude":
        return _call_claude(task, page_state, history, screenshot_b64, api_key, model)
    elif provider == "groq":
        return _call_groq(task, page_state, history, api_key, model)
    elif provider == "gemini":
        return _call_gemini(task, page_state, history, screenshot_b64, api_key, model)
    return None


# ---------------------------------------------------------------------------
# Ejecución de acciones en el navegador
# ---------------------------------------------------------------------------

def _execute_action(page: "Page", action: Dict) -> Tuple[bool, str]:
    """
    Ejecuta una acción en el navegador.
    Devuelve (éxito, mensaje_resultado).
    """
    act = action.get("action", "")

    try:
        # ── Navegación ──────────────────────────────────────────────────────
        if act == "navigate":
            url = action.get("url", "").strip()
            if not url:
                return False, "No se proporcionó URL"
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(1_500)
            return True, f"Navegado a {page.url}"

        # ── Búsqueda en Google ───────────────────────────────────────────────
        elif act == "google_search":
            query = action.get("query", "").strip()
            if not query:
                return False, "No se proporcionó query"
            search_url = f"https://www.google.com/search?q={quote_plus(query)}&hl=es"
            page.goto(search_url, wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(1_200)
            return True, f"Búsqueda en Google: {query}"

        # ── Clic ────────────────────────────────────────────────────────────
        elif act == "click":
            selector     = action.get("selector", "")
            fallback_text = action.get("fallback_text", "")
            description  = action.get("description", "elemento")

            # 1. Selector CSS directo
            if selector:
                try:
                    page.click(selector, timeout=5_000)
                    page.wait_for_timeout(1_200)
                    return True, f"Clic en: {description} ({selector})"
                except Exception:
                    pass

            # 2. Texto visible (getByText)
            if fallback_text:
                try:
                    page.get_by_text(fallback_text, exact=False).first.click(timeout=5_000)
                    page.wait_for_timeout(1_200)
                    return True, f"Clic en texto '{fallback_text}'"
                except Exception:
                    pass

            # 3. Búsqueda por role + nombre
            if fallback_text:
                try:
                    page.get_by_role("link", name=fallback_text).first.click(timeout=3_000)
                    page.wait_for_timeout(1_200)
                    return True, f"Clic en enlace '{fallback_text}'"
                except Exception:
                    pass
                try:
                    page.get_by_role("button", name=fallback_text).first.click(timeout=3_000)
                    page.wait_for_timeout(1_200)
                    return True, f"Clic en botón '{fallback_text}'"
                except Exception:
                    pass

            return False, f"Elemento no encontrado: {description}"

        # ── Escribir en un campo ─────────────────────────────────────────────
        elif act == "type":
            selector    = action.get("selector", "")
            text        = action.get("text", "")
            clear_first = action.get("clear_first", True)
            description = action.get("description", "campo")

            def _do_type(locator: Any) -> Tuple[bool, str]:
                if clear_first:
                    locator.clear(timeout=4_000)
                locator.type(text, delay=40, timeout=10_000)
                page.wait_for_timeout(400)
                return True, f"Escrito en {description}"

            # 1. Selector CSS
            if selector:
                try:
                    return _do_type(page.locator(selector).first)
                except Exception:
                    pass

            # 2. Placeholder
            placeholder = action.get("placeholder", description)
            try:
                return _do_type(page.get_by_placeholder(placeholder, exact=False).first)
            except Exception:
                pass

            # 3. Label
            try:
                return _do_type(page.get_by_label(description, exact=False).first)
            except Exception:
                pass

            return False, f"Campo no encontrado: {description}"

        # ── Pulsar Enter ─────────────────────────────────────────────────────
        elif act == "press_enter":
            selector = action.get("selector", "")
            if selector:
                try:
                    page.press(selector, "Enter", timeout=5_000)
                except Exception:
                    page.keyboard.press("Enter")
            else:
                page.keyboard.press("Enter")
            page.wait_for_timeout(1_500)
            return True, "Enter pulsado"

        # ── Scroll ───────────────────────────────────────────────────────────
        elif act == "scroll":
            direction = action.get("direction", "down").lower()
            pixels    = int(action.get("pixels", 500))
            delta     = pixels if direction == "down" else -pixels
            page.evaluate(f"window.scrollBy(0, {delta})")
            page.wait_for_timeout(600)
            return True, f"Scroll {direction} {abs(delta)}px"

        # ── Esperar ──────────────────────────────────────────────────────────
        elif act == "wait":
            secs = min(float(action.get("seconds", 1)), 5.0)
            page.wait_for_timeout(int(secs * 1_000))
            return True, f"Esperado {secs}s"

        # ── Extraer contenido ────────────────────────────────────────────────
        elif act == "extract":
            description = action.get("description", "")
            content = _extract_content(page)
            if not content:
                return False, "No se encontró contenido en la página"
            # Truncar si es muy largo
            summary = content[:3_000]
            return True, summary

        # ── Screenshot ───────────────────────────────────────────────────────
        elif act == "screenshot":
            # No hacemos nada extra — el loop ya captura screenshots
            return True, "Screenshot capturado"

        # ── Acciones terminales ───────────────────────────────────────────────
        elif act == "done":
            return True, action.get("result", "Tarea completada")

        elif act == "ask_confirmation":
            return True, action.get("message", "")

        else:
            return False, f"Acción desconocida: {act!r}"

    except PlaywrightTimeout:
        return False, f"Timeout en acción '{act}'"
    except Exception as e:
        return False, f"Error en '{act}': {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------------

def run_web_agent(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Agente de navegación web autónoma.

    Args:
        task (str): Descripción de la tarea a realizar. (obligatorio)
        url (str): URL inicial. Si se omite, el agente decide desde dónde empezar.
        max_steps (int): Pasos máximos del agente (default 20).
        headless (bool): Si es True, el navegador no es visible (default False).
        force_sensitive (bool): Si True, omite confirmaciones en acciones sensibles.
            ÚSALO CON CUIDADO. (default False)

    Returns:
        {
          "ok": bool,
          "result": str,         # Resultado final o información extraída
          "steps_taken": int,
          "requires_confirmation": str | None,  # Si el agente pidió confirmación
          "llm_provider": str,
          "error": str           # Solo si ok=False
        }
    """
    if not _PLAYWRIGHT_AVAILABLE:
        return {
            "ok": False,
            "error": (
                "Playwright no está instalado. Ejecuta:\n"
                "  pip install playwright\n"
                "  playwright install chromium"
            ),
        }

    task = str(args.get("task", "")).strip()
    if not task:
        return {"ok": False, "error": "Falta args['task']: descripción de la tarea."}

    start_url        = str(args.get("url", "")).strip()
    max_steps        = int(args.get("max_steps", _DEFAULT_MAX_STEPS))
    headless         = bool(args.get("headless", False))
    force_sensitive  = bool(args.get("force_sensitive", False))

    llm_config = _detect_llm_config()
    if not llm_config:
        return {
            "ok": False,
            "error": (
                "No hay LLM configurado para el agente web. "
                "Configura ANTHROPIC_API_KEY, GEMINI_API_KEY o GROQ_API_KEY en .env."
            ),
        }

    history: List[Dict]       = []
    result_text               = ""
    requires_confirmation: Optional[str] = None
    steps_taken               = 0
    consecutive_failures      = 0
    start_time                = time.monotonic()

    print(
        f"[WebAgent] Iniciando tarea: {task!r} | "
        f"LLM: {llm_config['provider']} | headless={headless}"
    )

    try:
        browser: Browser = _get_or_create_browser(headless=headless)
        ctx: BrowserContext = browser.new_context(
            viewport={"width": _VIEWPORT_W, "height": _VIEWPORT_H},
            user_agent=_USER_AGENT,
        )
        page: Page = ctx.new_page()

        try:
            # Navegar a URL inicial si se proporcionó
            if start_url:
                if not start_url.startswith(("http://", "https://")):
                    start_url = "https://" + start_url
                try:
                    page.goto(start_url, wait_until="domcontentloaded", timeout=20_000)
                    page.wait_for_timeout(1_000)
                except Exception as e:
                    print(f"[WebAgent] Advertencia navegando a URL inicial: {e}")

            # ── Bucle principal del agente ────────────────────────────────
            for step in range(max_steps):
                steps_taken = step + 1

                # Comprobar timeout global
                elapsed = time.monotonic() - start_time
                if elapsed > _GLOBAL_TIMEOUT_SEC:
                    result_text = (
                        f"Timeout de {_GLOBAL_TIMEOUT_SEC}s alcanzado. "
                        f"Resultado parcial: {result_text or 'sin resultado'}"
                    )
                    break

                # Estado actual de la página
                page_state = {
                    "url": page.url,
                    "title": page.title() if page.url not in ("about:blank", "") else "",
                    "elements": _get_page_elements(page),
                }

                # Screenshot (solo si el LLM soporta visión)
                screenshot_b64 = None
                if llm_config.get("vision"):
                    screenshot_b64 = _take_screenshot(page)

                print(
                    f"[WebAgent] Paso {step+1}/{max_steps} | "
                    f"URL: {page_state['url'][:60]} | "
                    f"Elementos: {len(page_state['elements'])}"
                )

                # Decisión del LLM
                action = _get_next_action(
                    task, page_state, history, screenshot_b64, llm_config
                )

                if not action:
                    consecutive_failures += 1
                    print(f"[WebAgent] LLM no respondió (fallo #{consecutive_failures})")
                    if consecutive_failures >= 3:
                        result_text = "El LLM no respondió correctamente en 3 intentos."
                        break
                    continue
                else:
                    consecutive_failures = 0

                act_type = action.get("action", "")
                print(f"[WebAgent] Acción: {act_type} | {json.dumps(action)[:120]}")

                # ── Acciones terminales ───────────────────────────────────
                if act_type == "done":
                    result_text = action.get("result", "Tarea completada")
                    break

                if act_type == "ask_confirmation":
                    msg = action.get("message", "¿Confirmas esta acción?")
                    if not force_sensitive:
                        requires_confirmation = msg
                        result_text = f"Confirmación requerida: {msg}"
                        break
                    # force_sensitive=True: continuar sin pausa
                    history.append({"action": action, "result": "confirmed", "success": True})
                    continue

                # ── Comprobación de sensibilidad ─────────────────────────
                if not force_sensitive:
                    combined = " ".join([
                        action.get("description", ""),
                        action.get("text", ""),
                        action.get("url", ""),
                    ])
                    if _is_sensitive(combined):
                        requires_confirmation = (
                            f"Estoy a punto de {act_type}: {combined.strip()[:200]}. "
                            "¿Confirmas?"
                        )
                        result_text = f"Confirmación requerida: {requires_confirmation}"
                        break

                # ── Ejecutar acción ──────────────────────────────────────
                success, msg = _execute_action(page, action)
                print(
                    f"[WebAgent] {'✓' if success else '✗'} "
                    f"{act_type}: {msg[:100]}"
                )

                history.append({
                    "action": action,
                    "result": msg,
                    "success": success,
                })

                if not success:
                    consecutive_failures += 1
                    if consecutive_failures >= 4:
                        result_text = (
                            f"Demasiados fallos consecutivos ({consecutive_failures}). "
                            f"Última info: {msg}"
                        )
                        break
                else:
                    consecutive_failures = 0

            # Fin del bucle
            if not result_text:
                result_text = (
                    f"Se alcanzó el límite de {max_steps} pasos. "
                    "El agente no devolvió un resultado final explícito."
                )

        finally:
            # Cerrar solo el contexto (tab aislado), no el browser (se reutiliza)
            try:
                ctx.close()
            except Exception:
                pass

    except Exception as e:
        return {
            "ok": False,
            "error": f"Error en el agente web: {type(e).__name__}: {e}",
            "steps_taken": steps_taken,
        }

    return {
        "ok": True,
        "result": result_text,
        "steps_taken": steps_taken,
        "requires_confirmation": requires_confirmation,
        "llm_provider": llm_config["provider"],
    }
