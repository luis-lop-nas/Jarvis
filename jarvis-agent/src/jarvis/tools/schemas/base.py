from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class ToolErrorModel(BaseModel):
    code: str = "tool_error"
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)


class ToolOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    ok: bool = True
    data: Optional[Dict[str, Any]] = None
    message: Optional[str] = None
    error: Optional[ToolErrorModel] = None
    meta: Optional[Dict[str, Any]] = None


def normalize_tool_output(tool_name: str, raw_output: Any) -> Dict[str, Any]:
    """
    Envuelve retornos legacy en un contrato común ToolOutput sin romper compatibilidad.
    """
    if isinstance(raw_output, ToolOutput):
        return raw_output.model_dump()

    if isinstance(raw_output, dict):
        src = dict(raw_output)
        ok = _infer_ok(src)
        message = _infer_message(src)

        err: Optional[ToolErrorModel] = None
        if "error" in src and src.get("error"):
            raw_err = src.get("error")
            if isinstance(raw_err, dict):
                err = ToolErrorModel(
                    code=str(raw_err.get("code", "tool_error")),
                    message=str(raw_err.get("message", "")) or "tool_error",
                    details=raw_err.get("details", {}) if isinstance(raw_err.get("details", {}), dict) else {},
                )
            else:
                err = ToolErrorModel(code="tool_error", message=str(raw_err))

        data = src.get("data")
        if not isinstance(data, dict):
            data = {
                k: v
                for k, v in src.items()
                if k not in {"ok", "data", "message", "error", "meta"}
            } or None

        meta = src.get("meta") if isinstance(src.get("meta"), dict) else {}
        meta = dict(meta)
        meta["tool_name"] = tool_name

        return ToolOutput(
            ok=ok,
            data=data,
            message=message,
            error=err,
            meta=meta,
        ).model_dump()

    if isinstance(raw_output, str):
        return ToolOutput(
            ok=True,
            data={"raw": raw_output},
            message=raw_output,
            meta={"tool_name": tool_name},
        ).model_dump()

    return ToolOutput(
        ok=True,
        data={"raw": raw_output},
        message=None,
        meta={"tool_name": tool_name},
    ).model_dump()


def _infer_ok(out: Dict[str, Any]) -> bool:
    if "ok" in out:
        return bool(out.get("ok"))
    if "success" in out:
        return bool(out.get("success"))
    if "returncode" in out:
        rc = out.get("returncode")
        return isinstance(rc, int) and rc == 0
    if "error" in out and out.get("error"):
        return False
    return True


def _infer_message(out: Dict[str, Any]) -> Optional[str]:
    for key in ("message", "result", "error"):
        value = out.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
