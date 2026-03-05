"""
send_message.py

Envía mensajes a través de apps de mensajería de macOS:
  - Messages  — iMessage o SMS, completamente automatizado vía AppleScript
  - WhatsApp  — UI scripting con System Events (requiere permiso Accesibilidad)
  - Telegram  — UI scripting con System Events (requiere permiso Accesibilidad)

Seguridad: los textos del usuario se pasan como argumentos argv a osascript
(nunca interpolados en el cuerpo del script). Esto elimina cualquier riesgo
de AppleScript injection, independientemente del contenido del mensaje.

Permisos necesarios en macOS:
  - Messages:           Ajustes → Privacidad → Automatización → Terminal → Messages ✓
  - WhatsApp/Telegram:  Ajustes → Privacidad → Accesibilidad → Terminal ✓
"""

from __future__ import annotations

import re
import subprocess
from typing import Any, Dict


# ── Constantes ────────────────────────────────────────────────────────────────

# Plataformas canónicas soportadas
_PLATFORMS = {"messages", "whatsapp", "telegram"}

# Alias normalizados a nombres canónicos
_PLATFORM_ALIASES: Dict[str, str] = {
    "imessage":  "messages",
    "sms":       "messages",
    "texto":     "messages",
    "mensajes":  "messages",
    "wa":        "whatsapp",
    "wapp":      "whatsapp",
    "tg":        "telegram",
}

# Timeout para AppleScript de automatización directa (Messages)
_TIMEOUT_DIRECT = 8

# Timeout para UI scripting (WhatsApp / Telegram: necesitan tiempo de arranque)
_TIMEOUT_UI = 12


# ── Helpers de seguridad ──────────────────────────────────────────────────────

def _sanitize(text: str) -> str:
    """
    Elimina bytes nulos y caracteres de control C0/C1 (excepto \\n y \\t)
    que podrían interferir con AppleScript o keystroke.
    Los acentos y caracteres Unicode normales se conservan.
    """
    return re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]", "", text)


def _run_applescript(
    script: str,
    *args: str,
    timeout: int = _TIMEOUT_DIRECT,
) -> Dict[str, Any]:
    """
    Ejecuta un script AppleScript pasado por stdin.
    Los argumentos del usuario se pasan como argv separados (no interpolados),
    lo que impide completamente cualquier forma de AppleScript injection.

    Returns:
        {"ok": True,  "result": "..."}
        {"ok": False, "error": "..."}
    """
    try:
        result = subprocess.run(
            ["osascript", "-", *args],
            input=script,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            err = result.stderr.strip() or "Error desconocido en AppleScript"
            return {"ok": False, "error": err}
        return {"ok": True, "result": result.stdout.strip()}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Timeout: la app tardó demasiado en responder"}
    except FileNotFoundError:
        return {"ok": False, "error": "osascript no encontrado. ¿Estás en macOS?"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ── Envío por plataforma ──────────────────────────────────────────────────────

# AppleScript para Messages: prueba iMessage primero, luego servicio por defecto.
# Ambas ramas aceptan argv — sin interpolación.
_SCRIPT_MESSAGES = """\
on run argv
    set theReceiver to item 1 of argv
    set theMessage  to item 2 of argv
    tell application "Messages"
        try
            set svc to first service whose service type = iMessage
            send theMessage to buddy theReceiver of svc
        on error
            send theMessage to buddy theReceiver
        end try
    end tell
    return "ok"
end run
"""

# AppleScript para WhatsApp via UI scripting.
# Cmd+F abre el buscador; flecha ↓ selecciona el primer resultado.
# Delays adaptativos: polling cada 0.1s en vez de esperas fijas.
_SCRIPT_WHATSAPP = """\
on run argv
    set theReceiver to item 1 of argv
    set theMessage  to item 2 of argv

    tell application "WhatsApp" to activate

    -- Esperar a que la ventana aparezca (máx 1.5s, típico 0.3-0.6s)
    tell application "System Events"
        set waited to 0
        repeat 15 times
            if (count of windows of process "WhatsApp") > 0 then exit repeat
            delay 0.1
            set waited to waited + 1
        end repeat
    end tell

    tell application "System Events"
        tell process "WhatsApp"
            keystroke "f" using command down
            delay 0.4
            keystroke theReceiver
            delay 0.8
            key code 125
            delay 0.3
            keystroke return
            delay 0.6
            keystroke theMessage
            delay 0.15
            keystroke return
        end tell
    end tell
    return "ok"
end run
"""

# AppleScript para Telegram via UI scripting.
# Cmd+K abre la búsqueda global de contactos.
# Delays adaptativos: polling cada 0.1s en vez de esperas fijas.
_SCRIPT_TELEGRAM = """\
on run argv
    set theReceiver to item 1 of argv
    set theMessage  to item 2 of argv

    tell application "Telegram" to activate

    -- Esperar a que la ventana aparezca (máx 1.5s, típico 0.3-0.6s)
    tell application "System Events"
        set waited to 0
        repeat 15 times
            if (count of windows of process "Telegram") > 0 then exit repeat
            delay 0.1
            set waited to waited + 1
        end repeat
    end tell

    tell application "System Events"
        tell process "Telegram"
            keystroke "k" using command down
            delay 0.4
            keystroke theReceiver
            delay 0.8
            key code 125
            delay 0.3
            keystroke return
            delay 0.6
            keystroke theMessage
            delay 0.15
            keystroke return
        end tell
    end tell
    return "ok"
end run
"""


def _is_app_running_or_available(app_name: str) -> bool:
    """
    Comprueba si una app está instalada intentando obtener su ruta con Finder.
    Devuelve True si la app existe (no importa si está abierta o no).
    """
    check = subprocess.run(
        [
            "osascript", "-e",
            f'tell application "Finder" to '
            f'POSIX path of (path to application "{app_name}")',
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return check.returncode == 0


def _send_via_messages(receiver: str, message: str) -> Dict[str, Any]:
    """Envía por Messages.app (iMessage o SMS)."""
    result = _run_applescript(_SCRIPT_MESSAGES, receiver, message, timeout=_TIMEOUT_DIRECT)
    if not result["ok"]:
        err = result["error"]
        # Mensajes de error habituales de Messages.app
        if "Can't get buddy" in err or "не удалось" in err.lower():
            return {
                "ok": False,
                "error": (
                    f"No se encontró el contacto '{receiver}' en Messages. "
                    "Verifica que el número o email es correcto y está en tus contactos."
                ),
            }
        if "not authorized" in err.lower() or "permission" in err.lower():
            return {
                "ok": False,
                "error": (
                    "Sin permiso para controlar Messages. "
                    "Ve a Ajustes → Privacidad → Automatización → Terminal → Messages ✓"
                ),
            }
        return {"ok": False, "error": f"Error en Messages: {err}"}
    return {
        "ok": True,
        "result": f"Mensaje enviado a '{receiver}' por Messages/iMessage.",
    }


def _send_via_whatsapp(receiver: str, message: str) -> Dict[str, Any]:
    """Envía por WhatsApp usando UI scripting."""
    try:
        if not _is_app_running_or_available("WhatsApp"):
            return {"ok": False, "error": "WhatsApp no está instalado en este Mac."}
    except Exception:
        pass  # si falla la comprobación, seguimos e intentamos igualmente

    # WhatsApp puede no soportar newlines via keystroke; los sustituimos por espacio
    message_flat = message.replace("\n", " ")

    result = _run_applescript(_SCRIPT_WHATSAPP, receiver, message_flat, timeout=_TIMEOUT_UI)
    if not result["ok"]:
        err = result["error"]
        if "not authorized" in err.lower() or "accessibility" in err.lower():
            return {
                "ok": False,
                "error": (
                    "Sin permiso de Accesibilidad para controlar WhatsApp. "
                    "Ve a Ajustes → Privacidad → Accesibilidad → Terminal ✓"
                ),
            }
        return {"ok": False, "error": f"Error en WhatsApp: {err}"}
    return {
        "ok": True,
        "result": f"Mensaje enviado a '{receiver}' por WhatsApp.",
    }


def _send_via_telegram(receiver: str, message: str) -> Dict[str, Any]:
    """Envía por Telegram usando UI scripting."""
    try:
        if not _is_app_running_or_available("Telegram"):
            return {"ok": False, "error": "Telegram no está instalado en este Mac."}
    except Exception:
        pass

    message_flat = message.replace("\n", " ")

    result = _run_applescript(_SCRIPT_TELEGRAM, receiver, message_flat, timeout=_TIMEOUT_UI)
    if not result["ok"]:
        err = result["error"]
        if "not authorized" in err.lower() or "accessibility" in err.lower():
            return {
                "ok": False,
                "error": (
                    "Sin permiso de Accesibilidad para controlar Telegram. "
                    "Ve a Ajustes → Privacidad → Accesibilidad → Terminal ✓"
                ),
            }
        return {"ok": False, "error": f"Error en Telegram: {err}"}
    return {
        "ok": True,
        "result": f"Mensaje enviado a '{receiver}' por Telegram.",
    }


# ── Punto de entrada público ──────────────────────────────────────────────────

def run_send_message(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Envía un mensaje de texto vía Messages (iMessage/SMS), WhatsApp o Telegram.

    Args:
        receiver     (str, obligatorio): Nombre del contacto, número de teléfono
                                         (+34612345678) o usuario (@usuario).
        message_text (str, obligatorio): Texto del mensaje a enviar.
        platform     (str, opcional):    "messages" | "whatsapp" | "telegram"
                                         (default: "messages").
                                         Alias aceptados: imessage, sms, wa, tg.

    Returns:
        {"ok": True,  "result": "Mensaje enviado a 'X' por Y."}
        {"ok": False, "error": "Descripción del problema"}
    """
    receiver     = str(args.get("receiver", "")).strip()
    message_text = str(args.get("message_text", "")).strip()
    platform     = str(args.get("platform", "messages")).lower().strip()

    # ── Validación de presencia ───────────────────────────────────────────────
    if not receiver:
        return {"ok": False, "error": "Falta el destinatario (receiver, obligatorio)."}
    if not message_text:
        return {"ok": False, "error": "Falta el texto del mensaje (message_text, obligatorio)."}

    # ── Normalización de plataforma ───────────────────────────────────────────
    platform = _PLATFORM_ALIASES.get(platform, platform)
    if platform not in _PLATFORMS:
        return {
            "ok": False,
            "error": (
                f"Plataforma '{platform}' no soportada. "
                "Usa: messages (o imessage/sms), whatsapp (o wa), telegram (o tg)."
            ),
        }

    # ── Sanitización anti-injection ───────────────────────────────────────────
    receiver     = _sanitize(receiver)
    message_text = _sanitize(message_text)

    if not receiver:
        return {"ok": False, "error": "El destinatario contiene sólo caracteres no válidos."}
    if not message_text:
        return {"ok": False, "error": "El mensaje contiene sólo caracteres no válidos."}

    # ── Dispatch ──────────────────────────────────────────────────────────────
    if platform == "messages":
        return _send_via_messages(receiver, message_text)
    if platform == "whatsapp":
        return _send_via_whatsapp(receiver, message_text)
    # platform == "telegram"
    return _send_via_telegram(receiver, message_text)
