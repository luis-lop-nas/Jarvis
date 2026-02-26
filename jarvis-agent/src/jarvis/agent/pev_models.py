"""
pev_models.py

Modelos Pydantic + dataclasses para el pipeline PEV (Planner → Executor → Verifier).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_validator


class PlanStep(BaseModel):
    id: str
    tool_name: Optional[str] = None       # None → ask_user step
    action: str                           # descripción humana
    args: Dict[str, Any] = {}
    requires_user_input: bool = False
    depends_on: List[str] = []
    success_criteria: str = ""
    sensitive: bool = False


class Plan(BaseModel):
    goal: str
    steps: List[PlanStep]
    constraints: Dict[str, Any] = {}

    @field_validator("steps")
    @classmethod
    def max_steps(cls, v: List[PlanStep]) -> List[PlanStep]:
        # Truncation to PEV_MAX_STEPS is enforced in PEVAgent after model_validate,
        # so this validator just passes the list through.
        return v


@dataclass
class StepResult:
    step_id: str
    status: str           # "ok" | "fail" | "skipped" | "paused_confirm" | "paused_input"
    output: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    retryable: bool = False
    suggested_fix: str = ""


@dataclass
class RunState:
    run_id: str
    session_key: str
    plan: Plan
    current_step_idx: int = 0
    step_results: Dict[str, StepResult] = field(default_factory=dict)
    pending_confirmation_step: Optional[str] = None   # step_id esperando sí/no
    pending_user_input_step: Optional[str] = None     # step_id esperando dato
    pending_args: Dict[str, Any] = field(default_factory=dict)  # args resueltos para step pendiente
    original_input: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
