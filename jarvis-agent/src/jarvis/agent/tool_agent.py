"""
tool_agent.py

Agente híbrido: Groq para conversación, Ollama para herramientas.
Decide automáticamente cuál usar según el contexto.
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
    max_tool_loops: int = 6
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    use_groq: bool = False
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"


class ToolAgent:
    def __init__(
        self,
        config: ToolAgentConfig,
        registry: Optional[ToolRegistry] = None,
        state: Optional[AgentState] = None,
    ):
        self.config = config
        self.registry = registry or build_default_registry()
        self.state = state or AgentState()
        
        self.groq_client = None
        if self.config.use_groq and self.config.groq_api_key:
            try:
                from groq import Groq
                self.groq_client = Groq(api_key=self.config.groq_api_key)
                if self.config.debug:
                    print("✅ Modo Híbrido: Groq (conversación) + Ollama (herramientas)")
            except ImportError:
                print("⚠️ Librería 'groq' no instalada. Usando solo Ollama.")
                self.groq_client = None

    def _needs_tools(self, user_text: str) -> bool:
        """
        Detecta si la pregunta necesita herramientas (acción) o solo conversación.
        
        Keywords que indican necesidad de tools:
        - Acciones: ejecuta, corre, abre, crea, lista, busca (web), lee (archivo)
        - Comandos: shell, terminal, código
        - Archivos: archivo, carpeta, directorio
        """
        text_lower = user_text.lower()
        
        # Patterns que indican necesidad de herramientas
        tool_patterns = [
            # Comandos/Shell
            r'\b(ejecuta|corre|run|shell|terminal|comando)\b',
            r'\b(lista|ls|dir|muestra.*archivo|muestra.*carpeta)\b',
            r'\b(git|npm|pip|brew|docker)\b',
            
            # Archivos
            r'\b(crea.*archivo|escribe.*archivo|lee.*archivo)\b',
            r'\b(abre.*carpeta|abre.*directorio)\b',
            r'\b(borra|elimina|delete).*\b(archivo|carpeta)\b',
            
            # Apps
            r'\b(abre|open|lanza|launch)\s+(spotify|chrome|safari|vscode|visual studio|finder)\b',
            
            # Código
            r'\b(ejecuta.*código|corre.*script|run.*code)\b',
            r'\b(python|node|javascript).*script\b',
            
            # Web search (necesita tool)
            r'\b(busca.*en.*web|busca.*internet|search.*web)\b',
            r'\b(encuentra.*información.*sobre|investiga.*sobre)\b',
        ]
        
        for pattern in tool_patterns:
            if re.search(pattern, text_lower):
                if self.config.debug:
                    print(f"🔧 Detectado patrón de herramienta: '{pattern}'")
                    print("→ Usando Ollama (local) para ejecutar tools")
                return True
        
        # Conversación pura
        if self.config.debug:
            print("💭 Conversación pura detectada")
            print("→ Usando Groq (rápido e inteligente)")
        return False

    def _tools_for_ollama(self) -> List[Dict[str, Any]]:
        """Convierte tools a formato Ollama."""
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

            parameters = {
                "type": "object",
                "properties": properties,
                "required": required,
            } if properties else {"type": "object"}

            tools.append({
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": parameters,
                },
            })

        return tools

    def build_messages(self, user_text: str) -> List[Message]:
        messages: List[Message] = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(self.state.history)
        messages.append({"role": "user", "content": user_text})
        return messages

    def _run_with_groq(self, user_text: str) -> str:
        """Ejecuta conversación pura con Groq (rápido e inteligente)."""
        messages = self.build_messages(user_text)

        try:
            response = self.groq_client.chat.completions.create(
                model=self.config.groq_model,
                messages=messages,
                max_tokens=2000,
                temperature=0.7,
            )
            
            choice = response.choices[0]
            msg = choice.message
            final_text = (msg.content or "").strip() or "No generé respuesta."
            self.state.add_assistant(final_text)
            return final_text
            
        except Exception as e:
            if self.config.debug:
                err = f"Error Groq: {type(e).__name__}: {e}"
                print(f"⚠️ {err}")
                print("→ Fallback a Ollama local")
            # Fallback a Ollama si Groq falla
            return self._run_with_ollama(user_text, use_tools=False)

    def _run_with_ollama(self, user_text: str, use_tools: bool = True) -> str:
        """Ejecuta con Ollama local (con o sin tools)."""
        messages = self.build_messages(user_text)
        
        if not use_tools:
            # Ollama sin tools (fallback de Groq)
            try:
                response = requests.post(
                    f"{self.config.ollama_url}/api/chat",
                    json={
                        "model": self.config.ollama_model,
                        "messages": messages,
                        "stream": False,
                    },
                    timeout=120,
                )
                response.raise_for_status()
                data = response.json()
                msg = data.get("message", {})
                content = msg.get("content", "").strip()
                final_text = content or "No generé respuesta."
                self.state.add_assistant(final_text)
                return final_text
            except Exception as e:
                err = f"Error Ollama: {type(e).__name__}: {e}"
                self.state.add_assistant(err)
                return err
        
        # Ollama CON tools
        tools = self._tools_for_ollama()

        for loop_count in range(self.config.max_tool_loops):
            try:
                response = requests.post(
                    f"{self.config.ollama_url}/api/chat",
                    json={
                        "model": self.config.ollama_model,
                        "messages": messages,
                        "tools": tools,
                        "stream": False,
                    },
                    timeout=120,
                )
                response.raise_for_status()
                data = response.json()
                
            except Exception as e:
                if self.config.debug:
                    err = f"Error Ollama: {type(e).__name__}: {e}"
                    self.state.add_assistant(err)
                    return err
                safe_err = "Error con Ollama. ¿Está corriendo?"
                self.state.add_assistant(safe_err)
                return safe_err

            msg = data.get("message", {})
            content = msg.get("content", "").strip()
            tool_calls = msg.get("tool_calls", [])

            if not tool_calls:
                final_text = content or "No generé respuesta."
                self.state.add_assistant(final_text)
                return final_text

            messages.append({
                "role": "assistant",
                "content": content or "",
                "tool_calls": tool_calls,
            })

            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                tool_args_raw = func.get("arguments", {})

                if isinstance(tool_args_raw, str):
                    try:
                        tool_args = json.loads(tool_args_raw)
                    except:
                        tool_args = {"_raw": tool_args_raw}
                else:
                    tool_args = tool_args_raw

                if self.config.debug:
                    print(f"🔧 Ejecutando: {tool_name}")

                tool_out = self.registry.call(tool_name, tool_args)

                messages.append({
                    "role": "tool",
                    "content": json.dumps(tool_out, ensure_ascii=False),
                })

        msg = "Límite de tool loops alcanzado."
        self.state.add_assistant(msg)
        return msg

    def run(self, user_text: str) -> str:
        """
        Ejecuta petición usando modo híbrido automático:
        - Groq si es conversación pura (rápido, inteligente)
        - Ollama si necesita herramientas (ejecución local)
        """
        user_text = (user_text or "").strip()
        if not user_text:
            return "Dime qué quieres que haga."

        self.state.add_user(user_text)

        # Decisión automática: ¿necesita tools?
        needs_tools = self._needs_tools(user_text)

        if needs_tools:
            # Necesita herramientas → Ollama local
            return self._run_with_ollama(user_text, use_tools=True)
        else:
            # Conversación pura → Groq (si disponible) o Ollama
            if self.groq_client and self.config.use_groq:
                return self._run_with_groq(user_text)
            else:
                return self._run_with_ollama(user_text, use_tools=False)


def tool_agent_from_settings(settings: Any, registry: Optional[ToolRegistry] = None) -> ToolAgent:
    """Construye ToolAgent desde Settings."""
    cfg = ToolAgentConfig(
        ollama_model=getattr(settings, "ollama_model", "llama3.2:3b"),
        use_groq=getattr(settings, "use_groq", False),
        groq_api_key=getattr(settings, "groq_api_key", ""),
        groq_model=getattr(settings, "groq_model", "llama-3.3-70b-versatile"),
        debug=bool(getattr(settings, "debug", False)),
        max_tool_loops=6,
    )
    return ToolAgent(cfg, registry=registry)
