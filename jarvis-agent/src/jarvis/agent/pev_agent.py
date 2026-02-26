"""
pev_agent.py

PEVAgent: Planner → Executor → Verifier pipeline.

Misma API pública que ToolAgent (run, run_stream, intent_tracker).
Daemon y web/server.py no necesitan cambios.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, AsyncGenerator, Dict, List, Optional
from uuid import uuid4

import requests

from jarvis.agent.confirm_policy import is_affirmative, is_negative
from jarvis.agent.dry_run import build_summary, is_sensitive
from jarvis.agent.intent_tracker import IntentTracker
from jarvis.agent.pev_models import Plan, PlanStep, RunState, StepResult
from jarvis.agent.pev_prompts import (
    PLANNER_SYSTEM_PROMPT,
    PLANNER_USER_TEMPLATE,
    SYNTHESIS_SYSTEM_PROMPT,
)
from jarvis.agent.pev_state import RunStateStore
from jarvis.agent.tool_agent import ToolAgent, ToolAgentConfig
from jarvis.agent.verifier import VerifyContext, verify
from jarvis.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# Schema simplificado del plan para inyectar en el prompt del planner
_PLAN_SCHEMA = """{
  "goal": "string — objetivo general",
  "steps": [
    {
      "id": "s1",
      "tool_name": "nombre_tool o null si requires_user_input=true",
      "action": "descripción humana del paso",
      "args": {"param": "valor"},
      "requires_user_input": false,
      "depends_on": [],
      "success_criteria": "qué debe ser verdad para que el paso sea exitoso",
      "sensitive": false
    }
  ]
}"""


class PEVAgent:
    """
    Agente PEV (Planner → Executor → Verifier).

    API pública idéntica a ToolAgent: run(), run_stream(), intent_tracker.
    """

    def __init__(
        self,
        config: ToolAgentConfig,
        registry: Optional[ToolRegistry] = None,
        memory_store: Optional[Any] = None,
        confirm_context: Optional[Dict] = None,
    ) -> None:
        self._tool_agent = ToolAgent(
            config,
            registry=registry,
            memory_store=memory_store,
            confirm_context=confirm_context,
        )
        self._state_store = RunStateStore(ttl_seconds=config.pev_state_ttl_seconds)
        self._config = config
        self._max_steps = config.pev_max_steps
        self._retry_max = config.pev_retry_max

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    @property
    def intent_tracker(self) -> IntentTracker:
        return self._tool_agent.intent_tracker

    @property
    def _session_key(self) -> str:
        return self._config.session_id or "default"

    def run(self, user_text: str) -> str:
        user_text = (user_text or "").strip()
        if not user_text:
            return "Dime qué quieres que haga."

        # 1. Cancelación explícita → delegar a ToolAgent
        if self._tool_agent.intent_tracker.check_user_cancel(user_text):
            self._state_store.clear(self._session_key)
            return "Cancelado."

        # 2. RunState pendiente → retomar
        state = self._state_store.get(self._session_key)
        if state:
            return self._resume(user_text, state)

        # 3. Confirmación de acción previa del ToolAgent (no-PEV)
        conf_reply = self._tool_agent._handle_confirmation_turn(user_text)
        if conf_reply is not None:
            self._tool_agent.state.add_user(user_text)
            self._tool_agent._save_message("user", user_text)
            self._tool_agent.state.add_assistant(conf_reply)
            self._tool_agent._save_message("assistant", conf_reply)
            return conf_reply

        # 4. Añadir al historial antes de planificar
        self._tool_agent.state.add_user(user_text)
        self._tool_agent._save_message("user", user_text)

        # 5. Planificar
        plan = self._plan(user_text)
        if plan is None or not plan.steps:
            # Fallback a ToolAgent (conversacional o fallo de parsing)
            # run() ya gestionará el historial para la respuesta
            return self._tool_agent.run(user_text)

        # 6. Ejecutar plan
        state = RunState(
            run_id=uuid4().hex[:8],
            session_key=self._session_key,
            plan=plan,
            original_input=user_text,
        )
        logger.info(
            "[PEV:%s] Plan: goal='%s' steps=%d",
            state.run_id,
            plan.goal,
            len(plan.steps),
        )
        return self._execute_plan(state)

    async def run_stream(self, user_text: str) -> AsyncGenerator[str, None]:
        result = await asyncio.to_thread(self.run, user_text)
        yield result

    # ------------------------------------------------------------------
    # Planner
    # ------------------------------------------------------------------

    def _plan(self, user_text: str) -> Optional[Plan]:
        """Llama al LLM para generar un Plan estructurado. Retorna None si falla."""
        tool_names = ", ".join(self._tool_agent.registry.list().keys())
        system = PLANNER_SYSTEM_PROMPT.format(
            tool_names=tool_names,
            plan_schema=_PLAN_SCHEMA,
            max_steps=self._max_steps,
        )
        user_msg = PLANNER_USER_TEMPLATE.format(
            user_text=user_text,
            context="",  # contexto extra vacío por ahora
        )

        raw: Optional[str] = None

        # Claude
        if self._tool_agent.claude_client and self._config.use_claude:
            raw = self._plan_with_claude(system, user_msg)
        # Gemini
        elif self._tool_agent.gemini_client and self._config.use_gemini:
            raw = self._plan_with_gemini(system, user_msg)
        # Groq
        elif self._tool_agent.groq_client and self._config.use_groq:
            raw = self._plan_with_groq(system, user_msg)
        # Ollama
        else:
            raw = self._plan_with_ollama(system, user_msg)

        if not raw:
            return None

        return self._parse_plan(raw)

    def _plan_with_claude(self, system: str, user_msg: str) -> Optional[str]:
        try:
            resp = self._tool_agent.claude_client.messages.create(
                model=self._config.claude_model,
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": user_msg}],
            )
            return "".join(
                b.text for b in resp.content if hasattr(b, "text")
            ).strip()
        except Exception as e:
            logger.warning("[PEV] Claude planner error: %s", e)
            return None

    def _plan_with_gemini(self, system: str, user_msg: str) -> Optional[str]:
        try:
            from google.genai import types
            resp = self._tool_agent.gemini_client.models.generate_content(
                model=self._config.gemini_model,
                contents=[types.Content(role="user", parts=[types.Part.from_text(user_msg)])],
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                ),
            )
            if not resp.candidates:
                return None
            parts = resp.candidates[0].content.parts
            return "".join(p.text for p in parts if hasattr(p, "text") and p.text).strip()
        except Exception as e:
            logger.warning("[PEV] Gemini planner error: %s", e)
            return None

    def _plan_with_groq(self, system: str, user_msg: str) -> Optional[str]:
        try:
            resp = self._tool_agent.groq_client.chat.completions.create(
                model=self._config.groq_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                response_format={"type": "json_object"},
                max_tokens=1024,
                temperature=0.2,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as e:
            logger.warning("[PEV] Groq planner error: %s", e)
            return None

    def _plan_with_ollama(self, system: str, user_msg: str) -> Optional[str]:
        try:
            resp = requests.post(
                f"{self._config.ollama_url}/api/chat",
                json={
                    "model": self._config.ollama_model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_msg},
                    ],
                    "format": "json",
                    "stream": False,
                },
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "").strip()
        except Exception as e:
            logger.warning("[PEV] Ollama planner error: %s", e)
            return None

    def _parse_plan(self, raw: str) -> Optional[Plan]:
        """Parsea JSON crudo en Plan. Si falla retorna None."""
        text = raw.strip()
        # Eliminar markdown fences si el LLM los incluye
        text = self._extract_json_from_text(text)
        try:
            plan = Plan.model_validate_json(text)
            # Truncar a max_steps
            if len(plan.steps) > self._max_steps:
                plan = Plan(
                    goal=plan.goal,
                    steps=plan.steps[: self._max_steps],
                    constraints=plan.constraints,
                )
            return plan
        except Exception as e:
            logger.warning("[PEV] Plan parse error: %s | raw=%s", e, raw[:200])
            return None

    @staticmethod
    def _extract_json_from_text(text: str) -> str:
        """Extrae bloque JSON de respuesta con markdown fences o texto extra."""
        # Buscar ```json ... ``` o ``` ... ```
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            return m.group(1)
        # Buscar primer { ... } balanceado
        start = text.find("{")
        if start != -1:
            depth = 0
            for i, ch in enumerate(text[start:], start):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return text[start : i + 1]
        return text

    # ------------------------------------------------------------------
    # Executor
    # ------------------------------------------------------------------

    def _execute_plan(self, state: RunState) -> str:
        steps = state.plan.steps

        for idx in range(state.current_step_idx, len(steps)):
            step = steps[idx]

            # Verificar dependencias
            if not self._deps_satisfied(step, state.step_results):
                failed_dep = next(
                    (d for d in step.depends_on
                     if state.step_results.get(d, StepResult(d, "ok")).status == "fail"),
                    step.depends_on[0] if step.depends_on else "?",
                )
                state.step_results[step.id] = StepResult(
                    step_id=step.id, status="skipped",
                    error=f"Dependencia fallida: {failed_dep}",
                )
                logger.info(
                    "[PEV:%s:%s] Skipped — dep failed: %s",
                    state.run_id, step.id, failed_dep,
                )
                continue

            # Step de pregunta al usuario
            if step.requires_user_input:
                state.pending_user_input_step = step.id
                state.current_step_idx = idx
                self._state_store.put(self._session_key, state)
                logger.warning(
                    "[PEV:%s:%s] Paused: waiting user input", state.run_id, step.id
                )
                return step.action

            # Resolver args con sustituciones entre pasos
            resolved_args = self._substitute(step.args, state.step_results)

            # Verificar sensibilidad → pedir confirmación
            always_for = set(
                str(t).strip().lower()
                for t in (self._config.dry_run_always_for or [])
                if str(t).strip()
            )
            needs_confirm = step.sensitive or (
                self._config.dry_run_enabled
                and self._config.confirm_policy_enabled
                and step.tool_name
                and is_sensitive(step.tool_name, resolved_args, always_for=always_for)
            )
            if needs_confirm and step.tool_name:
                summary = build_summary(step.tool_name, resolved_args)
                state.pending_confirmation_step = step.id
                state.pending_args = resolved_args
                state.current_step_idx = idx
                self._state_store.put(self._session_key, state)
                logger.warning(
                    "[PEV:%s:%s] Paused: confirmation required", state.run_id, step.id
                )
                return (
                    f"Para continuar necesito confirmación:\n{summary}\n"
                    "¿Procedo? (sí/no)"
                )

            # Ejecutar (con retry)
            result = self._execute_with_retry(step, resolved_args, state.run_id)
            state.step_results[step.id] = result

            if result.status == "fail" and not result.retryable:
                self._state_store.clear(self._session_key)
                return (
                    f"No pude completar el paso '{step.action}': {result.error}"
                )

        # Todos los pasos completados → sintetizar
        self._state_store.clear(self._session_key)
        return self._synthesize(state)

    def _resume(self, user_text: str, state: RunState) -> str:
        """Retoma ejecución tras pausa (confirmación o input de usuario)."""

        # Caso 1: esperando confirmación
        if state.pending_confirmation_step:
            if is_negative(user_text):
                self._state_store.clear(self._session_key)
                return "De acuerdo, cancelado."
            if is_affirmative(user_text):
                step_id = state.pending_confirmation_step
                step = next(s for s in state.plan.steps if s.id == step_id)
                resolved_args = state.pending_args
                result = self._execute_with_retry(step, resolved_args, state.run_id)
                state.step_results[step_id] = result
                state.pending_confirmation_step = None
                state.pending_args = {}
                state.current_step_idx += 1
                return self._execute_plan(state)
            return "¿Procedo? (sí/no)"

        # Caso 2: esperando input del usuario
        if state.pending_user_input_step:
            step_id = state.pending_user_input_step
            state.step_results[step_id] = StepResult(
                step_id=step_id,
                status="ok",
                output={"user_input": user_text},
            )
            state.pending_user_input_step = None
            state.current_step_idx += 1
            return self._execute_plan(state)

        # Estado corrupto → limpiar y replantear
        self._state_store.clear(self._session_key)
        return self.run(user_text)

    def _execute_with_retry(
        self, step: PlanStep, args: Dict[str, Any], run_id: str
    ) -> StepResult:
        tool_name = step.tool_name or ""
        for attempt in range(self._retry_max + 1):
            t0 = time.time()
            raw = self._tool_agent._execute_tool(tool_name, args)
            duration_ms = int((time.time() - t0) * 1000)

            vctx = VerifyContext(
                timeout_ms=self._config.verifier_timeout_ms,
                max_items=self._config.verifier_max_items,
                sample_if_over=self._config.verifier_sample_if_over,
                strict=self._config.verifier_strict,
                turn_id=run_id,
            )
            report = verify(tool_name, args, raw, vctx)

            logger.info(
                "[PEV:%s:%s] Exec %s args_summary=%s duration_ms=%d",
                run_id, step.id, tool_name,
                str(args)[:80], duration_ms,
            )
            logger.info(
                "[PEV:%s:%s] Verify: %s", run_id, step.id, report.status
            )

            if report.status == "ok":
                return StepResult(step_id=step.id, status="ok", output=raw)

            if report.retryable and attempt < self._retry_max:
                args = self._patch_args_for_retry(tool_name, args, report)
                logger.info(
                    "[PEV:%s:%s] Retry %d", run_id, step.id, attempt + 1
                )
                continue

            return StepResult(
                step_id=step.id,
                status="fail",
                output=raw if isinstance(raw, dict) else {},
                error=report.reason,
                retryable=report.retryable,
                suggested_fix=report.suggested_fix,
            )

        # Nunca debería llegar aquí, pero por seguridad
        return StepResult(step_id=step.id, status="fail", error="Max retries reached.")

    @staticmethod
    def _patch_args_for_retry(
        tool_name: str, args: Dict[str, Any], report: Any
    ) -> Dict[str, Any]:
        """Ajusta args para reintento. Para web_search añade más términos."""
        if tool_name == "web_search":
            query = str(args.get("query", ""))
            if query and "más información" not in query:
                args = {**args, "query": query + " más información"}
        return args

    @staticmethod
    def _deps_satisfied(step: PlanStep, step_results: Dict[str, StepResult]) -> bool:
        """True si todas las dependencias del step están en estado 'ok' o 'skipped'."""
        for dep_id in step.depends_on:
            result = step_results.get(dep_id)
            if result is None or result.status == "fail":
                return False
        return True

    @staticmethod
    def _substitute(
        args: Dict[str, Any], step_results: Dict[str, StepResult]
    ) -> Dict[str, Any]:
        """
        Sustituye referencias {{sN.field}} en los args con outputs de pasos anteriores.
        Ejemplo: args={"q": "{{s1.data.result}}"} →
                 args={"q": step_results["s1"].output["data"]["result"]}
        """
        _REF = re.compile(r"\{\{(\w+)\.(.+?)\}\}")

        def _resolve(value: Any) -> Any:
            if not isinstance(value, str):
                return value
            match = _REF.fullmatch(value.strip())
            if match:
                step_id, path = match.group(1), match.group(2)
                result = step_results.get(step_id)
                if result is None:
                    return value
                obj: Any = result.output
                for key in path.split("."):
                    if isinstance(obj, dict):
                        obj = obj.get(key, value)
                    else:
                        return value
                return obj
            return value

        return {k: _resolve(v) for k, v in args.items()}

    # ------------------------------------------------------------------
    # Synthesizer
    # ------------------------------------------------------------------

    def _synthesize(self, state: RunState) -> str:
        """Resume los resultados del plan en lenguaje natural."""
        outputs_summary = json.dumps(
            {sid: res.output for sid, res in state.step_results.items()},
            ensure_ascii=False,
            default=str,
        )[:1500]

        user_msg = (
            f"Objetivo: {state.plan.goal}\n"
            f"Resultados de los pasos:\n{outputs_summary}"
        )

        raw: Optional[str] = None

        try:
            if self._tool_agent.claude_client and self._config.use_claude:
                resp = self._tool_agent.claude_client.messages.create(
                    model=self._config.claude_model,
                    max_tokens=512,
                    system=SYNTHESIS_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_msg}],
                )
                raw = "".join(
                    b.text for b in resp.content if hasattr(b, "text")
                ).strip()

            elif self._tool_agent.gemini_client and self._config.use_gemini:
                from google.genai import types
                resp = self._tool_agent.gemini_client.models.generate_content(
                    model=self._config.gemini_model,
                    contents=[types.Content(role="user", parts=[types.Part.from_text(user_msg)])],
                    config=types.GenerateContentConfig(
                        system_instruction=SYNTHESIS_SYSTEM_PROMPT,
                    ),
                )
                if resp.candidates:
                    raw = "".join(
                        p.text for p in resp.candidates[0].content.parts
                        if hasattr(p, "text") and p.text
                    ).strip()

            elif self._tool_agent.groq_client and self._config.use_groq:
                resp = self._tool_agent.groq_client.chat.completions.create(
                    model=self._config.groq_model,
                    messages=[
                        {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    max_tokens=512,
                    temperature=0.7,
                )
                raw = (resp.choices[0].message.content or "").strip()

            else:
                resp = requests.post(
                    f"{self._config.ollama_url}/api/chat",
                    json={
                        "model": self._config.ollama_model,
                        "messages": [
                            {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
                            {"role": "user", "content": user_msg},
                        ],
                        "stream": False,
                    },
                    timeout=60,
                )
                resp.raise_for_status()
                raw = resp.json().get("message", {}).get("content", "").strip()

        except Exception as e:
            logger.warning("[PEV] Synthesizer error: %s", e)

        if raw:
            self._tool_agent.state.add_assistant(raw)
            self._tool_agent._save_message("assistant", raw)
            return raw

        # Fallback: construir desde outputs directamente
        parts: List[str] = []
        for sid, res in state.step_results.items():
            if res.status == "ok":
                step = next((s for s in state.plan.steps if s.id == sid), None)
                label = step.action if step else sid
                out_str = json.dumps(res.output, ensure_ascii=False, default=str)[:300]
                parts.append(f"• {label}: {out_str}")
        fallback = "Listo. " + " ".join(parts) if parts else "Completado."
        self._tool_agent.state.add_assistant(fallback)
        self._tool_agent._save_message("assistant", fallback)
        return fallback
