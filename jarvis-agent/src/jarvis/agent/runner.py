"""
runner.py

Motor del agente (IA).

Responsabilidades:
- Preparar mensajes (system + historial + mensaje del usuario)
- Llamar al modelo (OpenAI GPT-5 Codex) y devolver la respuesta
- Mantener un historial simple (memoria de sesión)
- Dejar "ganchos" claros para herramientas (tools) en el siguiente paso

Nota: La memoria persistente (SQLite) la conectaremos más adelante en `memory/store.py`.
Aquí mantenemos memoria de sesión para empezar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from jarvis.agent.prompts import SYSTEM_PROMPT

# SDK oficial OpenAI
# (lo instalaste en pyproject.toml)
from openai import OpenAI


# ---------------------------
# Tipos de datos simples
# ---------------------------

Message = Dict[str, str]
# Ejemplo:
# {"role": "system"|"user"|"assistant", "content": "..."}


@dataclass
class AgentConfig:
    """
    Configuración mínima del agente.

    La rellenaremos desde Settings (config.py) para no hardcodear modelos/keys.
    """
    api_key: str
    model: str
    org: str = ""
    project: str = ""
    debug: bool = False


@dataclass
class AgentState:
    """
    Estado de sesión del agente (memoria corta).

    Guardamos el historial como una lista de mensajes.
    """
    history: List[Message] = field(default_factory=list)

    def add_user(self, text: str) -> None:
        self.history.append({"role": "user", "content": text})

    def add_assistant(self, text: str) -> None:
        self.history.append({"role": "assistant", "content": text})

    def clear(self) -> None:
        self.history.clear()


# ---------------------------
# Clase principal: AgentRunner
# ---------------------------

class AgentRunner:
    """
    AgentRunner encapsula el cliente OpenAI y el bucle "mensaje -> respuesta".

    En versiones posteriores, este runner también:
    - registrará tools (tool calling)
    - ejecutará herramientas
    - guardará memoria en SQLite
    """

    def __init__(self, config: AgentConfig, state: Optional[AgentState] = None):
        self.config = config
        self.state = state or AgentState()

        # Creamos el cliente OpenAI.
        # Si usas org/project, el SDK lo soporta.
        # Si no, se quedan vacíos y no pasa nada.
        self.client = OpenAI(
            api_key=self.config.api_key,
            organization=self.config.org or None,
            project=self.config.project or None,
        )

    def build_messages(self, user_text: str) -> List[Message]:
        """
        Construye la lista de mensajes completa para enviar al modelo.

        Orden típico:
        1) System prompt (reglas)
        2) Historial (user/assistant)
        3) Mensaje nuevo del usuario
        """
        messages: List[Message] = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(self.state.history)
        messages.append({"role": "user", "content": user_text})
        return messages

    def run(self, user_text: str) -> str:
        """
        Ejecuta una interacción con el modelo y devuelve el texto del asistente.

        Manejo de errores:
        - Si falta API key, devolvemos un mensaje claro.
        - Si falla la llamada, devolvemos error resumido (sin reventar la app).
        """
        user_text = (user_text or "").strip()
        if not user_text:
            return "Dime qué quieres que haga."

        # Guardamos el mensaje del usuario en memoria de sesión
        self.state.add_user(user_text)

        # Validación: API key
        if not self.config.api_key:
            msg = (
                "Falta OPENAI_API_KEY en tu .env.\n"
                "Pon tu clave en `.env` y reinicia."
            )
            self.state.add_assistant(msg)
            return msg

        messages = self.build_messages(user_text)

        try:
            # Llamada al modelo.
            # OJO: la forma exacta del endpoint puede variar por modelo.
            # Con el SDK moderno, lo normal es usar `responses.create`.
            # Si por versión de SDK tu instalación no soporta `responses`,
            # lo adaptamos en 1 minuto (pero probamos así primero).
            resp = self.client.responses.create(
                model=self.config.model,
                input=messages,
            )

            # Extraemos texto.
            # El objeto response trae output_text como atajo en muchos casos.
            text = getattr(resp, "output_text", None)
            if not text:
                # Fallback: intentamos reconstruir desde output
                # (esto es defensivo por cambios de formato)
                text = self._extract_text_fallback(resp)

            text = (text or "").strip() or "No he podido generar respuesta."
            self.state.add_assistant(text)
            return text

        except Exception as e:
            # No tumbamos la app; devolvemos un mensaje útil.
            err = f"Error llamando al modelo: {type(e).__name__}: {e}"
            if self.config.debug:
                # En debug devolvemos el error completo tal cual.
                self.state.add_assistant(err)
                return err
            # En no-debug, lo suavizamos un poco.
            safe_err = "Error llamando al modelo. Revisa tu API key/modelo o conexión."
            self.state.add_assistant(safe_err)
            return safe_err

    def _extract_text_fallback(self, resp: Any) -> str:
        """
        Fallback defensivo para extraer texto si `output_text` no existe.
        Evita que el proyecto se rompa si cambia el formato del SDK.
        """
        try:
            # Estructura típica: resp.output -> items -> content
            out = getattr(resp, "output", None)
            if not out:
                return ""
            chunks: List[str] = []
            for item in out:
                content = getattr(item, "content", None)
                if not content:
                    continue
                for c in content:
                    # Muchas veces hay {type:'output_text', text:'...'}
                    text = getattr(c, "text", None)
                    if text:
                        chunks.append(text)
            return "\n".join(chunks)
        except Exception:
            return ""


# ---------------------------
# Helper para construir AgentRunner desde Settings
# ---------------------------

def runner_from_settings(settings: Any) -> AgentRunner:
    """
    Construye un AgentRunner usando tu Settings (config.py).

    Esto evita que UI/CLI tenga que conocer detalles del SDK.
    """
    cfg = AgentConfig(
        api_key=getattr(settings, "openai_api_key", ""),
        model=getattr(settings, "openai_model", "gpt-5.2-codex"),
        org=getattr(settings, "openai_org", ""),
        project=getattr(settings, "openai_project", ""),
        debug=bool(getattr(settings, "debug", False)),
    )
    return AgentRunner(cfg)