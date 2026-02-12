"""
tool_agent.py

Agente con herramientas (tool-calling).

Qué hace:
- Expone las tools del ToolRegistry al modelo como "functions"
- Permite que el modelo decida llamar a tools (ej: shell) para realizar acciones reales
- Ejecuta las tools y devuelve el resultado al modelo
- Repite hasta obtener una respuesta final de texto

Diseño:
- "ToolAgent" mantiene memoria corta (historial) para la sesión.
- Usa OpenAI Chat Completions porque el tool calling es muy estable ahí.
- El resultado de tools se devuelve al modelo usando mensajes role="tool".

Más adelante:
- Añadiremos herramientas run_code (Docker), web_search, open_app, filesystem...
- Añadiremos memoria persistente (SQLite) y políticas de seguridad (cortafuegos configurable).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from openai import OpenAI

from jarvis.agent.prompts import SYSTEM_PROMPT
from jarvis.agent.runner import AgentConfig, AgentState
from jarvis.tools.registry import ToolRegistry, build_default_registry


Message = Dict[str, Any]


@dataclass
class ToolAgentConfig(AgentConfig):
    """
    Heredamos AgentConfig (api_key, model, org, project, debug).
    max_tool_loops limita cuántas tools puede encadenar en una sola petición
    (evita bucles infinitos).
    """
    max_tool_loops: int = 6


class ToolAgent:
    """
    ToolAgent = modelo + memoria corta + tool registry.

    Flujo:
    1) Construye mensajes (system + historial + user)
    2) Llama al modelo con tools="auto"
    3) Si el modelo pide tool(s), las ejecuta y añade mensajes role="tool"
    4) Repite hasta obtener una respuesta final
    """

    def __init__(
        self,
        config: ToolAgentConfig,
        registry: Optional[ToolRegistry] = None,
        state: Optional[AgentState] = None,
    ):
        self.config = config
        self.registry = registry or build_default_registry()
        self.state = state or AgentState()

        self.client = OpenAI(
            api_key=self.config.api_key,
            organization=self.config.org or None,
            project=self.config.project or None,
        )

    # ---------------------------
    # Tools -> formato OpenAI
    # ---------------------------

    def _tools_for_openai(self) -> List[Dict[str, Any]]:
        """
        Convierte el ToolRegistry a la estructura esperada por OpenAI (tools/functions).

        IMPORTANTE:
        - Aquí usamos un JSON Schema mínimo por tool.
        - De momento lo hacemos sencillo y explícito.
        - Cuando añadamos más tools, ampliaremos los schemas.
        """
        tools: List[Dict[str, Any]] = []

        for name, spec in self.registry.list().items():
            # Por ahora tenemos schemas como dict de strings; construimos un JSON schema básico.
            # Reglas simples:
            # - command es required si existe en schema y contiene "(obligatorio)"
            # - el resto son opcionales con tipos aproximados
            properties: Dict[str, Any] = {}
            required: List[str] = []

            for field_name, desc in (spec.schema or {}).items():
                desc_str = str(desc)
                # Tipo por heurística (muy simple)
                ftype = "string"
                if "int" in desc_str:
                    ftype = "integer"
                elif "bool" in desc_str:
                    ftype = "boolean"
                elif "dict" in desc_str:
                    ftype = "object"

                properties[field_name] = {
                    "type": ftype,
                    "description": desc_str,
                }

                if "obligatorio" in desc_str.lower():
                    required.append(field_name)

            # Si no hay properties, permitimos objeto libre
            parameters: Dict[str, Any]
            if properties:
                parameters = {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": True,
                }
            else:
                parameters = {"type": "object", "additionalProperties": True}

            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": spec.name,
                        "description": spec.description,
                        "parameters": parameters,
                    },
                }
            )

        return tools

    # ---------------------------
    # Construcción de mensajes
    # ---------------------------

    def build_messages(self, user_text: str) -> List[Message]:
        """
        Mensajes para el modelo (system + historial + user).
        """
        messages: List[Message] = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(self.state.history)
        messages.append({"role": "user", "content": user_text})
        return messages

    # ---------------------------
    # Bucle principal
    # ---------------------------

    def run(self, user_text: str) -> str:
        """
        Ejecuta una petición del usuario permitiendo tool calling.

        Devuelve la respuesta final del asistente (texto).
        """
        user_text = (user_text or "").strip()
        if not user_text:
            return "Dime qué quieres que haga."

        # Guardamos el mensaje del usuario
        self.state.add_user(user_text)

        # Validación de API key
        if not self.config.api_key:
            msg = (
                "Falta OPENAI_API_KEY en tu .env.\n"
                "Pon tu clave en `.env` y reinicia."
            )
            self.state.add_assistant(msg)
            return msg

        tools = self._tools_for_openai()
        messages = self.build_messages(user_text)

        # Bucle: el modelo puede pedir varias tools seguidas
        for _ in range(self.config.max_tool_loops):
            try:
                resp = self.client.chat.completions.create(
                    model=self.config.model,
                    messages=messages,      # type: ignore[arg-type]
                    tools=tools,            # tools/functions disponibles
                    tool_choice="auto",     # deja que el modelo decida
                )
            except Exception as e:
                if self.config.debug:
                    err = f"Error llamando al modelo: {type(e).__name__}: {e}"
                    self.state.add_assistant(err)
                    return err
                safe_err = "Error llamando al modelo. Revisa tu API key/modelo o conexión."
                self.state.add_assistant(safe_err)
                return safe_err

            choice = resp.choices[0]
            msg = choice.message

            # 1) Si el modelo devuelve texto final sin tools
            if not getattr(msg, "tool_calls", None):
                final_text = (msg.content or "").strip() or "No he podido generar respuesta."
                self.state.add_assistant(final_text)
                return final_text

            # 2) Si pide tools, primero añadimos el mensaje del assistant con tool_calls
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [tc.model_dump() for tc in msg.tool_calls],  # serializable
                }
            )

            # 3) Ejecutamos cada tool llamada
            for tc in msg.tool_calls:
                tool_name = tc.function.name
                tool_args_raw = tc.function.arguments or "{}"

                # Parse de args
                try:
                    tool_args = json.loads(tool_args_raw)
                    if not isinstance(tool_args, dict):
                        tool_args = {"value": tool_args}
                except Exception:
                    tool_args = {"_raw": tool_args_raw}

                # Ejecutamos via registry
                tool_out = self.registry.call(tool_name, tool_args)

                # Añadimos resultado como role="tool"
                # tool_call_id sirve para enlazar el resultado con la llamada
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(tool_out, ensure_ascii=False),
                    }
                )

        # Si llegamos aquí, el modelo encadenó demasiadas tools
        msg = "He alcanzado el límite de acciones encadenadas en una sola petición."
        self.state.add_assistant(msg)
        return msg


def tool_agent_from_settings(settings: Any, registry: Optional[ToolRegistry] = None) -> ToolAgent:
    """
    Helper para construir ToolAgent desde Settings (config.py).
    """
    cfg = ToolAgentConfig(
        api_key=getattr(settings, "openai_api_key", ""),
        model=getattr(settings, "openai_model", "gpt-5.2-codex"),
        org=getattr(settings, "openai_org", ""),
        project=getattr(settings, "openai_project", ""),
        debug=bool(getattr(settings, "debug", False)),
        max_tool_loops=6,
    )
    return ToolAgent(cfg, registry=registry)