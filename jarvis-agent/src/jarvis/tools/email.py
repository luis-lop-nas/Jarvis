"""
email.py

Envío de emails usando la app Mail de macOS.
"""

from __future__ import annotations

import subprocess
from typing import Any, Dict


def send_email(
    to: str = "",
    subject: str = "",
    body: str = "",
    action: str = "send"
) -> Dict[str, Any]:
    """
    Envía emails usando Mail.app de macOS.
    
    Args:
        to: Destinatario (email)
        subject: Asunto del email
        body: Cuerpo del mensaje
        action: "send" para enviar, "draft" para crear borrador
    
    Returns:
        Dict con ok, result o error
    """
    to = (to or "").strip()
    subject = (subject or "").strip()
    body = (body or "").strip()
    action = (action or "send").lower().strip()
    
    if not to:
        return {
            "ok": False,
            "error": "Necesito un destinatario (email)"
        }
    
    if not subject:
        return {
            "ok": False,
            "error": "Necesito un asunto para el email"
        }
    
    try:
        # Escapar comillas en el texto
        to_safe = to.replace('"', '\\"')
        subject_safe = subject.replace('"', '\\"')
        body_safe = body.replace('"', '\\"')
        
        if action == "send":
            # Crear y enviar email
            script = f'''
            tell application "Mail"
                set newMessage to make new outgoing message with properties {{subject:"{subject_safe}", content:"{body_safe}", visible:false}}
                tell newMessage
                    make new to recipient with properties {{address:"{to_safe}"}}
                    send
                end tell
            end tell
            return "✅ Email enviado a {to_safe}"
            '''
        
        elif action == "draft":
            # Crear borrador (no enviar)
            script = f'''
            tell application "Mail"
                set newMessage to make new outgoing message with properties {{subject:"{subject_safe}", content:"{body_safe}", visible:true}}
                tell newMessage
                    make new to recipient with properties {{address:"{to_safe}"}}
                end tell
            end tell
            return "✅ Borrador creado (revisa Mail.app)"
            '''
        
        else:
            return {
                "ok": False,
                "error": f"Acción desconocida: {action}. Usa: send o draft"
            }
        
        # Ejecutar AppleScript
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=15,
        )
        
        if result.returncode != 0:
            return {
                "ok": False,
                "error": result.stderr.strip() or "Error enviando email"
            }
        
        output = result.stdout.strip()
        return {
            "ok": True,
            "result": output or "Email procesado"
        }
    
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Timeout enviando email"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
