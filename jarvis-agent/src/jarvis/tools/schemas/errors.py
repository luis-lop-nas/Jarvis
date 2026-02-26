from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import ValidationError


_SECRET_KEYS = ("key", "token", "password", "secret", "api")


def build_validation_error_payload(
    *,
    tool: str,
    stage: str,
    err: ValidationError,
    message: str,
    raw_output: Optional[Any] = None,
    include_raw: bool = False,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "type": "tool_validation_error",
        "tool": tool,
        "stage": stage,
        "message": message,
        "errors": _sanitize_errors(err.errors()),
    }
    if include_raw and raw_output is not None:
        payload["details"] = {"raw_output": _mask_obj(raw_output)}
    return payload


def _sanitize_errors(errors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    clean: List[Dict[str, Any]] = []
    for e in errors:
        item = {
            "loc": list(e.get("loc", [])),
            "msg": str(e.get("msg", "")),
            "type": str(e.get("type", "")),
        }
        if "input" in e:
            item["input"] = _mask_obj(e.get("input"))
        clean.append(item)
    return clean


def _mask_obj(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            key = str(k).lower()
            if any(s in key for s in _SECRET_KEYS):
                out[k] = "[REDACTED]"
            else:
                out[k] = _mask_obj(v)
        return out
    if isinstance(obj, list):
        return [_mask_obj(x) for x in obj]
    if isinstance(obj, str):
        low = obj.lower()
        if any(s in low for s in _SECRET_KEYS):
            return "[REDACTED]"
    return obj

