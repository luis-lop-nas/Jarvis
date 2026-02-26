"""
prompt_guard.py

Detección básica de prompt injection en inputs que llegan al agente desde
el LLM o el usuario antes de ejecutar tools.

No es una solución hermética — las defensa principal es el shell_guard y el
sistema de confirmaciones. Este módulo añade una capa de detección adicional
para los patrones más comunes y conocidos.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# ── Patrones de inyección conocidos ──────────────────────────────────────────

# Patrones que intentan suplantar instrucciones del sistema o cambiar el rol del LLM
_ROLE_OVERRIDE_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bignora\s+(todas?\s+las?\s+)?(instrucciones|reglas|restricciones)\b", re.I),
    re.compile(r"\bignore\s+(all\s+)?(previous|prior|above)\s+instructions?\b", re.I),
    re.compile(r"\bforget\s+(all\s+)?(your|previous)\s+(instructions?|rules?|context)\b", re.I),
    re.compile(r"\byou\s+are\s+now\s+(?!jarvis)", re.I),  # "you are now [another persona]"
    re.compile(r"\bact\s+as\s+(if\s+you\s+are\s+)?(?!jarvis)", re.I),
    re.compile(r"\bnew\s+(system\s+)?prompt\b", re.I),
    re.compile(r"\bsystem\s*:\s*(ignore|override|forget)", re.I),
    re.compile(r"\[INST\]|\[\/INST\]|<\|im_start\|>|<\|im_end\|>", re.I),  # tokens LLM
    re.compile(r"###\s*(system|instruction|override)\s*:", re.I),
]

# Patrones que intentan exfiltrar datos o ejecutar comandos fuera del contexto
_EXFIL_PATTERNS: List[re.Pattern] = [
    re.compile(r"\brepeat\s+(everything|all)\s+(above|before|prior)\b", re.I),
    re.compile(r"\bprint\s+(your\s+)?(system\s+)?prompt\b", re.I),
    re.compile(r"\breveal\s+(your\s+)?(system\s+|hidden\s+)?instructions?\b", re.I),
    re.compile(r"\bmuéstrame\s+(el\s+)?(prompt|instrucciones)\s+(del\s+sistema|ocultas?)\b", re.I),
    re.compile(r"\bexfiltr", re.I),
]

# Patrones específicos a tool args que intentan escapar del contexto
_TOOL_INJECTION_PATTERNS: List[re.Pattern] = [
    # Inyección en rutas de archivo
    re.compile(r"\.\./.*\.\./"),               # path traversal ../../
    re.compile(r"[;&|`$]"),                    # shell metacharacters en paths
    re.compile(r"\x00"),                       # null byte
    # Intentos de sobrescribir archivos críticos via filesystem tool
    re.compile(r"/(etc/passwd|etc/shadow|etc/sudoers)", re.I),
    re.compile(r"~/(\.ssh|\.aws|\.gnupg)/", re.I),
]


@dataclass
class InjectionReport:
    detected: bool
    patterns_matched: List[str]
    risk_level: str  # "low" | "medium" | "high"
    message: str


def scan_text(text: str) -> InjectionReport:
    """
    Escanea un texto libre buscando patrones de prompt injection.

    Retorna un InjectionReport con detected=True si se encontró algo sospechoso.
    No bloquea — el caller decide qué hacer con el resultado.
    """
    matched: List[str] = []

    for pat in _ROLE_OVERRIDE_PATTERNS:
        if pat.search(text):
            matched.append(f"role_override:{pat.pattern[:40]}")

    for pat in _EXFIL_PATTERNS:
        if pat.search(text):
            matched.append(f"exfil:{pat.pattern[:40]}")

    if not matched:
        return InjectionReport(
            detected=False, patterns_matched=[], risk_level="none", message=""
        )

    risk = "high" if len(matched) >= 2 else "medium"
    return InjectionReport(
        detected=True,
        patterns_matched=matched,
        risk_level=risk,
        message=(
            f"Posible prompt injection detectado ({len(matched)} patrón/es). "
            "La petición fue procesada pero se recomienda revisión."
        ),
    )


def scan_tool_args(tool_name: str, args: Dict[str, Any]) -> InjectionReport:
    """
    Escanea los args de una tool buscando patrones de inyección en valores string.

    Principalmente útil para args de filesystem (path traversal) y shell.
    """
    matched: List[str] = []

    for key, value in args.items():
        if not isinstance(value, str):
            continue
        for pat in _TOOL_INJECTION_PATTERNS:
            if pat.search(value):
                matched.append(f"tool_inject[{key}]:{pat.pattern[:40]}")

    if not matched:
        return InjectionReport(
            detected=False, patterns_matched=[], risk_level="none", message=""
        )

    return InjectionReport(
        detected=True,
        patterns_matched=matched,
        risk_level="high",
        message=(
            f"Patrón de inyección en args de '{tool_name}': "
            f"{', '.join(matched[:3])}."
        ),
    )
