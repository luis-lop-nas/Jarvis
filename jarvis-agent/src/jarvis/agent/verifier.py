from __future__ import annotations

import json
import shlex
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class VerifyContext:
    timeout_ms: int = 1500
    max_items: int = 50
    sample_if_over: int = 200
    strict: bool = False
    turn_id: Optional[str] = None


@dataclass(frozen=True)
class VerifyReport:
    status: str  # ok | fail | unknown
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)
    suggested_fix: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    retryable: bool = False


def verify(
    tool_name: str,
    args: Dict[str, Any],
    tool_result: Any,
    context: VerifyContext,
) -> VerifyReport:
    tool = (tool_name or "").strip().lower()
    start = time.time()
    try:
        if tool == "filesystem":
            report = _verify_filesystem(args, tool_result)
        elif tool == "shell":
            report = _verify_shell(args, tool_result)
        elif tool == "open_app":
            report = _verify_open_app(args, tool_result)
        elif tool in {"download_file", "search_and_download"}:
            report = _verify_download(tool, args, tool_result)
        elif tool == "calendar":
            report = _verify_calendar(args, tool_result)
        elif tool == "send_email":
            report = _verify_send_email(args, tool_result)
        elif tool == "send_message":
            report = _verify_send_message(args, tool_result)
        else:
            report = VerifyReport(
                status="unknown",
                reason=f"No hay verificador específico para tool '{tool}'.",
            )
    except Exception as e:
        report = VerifyReport(
            status="unknown",
            reason=f"Verifier exception: {type(e).__name__}",
            details={"error": str(e)},
        )

    duration_ms = int((time.time() - start) * 1000)
    _log_verify(tool, report, duration_ms, context.turn_id)
    return report


def _verify_filesystem(args: Dict[str, Any], tool_result: Any) -> VerifyReport:
    result = _as_dict(tool_result)
    if _result_failed(result):
        return VerifyReport(
            status="fail",
            reason="La operación filesystem reportó error.",
            details=result,
            retryable=False,
        )

    action = str(result.get("action") or args.get("action", "")).lower().strip()
    if action in {"write_text", "mkdir"}:
        path = Path(str(result.get("path") or args.get("path", ""))).expanduser()
        exists = path.exists()
        if not exists:
            return VerifyReport(
                status="fail",
                reason=f"No existe el path esperado tras '{action}'.",
                evidence={"path": str(path)},
                retryable=True,
                suggested_fix="Revisa permisos/ruta e inténtalo de nuevo.",
            )
        if action == "write_text" and path.is_file() and path.stat().st_size == 0:
            return VerifyReport(
                status="fail",
                reason="El archivo existe pero quedó vacío.",
                evidence={"path": str(path), "size": 0},
                retryable=True,
            )
        return VerifyReport(status="ok", reason="Filesystem verificado.", evidence={"path": str(path)})

    if action == "copy":
        dst = Path(str(result.get("destination") or args.get("destination", ""))).expanduser()
        if not dst.exists():
            return VerifyReport(
                status="fail",
                reason="El destino de copy no existe.",
                evidence={"destination": str(dst)},
                retryable=True,
            )
        return VerifyReport(status="ok", reason="Copy verificado.", evidence={"destination": str(dst)})

    if action in {"move", "rename"}:
        src = str(result.get("source") or result.get("old_path") or args.get("path", ""))
        dst = str(result.get("destination") or result.get("new_path") or args.get("destination", ""))
        src_p = Path(src).expanduser() if src else None
        dst_p = Path(dst).expanduser() if dst else None
        src_ok = (src_p is None) or (not src_p.exists())
        dst_ok = (dst_p is not None) and dst_p.exists()
        if not (src_ok and dst_ok):
            return VerifyReport(
                status="fail",
                reason="Move/rename no refleja el estado esperado.",
                evidence={
                    "source_exists": src_p.exists() if src_p else None,
                    "destination_exists": dst_p.exists() if dst_p else None,
                    "source": str(src_p) if src_p else "",
                    "destination": str(dst_p) if dst_p else "",
                },
                retryable=True,
            )
        return VerifyReport(status="ok", reason="Move/rename verificado.", evidence={"destination": str(dst_p)})

    if action == "delete":
        path = Path(str(result.get("path") or args.get("path", ""))).expanduser()
        if path.exists():
            return VerifyReport(
                status="fail",
                reason="Delete reportó éxito, pero el path aún existe.",
                evidence={"path": str(path)},
                retryable=False,
            )
        return VerifyReport(status="ok", reason="Delete verificado.", evidence={"path": str(path)})

    return VerifyReport(status="unknown", reason=f"No hay verificación específica para action '{action}'.")


def _verify_shell(args: Dict[str, Any], tool_result: Any) -> VerifyReport:
    result = _as_dict(tool_result)
    if result.get("type") in {"deny", "dry_run"}:
        return VerifyReport(status="unknown", reason="Shell no ejecutado (guard).", details=result)

    returncode = result.get("returncode")
    if isinstance(returncode, int) and returncode != 0:
        return VerifyReport(
            status="fail",
            reason="Comando shell terminó con error.",
            details={"returncode": returncode, "stderr": str(result.get("stderr", ""))[:500]},
            suggested_fix="Revisa stderr y corrige el comando.",
            retryable=True,
        )

    cmd = str(result.get("command") or args.get("command", "")).strip()
    parsed = _safe_split(cmd)
    if not parsed:
        return VerifyReport(status="unknown", reason="No se pudo parsear comando para verificación.")
    verb = parsed[0]

    if verb == "mkdir" and len(parsed) >= 2:
        path = Path(parsed[-1]).expanduser()
        return VerifyReport(
            status="ok" if path.exists() else "fail",
            reason="mkdir verificado." if path.exists() else "mkdir no creó el directorio esperado.",
            evidence={"path": str(path)},
            retryable=not path.exists(),
        )
    if verb == "touch" and len(parsed) >= 2:
        path = Path(parsed[-1]).expanduser()
        return VerifyReport(
            status="ok" if path.exists() else "fail",
            reason="touch verificado." if path.exists() else "touch no creó/actualizó el archivo.",
            evidence={"path": str(path)},
            retryable=not path.exists(),
        )
    if verb in {"mv", "cp"} and len(parsed) >= 3:
        src = Path(parsed[-2]).expanduser()
        dst = Path(parsed[-1]).expanduser()
        if verb == "mv":
            ok = (not src.exists()) and dst.exists()
            return VerifyReport(
                status="ok" if ok else "fail",
                reason="mv verificado." if ok else "mv no refleja estado esperado.",
                evidence={"source_exists": src.exists(), "destination_exists": dst.exists()},
                retryable=not ok,
            )
        ok = dst.exists()
        return VerifyReport(
            status="ok" if ok else "fail",
            reason="cp verificado." if ok else "cp no creó destino esperado.",
            evidence={"destination_exists": dst.exists()},
            retryable=not ok,
        )
    if verb == "rm" and len(parsed) >= 2:
        target = Path(parsed[-1]).expanduser()
        ok = not target.exists()
        return VerifyReport(
            status="ok" if ok else "fail",
            reason="rm verificado." if ok else "rm no eliminó el objetivo esperado.",
            evidence={"target_exists": target.exists(), "target": str(target)},
            retryable=False,
        )

    return VerifyReport(status="unknown", reason="Sin verificador específico para este comando shell.")


def _verify_open_app(args: Dict[str, Any], tool_result: Any) -> VerifyReport:
    result = _as_dict(tool_result)
    returncode = result.get("returncode")
    if isinstance(returncode, int) and returncode != 0:
        return VerifyReport(
            status="fail",
            reason="open_app devolvió returncode no cero.",
            details={"returncode": returncode, "stderr": str(result.get("stderr", ""))[:300]},
            retryable=True,
        )

    app = str(args.get("app", "")).strip()
    if not app:
        return VerifyReport(status="unknown", reason="No hay app explícita para verificar (puede ser URL/archivo).")

    running = _is_app_running(app)
    if running:
        return VerifyReport(status="ok", reason="App abierta y proceso activo.", evidence={"app": app})
    return VerifyReport(
        status="fail",
        reason="No se detecta proceso de la app tras open_app.",
        evidence={"app": app},
        suggested_fix="Verifica nombre de app o permisos de apertura.",
        retryable=True,
    )


def _verify_download(tool_name: str, args: Dict[str, Any], tool_result: Any) -> VerifyReport:
    result = _as_dict(tool_result)
    if tool_name == "search_and_download":
        if not result.get("success", False):
            return VerifyReport(status="fail", reason="search_and_download reportó fallo.", details=result)
        download = _as_dict(result.get("download", {}))
        path = Path(str(download.get("path", ""))).expanduser() if download.get("path") else None
        if not path or not path.exists() or path.stat().st_size <= 0:
            return VerifyReport(
                status="fail",
                reason="No existe archivo descargado válido tras search_and_download.",
                evidence={"path": str(path) if path else ""},
                retryable=True,
            )
        return VerifyReport(status="ok", reason="Descarga verificada.", evidence={"path": str(path), "size": path.stat().st_size})

    if not result.get("success", False):
        return VerifyReport(status="fail", reason="download_file reportó fallo.", details=result)
    path = Path(str(result.get("path", ""))).expanduser() if result.get("path") else None
    if not path or not path.exists():
        return VerifyReport(status="fail", reason="download_file no dejó archivo en ruta esperada.", retryable=True)
    size = path.stat().st_size
    if size <= 0:
        return VerifyReport(status="fail", reason="download_file creó archivo vacío.", evidence={"path": str(path), "size": size}, retryable=True)
    return VerifyReport(status="ok", reason="Archivo descargado verificado.", evidence={"path": str(path), "size": size})


def _verify_calendar(args: Dict[str, Any], tool_result: Any) -> VerifyReport:
    result = _as_dict(tool_result)
    if not result.get("ok", False):
        return VerifyReport(status="fail", reason="Calendar reportó error.", details=result, retryable=True)
    action = str(args.get("action", "")).strip().lower()
    if action in {"create", "create_event", "update", "edit", "delete", "remove"}:
        return VerifyReport(
            status="unknown",
            reason="Calendar no expone ID verificable en la salida actual.",
            evidence={"result": str(result.get("result", ""))[:200], "action": action},
        )
    return VerifyReport(status="ok", reason="Consulta de calendario completada.")


def _verify_send_email(args: Dict[str, Any], tool_result: Any) -> VerifyReport:
    result = _as_dict(tool_result)
    if not result.get("ok", False):
        return VerifyReport(status="fail", reason="send_email reportó error.", details=result, retryable=True)
    return VerifyReport(
        status="unknown",
        reason="Proveedor local (Mail.app) sin message_id verificable.",
        evidence={"result": str(result.get("result", ""))[:200], "action": str(args.get("action", "send"))},
    )


def _verify_send_message(args: Dict[str, Any], tool_result: Any) -> VerifyReport:
    result = _as_dict(tool_result)
    if not result.get("ok", False):
        return VerifyReport(status="fail", reason="send_message reportó error.", details=result, retryable=True)
    return VerifyReport(
        status="unknown",
        reason="Canal UI scripting sin ack/message_id verificable.",
        evidence={"result": str(result.get("result", ""))[:200]},
    )


def _result_failed(result: Dict[str, Any]) -> bool:
    if "ok" in result and result.get("ok") is False:
        return True
    if "success" in result and result.get("success") is False:
        return True
    return False


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {"raw": value}


def _safe_split(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=True)
    except Exception:
        return []


def _is_app_running(app_name: str) -> bool:
    proc = subprocess.run(
        ["pgrep", "-if", app_name],
        capture_output=True,
        text=True,
        timeout=1.0,
    )
    return proc.returncode == 0 and bool(proc.stdout.strip())


def _log_verify(tool: str, report: VerifyReport, duration_ms: int, turn_id: Optional[str]) -> None:
    payload = {
        "event": "tool_verify",
        "tool_name": tool,
        "status": report.status,
        "reason": report.reason,
        "duration_ms": duration_ms,
        "turn_id": turn_id or "",
    }
    print(f"🔎 {json.dumps(payload, ensure_ascii=False)}")

