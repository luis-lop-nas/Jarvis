"""
tool_agent.py

Agente con Claude Sonnet 4.6 como cerebro principal.
- Claude maneja conversación + tool use nativo (sin Ollama)
- Fallback a Groq si Claude no está configurado
- Fallback a Ollama si ninguno está disponible
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from jarvis.agent.prompts import SYSTEM_PROMPT
from jarvis.agent.runner import AgentConfig, AgentState
from jarvis.tools.registry import ToolRegistry, build_default_registry


Message = Dict[str, Any]


@dataclass
class ToolAgentConfig(AgentConfig):
    max_tool_loops: int = 8
    # Claude (principal)
    use_claude: bool = False
    claude_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"
    # Groq (fallback conversación)
    use_groq: bool = False
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    # Ollama (último fallback)
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    # Memoria
    session_id: Optional[str] = None
    enable_memory: bool = True


class ToolAgent:
    def __init__(
        self,
        config: ToolAgentConfig,
        registry: Optional[ToolRegistry] = None,
        state: Optional[AgentState] = None,
        memory_store: Optional[Any] = None,
    ):
        self.config = config
        self.registry = registry or build_default_registry()
        self.state = state or AgentState()
        self.memory_store = memory_store

        if self.memory_store and self.config.enable_memory and not self.config.session_id:
            self.config.session_id = self.memory_store.create_session()
            if self.config.debug:
                print(f"📝 Nueva sesión: {self.config.session_id[:8]}...")

        # Inicializar Claude
        self.claude_client = None
        if self.config.use_claude and self.config.claude_api_key:
            try:
                from anthropic import Anthropic
                self.claude_client = Anthropic(api_key=self.config.claude_api_key)
                print(f"✅ Claude {self.config.claude_model} activado (conversación + tools)")
                if self.memory_store:
                    print("✅ Memoria persistente activada")
            except ImportError:
                print("⚠️ 'anthropic' no instalado. pip install anthropic")

        # Inicializar Groq (fallback o STT)
        self.groq_client = None
        if self.config.use_groq and self.config.groq_api_key:
            try:
                from groq import Groq
                self.groq_client = Groq(api_key=self.config.groq_api_key)
                if not self.claude_client:
                    print("✅ Groq activado como LLM principal")
            except ImportError:
                print("⚠️ Librería 'groq' no instalada.")

    # ------------------------------------------------------------------
    # Memoria
    # ------------------------------------------------------------------

    def _save_message(self, role: str, content: str) -> None:
        if self.memory_store and self.config.enable_memory and self.config.session_id:
            try:
                self.memory_store.add_message(
                    session_id=self.config.session_id,
                    role=role,
                    content=content,
                )
            except Exception as e:
                if self.config.debug:
                    print(f"⚠️ Error guardando mensaje: {e}")

    def _save_tool_event(self, tool_name: str, tool_args: Dict, tool_result: Dict) -> None:
        if self.memory_store and self.config.enable_memory and self.config.session_id:
            try:
                self.memory_store.add_tool_event(
                    session_id=self.config.session_id,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_result=tool_result,
                )
            except Exception as e:
                if self.config.debug:
                    print(f"⚠️ Error guardando tool event: {e}")

    # ------------------------------------------------------------------
    # Schema de herramientas
    # ------------------------------------------------------------------

    def _tools_for_claude(self) -> List[Dict[str, Any]]:
        """Schema de tools en formato Anthropic."""
        tools: List[Dict[str, Any]] = []

        for name, spec in self.registry.list().items():
            properties: Dict[str, Any] = {}
            required: List[str] = []

            for field_name, desc in (spec.schema or {}).items():
                desc_str = str(desc)
                ftype = "string"
                if "int" in desc_str.lower():
                    ftype = "integer"
                elif "bool" in desc_str.lower():
                    ftype = "boolean"

                properties[field_name] = {
                    "type": ftype,
                    "description": desc_str,
                }

                if "obligatorio" in desc_str.lower():
                    required.append(field_name)

            input_schema: Dict[str, Any] = {
                "type": "object",
                "properties": properties,
            }
            if required:
                input_schema["required"] = required

            tools.append({
                "name": spec.name,
                "description": spec.description,
                "input_schema": input_schema,
            })

        return tools

    def _tools_for_ollama(self) -> List[Dict[str, Any]]:
        """Schema de tools en formato Ollama."""
        tools: List[Dict[str, Any]] = []

        for name, spec in self.registry.list().items():
            properties: Dict[str, Any] = {}
            required: List[str] = []

            for field_name, desc in (spec.schema or {}).items():
                desc_str = str(desc)
                ftype = "string"
                if "int" in desc_str.lower():
                    ftype = "integer"
                elif "bool" in desc_str.lower():
                    ftype = "boolean"

                properties[field_name] = {
                    "type": ftype,
                    "description": desc_str,
                }

                if "obligatorio" in desc_str.lower():
                    required.append(field_name)

            parameters = (
                {"type": "object", "properties": properties, "required": required}
                if properties
                else {"type": "object"}
            )

            tools.append({
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": parameters,
                },
            })

        return tools

    # ------------------------------------------------------------------
    # Historial para Claude (solo user/assistant con content string)
    # ------------------------------------------------------------------

    def _build_claude_messages(self) -> List[Message]:
        """Filtra el historial para Claude (solo user/assistant con texto)."""
        messages: List[Message] = []
        for msg in self.state.history:
            role = msg.get("role")
            content = msg.get("content", "")
            if role in ("user", "assistant") and isinstance(content, str) and content.strip():
                messages.append({"role": role, "content": content})
        return messages

    # ------------------------------------------------------------------
    # Motor Claude
    # ------------------------------------------------------------------

    def _run_with_claude(self, user_text: str) -> str:
        """Claude como cerebro único: conversación + tools nativo."""
        messages = self._build_claude_messages()
        tools = self._tools_for_claude()

        for loop_count in range(self.config.max_tool_loops):
            try:
                response = self.claude_client.messages.create(
                    model=self.config.claude_model,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    tools=tools,
                    messages=messages,
                )
            except Exception as e:
                err = f"Error Claude API: {e}"
                if self.config.debug:
                    print(f"⚠️ {err}")
                # Intentar fallback a Groq
                if self.groq_client:
                    return self._run_with_groq_simple(user_text)
                self.state.add_assistant(err)
                self._save_message("assistant", err)
                return err

            stop_reason = response.stop_reason

            # Respuesta final (sin tool use)
            if stop_reason == "end_turn":
                text = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        text += block.text
                text = text.strip() or "No generé respuesta."
                self.state.add_assistant(text)
                self._save_message("assistant", text)
                return text

            # Claude quiere usar herramientas
            if stop_reason == "tool_use":
                # Añadir respuesta de Claude al historial
                messages.append({"role": "assistant", "content": response.content})

                # Ejecutar todas las herramientas
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        tool_name = block.name
                        tool_args = block.input

                        if self.config.debug:
                            print(f"🔧 Claude usa: {tool_name}({json.dumps(tool_args, ensure_ascii=False)[:80]})")

                        tool_out = self.registry.call(tool_name, tool_args)
                        self._save_tool_event(tool_name, tool_args, tool_out)

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(tool_out, ensure_ascii=False),
                        })

                # Devolver resultados a Claude
                messages.append({"role": "user", "content": tool_results})
                continue

            # stop_reason inesperado → extraer texto si lo hay
            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text += block.text
            text = text.strip() or "Respuesta inesperada."
            self.state.add_assistant(text)
            self._save_message("assistant", text)
            return text

        msg = "Límite de iteraciones de herramientas alcanzado."
        self.state.add_assistant(msg)
        self._save_message("assistant", msg)
        return msg

    # ------------------------------------------------------------------
    # Motor Groq (fallback)
    # ------------------------------------------------------------------

    def _run_with_groq_simple(self, user_text: str) -> str:
        """Groq para conversación (fallback de Claude)."""
        messages: List[Message] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for msg in self.state.history:
            role = msg.get("role")
            content = msg.get("content", "")
            if role in ("user", "assistant") and isinstance(content, str):
                messages.append({"role": role, "content": content})

        try:
            response = self.groq_client.chat.completions.create(
                model=self.config.groq_model,
                messages=messages,
                max_tokens=2000,
                temperature=0.7,
            )
            text = (response.choices[0].message.content or "").strip() or "No generé respuesta."
            self.state.add_assistant(text)
            self._save_message("assistant", text)
            return text
        except Exception as e:
            err = f"Error Groq: {e}"
            self.state.add_assistant(err)
            self._save_message("assistant", err)
            return err

    # ------------------------------------------------------------------
    # Motor Ollama (último fallback)
    # ------------------------------------------------------------------

    def _run_with_ollama(self, user_text: str, use_tools: bool = True) -> str:
        """Ollama local — solo usado si Claude y Groq no están disponibles."""
        messages: List[Message] = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(self.state.history)

        if not use_tools:
            try:
                response = requests.post(
                    f"{self.config.ollama_url}/api/chat",
                    json={"model": self.config.ollama_model, "messages": messages, "stream": False},
                    timeout=120,
                )
                response.raise_for_status()
                content = response.json().get("message", {}).get("content", "").strip()
                text = content or "No generé respuesta."
                self.state.add_assistant(text)
                self._save_message("assistant", text)
                return text
            except Exception as e:
                err = f"Error Ollama: {e}"
                self.state.add_assistant(err)
                self._save_message("assistant", err)
                return err

        tools = self._tools_for_ollama()

        for _ in range(self.config.max_tool_loops):
            try:
                response = requests.post(
                    f"{self.config.ollama_url}/api/chat",
                    json={"model": self.config.ollama_model, "messages": messages, "tools": tools, "stream": False},
                    timeout=120,
                )
                response.raise_for_status()
                data = response.json()
            except Exception as e:
                err = f"Error Ollama: {e}"
                self.state.add_assistant(err)
                self._save_message("assistant", err)
                return err

            msg = data.get("message", {})
            content = msg.get("content", "").strip()
            tool_calls = msg.get("tool_calls", [])

            if not tool_calls:
                text = content or "No generé respuesta."
                self.state.add_assistant(text)
                self._save_message("assistant", text)
                return text

            messages.append({"role": "assistant", "content": content or "", "tool_calls": tool_calls})

            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                tool_args_raw = func.get("arguments", {})
                if isinstance(tool_args_raw, str):
                    try:
                        tool_args = json.loads(tool_args_raw)
                    except Exception:
                        tool_args = {"_raw": tool_args_raw}
                else:
                    tool_args = tool_args_raw

                tool_out = self.registry.call(tool_name, tool_args)
                self._save_tool_event(tool_name, tool_args, tool_out)
                messages.append({"role": "tool", "content": json.dumps(tool_out, ensure_ascii=False)})

        msg = "Límite de tool loops alcanzado."
        self.state.add_assistant(msg)
        self._save_message("assistant", msg)
        return msg

    # ------------------------------------------------------------------
    # Punto de entrada principal
    # ------------------------------------------------------------------

    def run(self, user_text: str) -> str:
        """Ejecuta petición. Prioridad: Claude > Groq > Ollama."""
        user_text = (user_text or "").strip()
        if not user_text:
            return "Dime qué quieres que haga."

        self.state.add_user(user_text)
        self._save_message("user", user_text)

        # Claude: maneja TODO (conversación + tools) de forma nativa
        if self.claude_client and self.config.use_claude:
            return self._run_with_claude(user_text)

        # Groq: solo conversación (sin tools)
        if self.groq_client and self.config.use_groq:
            return self._run_with_groq_simple(user_text)

        # Ollama: fallback local
        return self._run_with_ollama(user_text, use_tools=True)


def tool_agent_from_settings(
    settings: Any,
    registry: Optional[ToolRegistry] = None,
    memory_store: Optional[Any] = None,
) -> ToolAgent:
    """Construye ToolAgent desde Settings."""
    cfg = ToolAgentConfig(
        # Claude
        use_claude=bool(getattr(settings, "use_claude", False)),
        claude_api_key=getattr(settings, "anthropic_api_key", ""),
        claude_model=getattr(settings, "anthropic_model", "claude-sonnet-4-6"),
        # Groq
        use_groq=bool(getattr(settings, "use_groq", False)),
        groq_api_key=getattr(settings, "groq_api_key", ""),
        groq_model=getattr(settings, "groq_model", "llama-3.3-70b-versatile"),
        # Ollama
        ollama_model=getattr(settings, "ollama_model", "llama3.2:3b"),
        # General
        debug=bool(getattr(settings, "debug", False)),
        max_tool_loops=8,
        enable_memory=True,
    )
    return ToolAgent(cfg, registry=registry, memory_store=memory_store)
