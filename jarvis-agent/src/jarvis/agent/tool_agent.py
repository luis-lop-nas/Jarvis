"""
tool_agent.py

Agente con Claude Sonnet 4.6 como cerebro principal.
- Claude maneja conversación + tool use nativo (sin Ollama)
- Fallback a Groq si Claude no está configurado
- Fallback a Ollama si ninguno está disponible
"""

from __future__ import annotations

import asyncio
import json
import queue as queue_module
import re
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, List, Optional

import requests

from jarvis.agent.intent_tracker import IntentTracker
from jarvis.agent.prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_GROQ
from jarvis.agent.runner import AgentConfig
from jarvis.agent.state import AgentState, truncate_history
from jarvis.tools.registry import ToolRegistry, build_default_registry


Message = Dict[str, Any]


@dataclass
class ToolAgentConfig(AgentConfig):
    max_tool_loops: int = 8
    # Claude (principal)
    use_claude: bool = False
    claude_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"
    # Gemini
    use_gemini: bool = False
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
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

        # Inicializar Gemini
        self.gemini_client = None
        if self.config.use_gemini and self.config.gemini_api_key:
            try:
                from google import genai
                self.gemini_client = genai.Client(api_key=self.config.gemini_api_key)
                if not self.claude_client:
                    print(f"✅ Gemini {self.config.gemini_model} activado")
            except ImportError:
                print("⚠️ 'google-genai' no instalado. pip install google-genai")

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

        # Multi-step intent tracker (shared across all backends)
        self.intent_tracker = IntentTracker()

        # Pre-computar schemas de tools (inmutables durante la vida del agente)
        self._cached_claude_tools = self._tools_for_claude()
        self._cached_ollama_tools = self._tools_for_ollama()
        self._cached_gemini_tools = self._tools_for_gemini() if self.gemini_client else []

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

    @staticmethod
    def _field_type(desc_str: str) -> str:
        """Detecta el tipo JSON de un campo a partir de su descripción."""
        import re
        dl = desc_str.lower()
        # Booleano
        if "bool" in dl:
            return "boolean"
        # Entero — búsqueda por palabra completa para evitar falsos positivos
        # (e.g., "int" dentro de "inteligente")
        _INT_RE = re.compile(
            r"\b(int(eger)?|n[úu]mero|segundos|timeout|top_n|l[íi]mit|"
            r"cantidad|count|d[íi]as?|days?)\b"
        )
        if _INT_RE.search(dl):
            return "integer"
        return "string"

    def _tools_for_ollama(self) -> List[Dict[str, Any]]:
        """Schema de tools en formato OpenAI/Groq/Ollama."""
        tools: List[Dict[str, Any]] = []

        for name, spec in self.registry.list().items():
            properties: Dict[str, Any] = {}
            required: List[str] = []

            for field_name, desc in (spec.schema or {}).items():
                desc_str = str(desc)
                properties[field_name] = {
                    "type": self._field_type(desc_str),
                    "description": desc_str,
                }
                if "obligatorio" in desc_str.lower():
                    required.append(field_name)

            # No incluir "required" vacío — algunos modelos lo usan mal
            params: Dict[str, Any] = {"type": "object"}
            if properties:
                params["properties"] = properties
            if required:
                params["required"] = required

            tools.append({
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": params,
                },
            })

        return tools

    # ------------------------------------------------------------------
    # Historial para Claude (solo user/assistant con content string)
    # ------------------------------------------------------------------

    def _build_claude_messages(self) -> List[Message]:
        """Filtra el historial para Claude (solo user/assistant con texto, truncado)."""
        history = truncate_history(self.state.history, max_messages=20)
        messages: List[Message] = []
        for msg in history:
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
        tools = self._cached_claude_tools

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

                        # Check for missing required params before executing
                        question = self.intent_tracker.check_tool_call(
                            tool_name, tool_args, self.registry
                        )
                        if question:
                            # Params missing — send a synthetic tool_result so Claude
                            # stays in a valid conversation state and asks the user.
                            if self.config.debug:
                                print(f"⏳ Intent pendiente ({tool_name}): {question}")
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps({
                                    "ok": False,
                                    "error": (
                                        f"Parámetros obligatorios faltantes. "
                                        f"Pregunta al usuario: {question}"
                                    ),
                                }, ensure_ascii=False),
                            })
                            continue  # don't execute the tool

                        tool_out = self.registry.call(tool_name, tool_args)
                        self.intent_tracker.on_tool_executed(tool_name)
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
    # Motor Gemini
    # ------------------------------------------------------------------

    def _tools_for_gemini(self) -> List[Any]:
        """Schema de tools en formato Gemini."""
        from google.genai import types

        declarations = []
        for name, spec in self.registry.list().items():
            properties: Dict[str, Any] = {}
            required: List[str] = []

            for field_name, desc in (spec.schema or {}).items():
                desc_str = str(desc)
                if "int" in desc_str.lower():
                    ftype = "INTEGER"
                elif "bool" in desc_str.lower():
                    ftype = "BOOLEAN"
                else:
                    ftype = "STRING"

                properties[field_name] = types.Schema(
                    type=ftype,
                    description=desc_str,
                )
                if "obligatorio" in desc_str.lower():
                    required.append(field_name)

            params = types.Schema(
                type="OBJECT",
                properties=properties,
                required=required if required else [],
            )
            declarations.append(
                types.FunctionDeclaration(
                    name=spec.name,
                    description=spec.description,
                    parameters=params,
                )
            )

        return [types.Tool(function_declarations=declarations)] if declarations else []

    def _run_with_gemini(self, user_text: str) -> str:
        """Gemini como cerebro: conversación + tools nativo."""
        from google.genai import types

        # Construir historial en formato Gemini (truncado)
        contents: List[Any] = []
        for msg in truncate_history(self.state.history, max_messages=20):
            role = msg.get("role")
            content = msg.get("content", "")
            if role == "user" and isinstance(content, str) and content.strip():
                contents.append(types.Content(role="user", parts=[types.Part.from_text(content)]))
            elif role == "assistant" and isinstance(content, str) and content.strip():
                contents.append(types.Content(role="model", parts=[types.Part.from_text(content)]))

        tools = self._cached_gemini_tools

        for _ in range(self.config.max_tool_loops):
            try:
                response = self.gemini_client.models.generate_content(
                    model=self.config.gemini_model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        tools=tools if tools else None,
                    ),
                )
            except Exception as e:
                err = f"Error Gemini API: {e}"
                if self.config.debug:
                    print(f"⚠️ {err}")
                if self.groq_client:
                    return self._run_with_groq_simple(user_text)
                self.state.add_assistant(err)
                self._save_message("assistant", err)
                return err

            if not response.candidates:
                err = "Gemini no devolvió candidatos (posible filtro de contenido)."
                if self.config.debug:
                    print(f"⚠️ {err}")
                self.state.add_assistant(err)
                self._save_message("assistant", err)
                return err

            candidate = response.candidates[0]
            parts = candidate.content.parts

            # Buscar tool calls
            tool_calls = [p for p in parts if p.function_call is not None]

            if not tool_calls:
                # Respuesta final
                text = "".join(p.text for p in parts if hasattr(p, "text") and p.text).strip()
                text = text or "No generé respuesta."
                self.state.add_assistant(text)
                self._save_message("assistant", text)
                return text

            # Añadir respuesta del modelo al historial
            contents.append(types.Content(role="model", parts=parts))

            # Ejecutar tools y devolver resultados
            result_parts = []
            for part in tool_calls:
                fc = part.function_call
                tool_args = dict(fc.args) if fc.args else {}

                # Check for missing required params before executing
                question = self.intent_tracker.check_tool_call(
                    fc.name, tool_args, self.registry
                )
                if question:
                    if self.config.debug:
                        print(f"⏳ Intent pendiente ({fc.name}): {question}")
                    self.state.add_assistant(question)
                    self._save_message("assistant", question)
                    return question

                if self.config.debug:
                    print(f"🔧 Gemini usa: {fc.name}({json.dumps(tool_args, ensure_ascii=False)[:80]})")

                tool_out = self.registry.call(fc.name, tool_args)
                self.intent_tracker.on_tool_executed(fc.name)
                self._save_tool_event(fc.name, tool_args, tool_out)

                result_parts.append(
                    types.Part.from_function_response(
                        name=fc.name,
                        response={"result": json.dumps(tool_out, ensure_ascii=False)},
                    )
                )

            contents.append(types.Content(role="user", parts=result_parts))

        msg = "Límite de iteraciones de herramientas alcanzado."
        self.state.add_assistant(msg)
        self._save_message("assistant", msg)
        return msg

    # ------------------------------------------------------------------
    # Motor Groq (fallback)
    # ------------------------------------------------------------------

    def _run_with_groq(self, user_text: str) -> str:
        """Groq con tool calling nativo (mismo formato OpenAI)."""
        # SYSTEM_PROMPT_GROQ: versión compacta sin ejemplos de código Python que
        # confunden al modelo llama sobre el formato de function calling de la API.
        messages: List[Message] = [{"role": "system", "content": SYSTEM_PROMPT_GROQ}]
        for msg in truncate_history(self.state.history, max_messages=20):
            role = msg.get("role")
            content = msg.get("content", "")
            if role in ("user", "assistant") and isinstance(content, str):
                messages.append({"role": role, "content": content})

        tools = self._cached_ollama_tools  # formato OpenAI — idéntico al que usa Groq

        for _ in range(self.config.max_tool_loops):
            try:
                response = self.groq_client.chat.completions.create(
                    model=self.config.groq_model,
                    messages=messages,
                    tools=tools if tools else None,
                    tool_choice="auto" if tools else None,
                    parallel_tool_calls=False,
                    max_tokens=2000,
                    temperature=0.7,
                )
            except Exception as e:
                # Si el modelo genera una tool call malformada, reintentar sin tools
                err_str = str(e)
                if "tool_use_failed" in err_str or "tool call validation failed" in err_str:
                    if self.config.debug:
                        print(f"⚠️ Groq tool_use_failed — reintentando sin tools")
                    return self._run_with_groq_simple(user_text)
                err = f"Error Groq: {e}"
                self.state.add_assistant(err)
                self._save_message("assistant", err)
                return err

            choice = response.choices[0]
            msg_out = choice.message

            # Respuesta final (sin tool calls estructurados)
            if not msg_out.tool_calls:
                text = (msg_out.content or "").strip() or "No generé respuesta."
                # Detectar tool calls en formato texto (<function=...>) que el modelo
                # a veces genera en vez de usar el mecanismo estructurado de la API
                text_calls = self._extract_text_tool_calls(text)
                if text_calls:
                    # Ejecutar las tools y pedir al modelo que reformule con los resultados
                    tool_results_ctx = self._run_text_tool_calls(text_calls)
                    messages.append({"role": "assistant", "content": text})
                    messages.append({
                        "role": "user",
                        "content": (
                            f"Resultados de las herramientas:\n{tool_results_ctx}\n\n"
                            "Ahora responde al usuario usando esos resultados. "
                            "No incluyas etiquetas <function=...> en tu respuesta."
                        ),
                    })
                    # Nueva llamada para que el modelo formule la respuesta final
                    try:
                        resp2 = self.groq_client.chat.completions.create(
                            model=self.config.groq_model,
                            messages=messages,
                            max_tokens=2000,
                            temperature=0.7,
                        )
                        text = (resp2.choices[0].message.content or "").strip() or text
                    except Exception:
                        pass  # usar texto original si falla
                self.state.add_assistant(text)
                self._save_message("assistant", text)
                return text

            # Check for missing required params BEFORE adding tool_calls to messages.
            # For Groq, returning early avoids leaving an orphaned tool_call in history.
            first_question: Optional[str] = None
            for tc in msg_out.tool_calls:
                _tname = tc.function.name
                try:
                    _targs = json.loads(tc.function.arguments or "{}")
                except Exception:
                    _targs = {}
                _q = self.intent_tracker.check_tool_call(_tname, _targs, self.registry)
                if _q:
                    first_question = _q
                    if self.config.debug:
                        print(f"⏳ Intent pendiente ({_tname}): {_q}")
                    break

            if first_question:
                self.state.add_assistant(first_question)
                self._save_message("assistant", first_question)
                return first_question

            # All params present — añadir respuesta al historial y ejecutar
            messages.append({
                "role": "assistant",
                "content": msg_out.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg_out.tool_calls
                ],
            })

            # Ejecutar cada tool y devolver resultados
            for tc in msg_out.tool_calls:
                tool_name = tc.function.name
                try:
                    tool_args = json.loads(tc.function.arguments)
                except Exception:
                    tool_args = {}

                if self.config.debug:
                    print(f"🔧 Groq usa: {tool_name}({json.dumps(tool_args, ensure_ascii=False)[:80]})")

                tool_out = self.registry.call(tool_name, tool_args)
                self.intent_tracker.on_tool_executed(tool_name)
                self._save_tool_event(tool_name, tool_args, tool_out)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(tool_out, ensure_ascii=False),
                })

        msg = "Límite de iteraciones de herramientas alcanzado."
        self.state.add_assistant(msg)
        self._save_message("assistant", msg)
        return msg

    def _run_with_groq_simple(self, user_text: str) -> str:
        """Groq sin tools — solo usado como fallback de Claude/Gemini en caso de error."""
        messages: List[Message] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for msg in truncate_history(self.state.history, max_messages=20):
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

        tools = self._cached_ollama_tools

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

            # Check for missing required params BEFORE adding tool_calls to messages
            first_question_ollama: Optional[str] = None
            for tc in tool_calls:
                _func = tc.get("function", {})
                _tname = _func.get("name", "")
                _targs_raw = _func.get("arguments", {})
                if isinstance(_targs_raw, str):
                    try:
                        _targs = json.loads(_targs_raw)
                    except Exception:
                        _targs = {}
                else:
                    _targs = _targs_raw
                _q = self.intent_tracker.check_tool_call(_tname, _targs, self.registry)
                if _q:
                    first_question_ollama = _q
                    if self.config.debug:
                        print(f"⏳ Intent pendiente ({_tname}): {_q}")
                    break

            if first_question_ollama:
                self.state.add_assistant(first_question_ollama)
                self._save_message("assistant", first_question_ollama)
                return first_question_ollama

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
                self.intent_tracker.on_tool_executed(tool_name)
                self._save_tool_event(tool_name, tool_args, tool_out)
                messages.append({"role": "tool", "content": json.dumps(tool_out, ensure_ascii=False)})

        msg = "Límite de tool loops alcanzado."
        self.state.add_assistant(msg)
        self._save_message("assistant", msg)
        return msg

    # ------------------------------------------------------------------
    # Punto de entrada principal
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Parser de text-format tool calls (Groq/llama fallback)
    # ------------------------------------------------------------------

    _RE_TEXT_FUNC = re.compile(
        r'<function=(\w+)>(.*?)</function>', re.DOTALL
    )

    def _extract_text_tool_calls(self, text: str) -> List[Dict[str, Any]]:
        """
        Detecta tool calls escritas en texto por el modelo
        (<function=name>{...}</function>) y devuelve lista de {name, args}.
        """
        results = []
        for m in self._RE_TEXT_FUNC.finditer(text):
            name = m.group(1)
            raw = m.group(2).strip()
            try:
                args = json.loads(raw)
            except Exception:
                args = {}
            results.append({"name": name, "args": args})
        return results

    def _run_text_tool_calls(self, calls: List[Dict[str, Any]]) -> str:
        """Ejecuta una lista de text-format tool calls y devuelve resultados como texto."""
        parts: List[str] = []
        for call in calls:
            name = call["name"]
            args = call["args"]
            if self.config.debug:
                print(f"🔧 Groq text-call: {name}({json.dumps(args, ensure_ascii=False)[:80]})")
            try:
                out = self.registry.call(name, args)
                self._save_tool_event(name, args, out)
                parts.append(f"[{name}] {json.dumps(out, ensure_ascii=False)}")
            except Exception as e:
                parts.append(f"[{name}] Error: {e}")
        return "\n".join(parts)

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

        # Gemini: conversación + tools
        if self.gemini_client and self.config.use_gemini:
            return self._run_with_gemini(user_text)

        # Groq: conversación + tools nativo
        if self.groq_client and self.config.use_groq:
            return self._run_with_groq(user_text)

        # Ollama: fallback local
        return self._run_with_ollama(user_text, use_tools=True)

    # ------------------------------------------------------------------
    # Streaming (Groq)
    # ------------------------------------------------------------------

    async def run_stream(self, user_text: str) -> AsyncGenerator[str, None]:
        """
        Versión streaming de run() para Groq.
        Yield-ea chunks de texto según llegan del LLM.
        Si no hay Groq disponible, hace run() normal y yield-ea todo de golpe.
        """
        user_text = (user_text or "").strip()
        if not user_text:
            yield "Dime qué quieres que haga."
            return

        self.state.add_user(user_text)
        self._save_message("user", user_text)

        # Claude: no streaming en este modo — fallback síncrono
        if self.claude_client and self.config.use_claude:
            # _run_with_claude ya maneja estado y memoria
            text = await asyncio.to_thread(self._run_with_claude, user_text)
            yield text
            return

        # Groq streaming nativo
        if self.groq_client and self.config.use_groq:
            messages: List[Message] = [{"role": "system", "content": SYSTEM_PROMPT}]
            for msg in truncate_history(self.state.history, max_messages=20):
                role = msg.get("role")
                content = msg.get("content", "")
                if role in ("user", "assistant") and isinstance(content, str):
                    messages.append({"role": role, "content": content})

            q: queue_module.Queue = queue_module.Queue()

            def _stream_worker() -> None:
                try:
                    response = self.groq_client.chat.completions.create(
                        model=self.config.groq_model,
                        messages=messages,
                        max_tokens=2000,
                        temperature=0.7,
                        stream=True,
                    )
                    for chunk in response:
                        delta = chunk.choices[0].delta.content
                        if delta:
                            q.put(("chunk", delta))
                    q.put(("done", None))
                except Exception as e:
                    q.put(("error", str(e)))

            loop = asyncio.get_event_loop()
            future = loop.run_in_executor(None, _stream_worker)

            full_text = ""
            while True:
                try:
                    kind, data = q.get_nowait()
                except queue_module.Empty:
                    await asyncio.sleep(0.01)
                    continue

                if kind == "done":
                    break
                if kind == "error":
                    yield f"Error Groq: {data}"
                    return
                full_text += data
                yield data

            await future  # asegurar que el thread terminó limpiamente

            full_text = full_text.strip() or "No generé respuesta."
            self.state.add_assistant(full_text)
            self._save_message("assistant", full_text)
            return

        # Fallback: Gemini / Ollama (no streaming)
        # Nota: ya añadimos user al state arriba, no llamar run() completo
        if self.gemini_client and self.config.use_gemini:
            text = await asyncio.to_thread(self._run_with_gemini, user_text)
        else:
            text = await asyncio.to_thread(self._run_with_ollama, user_text, True)
        yield text


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
        # Gemini
        use_gemini=bool(getattr(settings, "use_gemini", False)),
        gemini_api_key=getattr(settings, "gemini_api_key", ""),
        gemini_model=getattr(settings, "gemini_model", "gemini-2.0-flash"),
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
