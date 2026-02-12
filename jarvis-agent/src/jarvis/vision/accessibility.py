"""
accessibility.py

API de accesibilidad de macOS para leer contexto de apps.
"""

from __future__ import annotations

from typing import Dict, Any, Optional

try:
    from AppKit import NSWorkspace
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID
    )
    ACCESSIBILITY_AVAILABLE = True
except ImportError:
    ACCESSIBILITY_AVAILABLE = False


def get_active_app() -> Dict[str, Any]:
    """
    Obtiene información de la aplicación activa.
    
    Returns:
        {
            'name': str,
            'bundle_id': str,
            'window_title': str,
            'url': str (si es navegador)
        }
    """
    if not ACCESSIBILITY_AVAILABLE:
        return {
            'name': 'Unknown',
            'bundle_id': '',
            'window_title': '',
            'url': ''
        }
    
    try:
        workspace = NSWorkspace.sharedWorkspace()
        active_app = workspace.activeApplication()
        
        app_name = active_app.get('NSApplicationName', 'Unknown')
        bundle_id = active_app.get('NSApplicationBundleIdentifier', '')
        
        # Obtener título de ventana
        window_title = get_active_window_title()
        
        # Intentar obtener URL si es navegador
        url = ''
        if 'Safari' in app_name or 'Chrome' in app_name or 'Firefox' in app_name:
            url = get_browser_url(app_name)
        
        return {
            'name': app_name,
            'bundle_id': bundle_id,
            'window_title': window_title,
            'url': url
        }
        
    except Exception as e:
        print(f"Error obteniendo app activa: {e}")
        return {
            'name': 'Unknown',
            'bundle_id': '',
            'window_title': '',
            'url': ''
        }


def get_active_window_title() -> str:
    """Obtiene el título de la ventana activa."""
    if not ACCESSIBILITY_AVAILABLE:
        return ''
    
    try:
        window_list = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly,
            kCGNullWindowID
        )
        
        for window in window_list:
            layer = window.get('kCGWindowLayer', 0)
            if layer == 0:  # Ventana normal
                title = window.get('kCGWindowName', '')
                if title:
                    return title
        
        return ''
        
    except Exception as e:
        print(f"Error obteniendo título: {e}")
        return ''


def get_browser_url(browser_name: str) -> str:
    """
    Intenta obtener la URL del navegador activo usando AppleScript.
    
    Args:
        browser_name: Nombre del navegador (Safari, Chrome, etc.)
    
    Returns:
        URL actual o string vacío
    """
    import subprocess
    
    try:
        if 'Safari' in browser_name:
            script = 'tell application "Safari" to get URL of current tab of front window'
        elif 'Chrome' in browser_name:
            script = 'tell application "Google Chrome" to get URL of active tab of front window'
        elif 'Firefox' in browser_name:
            # Firefox no soporta AppleScript tan bien
            return ''
        else:
            return ''
        
        result = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True,
            text=True,
            timeout=2
        )
        
        if result.returncode == 0:
            return result.stdout.strip()
        
        return ''
        
    except Exception:
        return ''


def get_system_context() -> Dict[str, Any]:
    """
    Obtiene contexto completo del sistema.
    
    Returns:
        {
            'active_app': dict,
            'timestamp': str,
            'screen_locked': bool
        }
    """
    import datetime
    
    active_app = get_active_app()
    
    return {
        'active_app': active_app,
        'timestamp': datetime.datetime.now().isoformat(),
        'screen_locked': False  # TODO: detectar si pantalla está bloqueada
    }


def format_context_for_llm(context: Dict[str, Any]) -> str:
    """
    Formatea el contexto en texto legible para el LLM.
    
    Args:
        context: Diccionario de contexto del sistema
    
    Returns:
        String formateado para incluir en el prompt
    """
    app = context.get('active_app', {})
    app_name = app.get('name', 'Unknown')
    window_title = app.get('window_title', '')
    url = app.get('url', '')
    
    parts = [f"Aplicación activa: {app_name}"]
    
    if window_title:
        parts.append(f"Ventana: {window_title}")
    
    if url:
        parts.append(f"URL: {url}")
    
    return " | ".join(parts)
