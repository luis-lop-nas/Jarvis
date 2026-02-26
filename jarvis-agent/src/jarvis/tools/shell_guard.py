from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class ShellGuardDecision:
    decision: str  # allow | confirm | deny
    risk_level: str  # low | medium | high
    reason: str
    normalized_command: str
    matches: List[str]


_SYSTEM_PATH_PREFIXES = ("/System", "/Library", "/usr", "/bin", "/sbin", "/etc")

_RE_FORK_BOMB = re.compile(r":\(\)\s*\{\s*:\|:&\s*;\s*\}\s*;", re.IGNORECASE)
_RE_RM_ROOT = re.compile(r"\brm\b[^\n]*-(?:[^\n]*r[^\n]*f|[^\n]*f[^\n]*r)[^\n]*(?:^|\s)(/|\/*|\~)(?:\s|$)")
_RE_RM_ALL_ROOT = re.compile(r"\brm\b[^\n]*-(?:[^\n]*r|[^\n]*f)[^\n]*(?:/+\*|~)(?:\s|$)")
_RE_DISK_OVERWRITE = re.compile(
    r"\bdd\b[^\n]*\bif=/dev/zero\b[^\n]*\bof=/dev/(r?disk\d+)\b",
    re.IGNORECASE,
)
_RE_MKFS_DEVICE = re.compile(r"\bmkfs[\w.-]*\b[^\n]*/dev/(r?disk\d+)", re.IGNORECASE)
_RE_SHUTDOWN = re.compile(r"\b(shutdown\s+-h\s+now|reboot)\b", re.IGNORECASE)
_RE_KILL_ALL = re.compile(r"\bkill\s+-9\s+-1\b", re.IGNORECASE)

_RE_SUDO = re.compile(r"(^|\s)sudo(\s|$)", re.IGNORECASE)
_RE_RM_RF = re.compile(r"\brm\b[^\n]*-(?:[^\n]*r|[^\n]*f)", re.IGNORECASE)
_RE_WILDCARD = re.compile(r"(\*|\?\b|/\*\*|/\*|\s\.)")
_RE_CHMOD_CHOWN_R = re.compile(r"\b(chmod|chown)\b[^\n]*\s-[^\n]*R", re.IGNORECASE)
_RE_DEFAULTS_WRITE = re.compile(r"\bdefaults\s+write\b", re.IGNORECASE)
_RE_SYSTEM_TOOLS = re.compile(r"\b(launchctl|systemsetup|networksetup)\b", re.IGNORECASE)
_RE_CURL_PIPE_SH = re.compile(r"\b(curl|wget)\b[^\n]*\|\s*(sh|bash|zsh)\b", re.IGNORECASE)
_RE_PYTHON_C_CURL = re.compile(r"\bpython\d?\b[^\n]*-c[^\n]*\$\((curl|wget)[^\)]*\)", re.IGNORECASE)


def analyze_shell_command(
    command: str,
    *,
    cwd: str | None = None,
    mode: str = "strict",
    deny_patterns: List[str] | None = None,
    confirm_patterns: List[str] | None = None,
) -> ShellGuardDecision:
    cmd = _normalize_command(command)
    matches: List[str] = []

    if _RE_FORK_BOMB.search(cmd):
        matches.append("fork_bomb")
        return _deny("Fork bomb detectada.", cmd, matches)
    if _RE_RM_ROOT.search(cmd) or _RE_RM_ALL_ROOT.search(cmd):
        matches.append("rm_root")
        return _deny("Intento de borrado masivo de raíz/home.", cmd, matches)
    if _RE_DISK_OVERWRITE.search(cmd):
        matches.append("disk_overwrite")
        return _deny("Escritura directa destructiva sobre dispositivo de disco.", cmd, matches)
    if _RE_MKFS_DEVICE.search(cmd):
        matches.append("mkfs_device")
        return _deny("Formateo directo de dispositivo detectado.", cmd, matches)
    if _RE_SHUTDOWN.search(cmd):
        matches.append("shutdown_reboot")
        return _deny("Comando de apagado/reinicio bloqueado por seguridad.", cmd, matches)
    if _RE_KILL_ALL.search(cmd):
        matches.append("kill_all")
        return _deny("Comando de kill indiscriminado bloqueado.", cmd, matches)

    _tokens = _tokenize(cmd)
    if _RE_SUDO.search(cmd):
        matches.append("sudo")
    if _RE_RM_RF.search(cmd):
        matches.append("rm_recursive_or_force")
    if _RE_WILDCARD.search(cmd) and _has_destructive_verb(_tokens):
        matches.append("destructive_wildcard")
    if _targets_system_path(_tokens):
        matches.append("system_path_target")
    if _RE_CHMOD_CHOWN_R.search(cmd):
        matches.append("chmod_chown_recursive")
    if _RE_DEFAULTS_WRITE.search(cmd):
        matches.append("defaults_write")
    if _RE_SYSTEM_TOOLS.search(cmd):
        matches.append("system_tool")
    if _RE_CURL_PIPE_SH.search(cmd) or _RE_PYTHON_C_CURL.search(cmd):
        matches.append("remote_pipe_exec")

    for pat in deny_patterns or []:
        if _safe_search(pat, cmd):
            matches.append(f"deny_override:{pat}")
            return _deny("Coincide con patrón deny configurado.", cmd, matches)

    for pat in confirm_patterns or []:
        if _safe_search(pat, cmd):
            matches.append(f"confirm_override:{pat}")

    if matches:
        risk = "high" if any(m in matches for m in ("sudo", "remote_pipe_exec", "rm_recursive_or_force", "system_path_target")) else "medium"
        return ShellGuardDecision(
            decision="confirm",
            risk_level=risk,
            reason="Comando potencialmente peligroso; requiere confirmación explícita.",
            normalized_command=cmd,
            matches=matches,
        )

    if mode.lower() == "strict" and _looks_state_changing(_tokens):
        return ShellGuardDecision(
            decision="confirm",
            risk_level="medium",
            reason="Modo strict: cambios de estado requieren confirmación.",
            normalized_command=cmd,
            matches=["strict_state_change"],
        )

    return ShellGuardDecision(
        decision="allow",
        risk_level="low",
        reason="Comando permitido.",
        normalized_command=cmd,
        matches=[],
    )


def _deny(reason: str, cmd: str, matches: List[str]) -> ShellGuardDecision:
    return ShellGuardDecision(
        decision="deny",
        risk_level="high",
        reason=reason,
        normalized_command=cmd,
        matches=matches,
    )


def _normalize_command(command: str) -> str:
    return " ".join((command or "").strip().split())


def _tokenize(command: str) -> List[str]:
    try:
        return shlex.split(command, posix=True)
    except Exception:
        return command.split()


def _targets_system_path(tokens: List[str]) -> bool:
    for tok in tokens:
        if tok.startswith("-"):
            continue
        if tok.startswith(_SYSTEM_PATH_PREFIXES):
            return True
    return False


def _has_destructive_verb(tokens: List[str]) -> bool:
    if not tokens:
        return False
    return tokens[0] in {"rm", "mv", "cp", "rsync", "chmod", "chown"}


def _looks_state_changing(tokens: List[str]) -> bool:
    if not tokens:
        return False
    return tokens[0] in {"mv", "cp", "rsync", "chmod", "chown", "defaults", "launchctl", "systemsetup", "networksetup"}


def _safe_search(pattern: str, text: str) -> bool:
    try:
        return bool(re.search(pattern, text, re.IGNORECASE))
    except re.error:
        return False

