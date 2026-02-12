"""
spotify.py

Control de Spotify en macOS usando AppleScript.
"""

from __future__ import annotations

import subprocess
from typing import Any, Dict


def spotify_control(action: str = "status") -> Dict[str, Any]:
    """
    Controla Spotify en macOS.
    
    Args:
        action: Acción a realizar
            - "play" / "pause" / "playpause"
            - "next" / "previous"
            - "status" (devuelve qué está sonando)
            - "volume_up" / "volume_down"
    
    Returns:
        Dict con ok, result o error
    """
    action = (action or "status").lower().strip()
    
    try:
        if action == "status":
            # Obtener estado actual
            script = '''
            tell application "Spotify"
                if player state is playing then
                    set trackName to name of current track
                    set artistName to artist of current track
                    set albumName to album of current track
                    return "▶️ Sonando: " & trackName & " - " & artistName & " (" & albumName & ")"
                else if player state is paused then
                    return "⏸️ Pausado"
                else
                    return "⏹️ Detenido"
                end if
            end tell
            '''
        
        elif action in ["play", "pause", "playpause"]:
            script = 'tell application "Spotify" to playpause'
        
        elif action == "next":
            script = 'tell application "Spotify" to next track'
        
        elif action == "previous":
            script = 'tell application "Spotify" to previous track'
        
        elif action == "volume_up":
            script = '''
            tell application "Spotify"
                set sound volume to (sound volume + 10)
                return "🔊 Volumen: " & sound volume
            end tell
            '''
        
        elif action == "volume_down":
            script = '''
            tell application "Spotify"
                set sound volume to (sound volume - 10)
                return "🔉 Volumen: " & sound volume
            end tell
            '''
        
        else:
            return {
                "ok": False,
                "error": f"Acción desconocida: {action}. Usa: play, pause, next, previous, status, volume_up, volume_down"
            }
        
        # Ejecutar AppleScript
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        if result.returncode != 0:
            # Spotify no está abierto probablemente
            if "Spotify got an error" in result.stderr or "not running" in result.stderr:
                return {
                    "ok": False,
                    "error": "Spotify no está abierto. Abre Spotify primero."
                }
            
            return {
                "ok": False,
                "error": result.stderr.strip() or "Error ejecutando AppleScript"
            }
        
        output = result.stdout.strip()
        return {
            "ok": True,
            "result": output or f"Acción '{action}' ejecutada"
        }
    
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Timeout ejecutando comando de Spotify"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
