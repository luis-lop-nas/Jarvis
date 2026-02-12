"""
vision.py

Herramienta de visión para Jarvis.
Combina capturas de pantalla + Accessibility API + análisis con Groq Vision.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from jarvis.vision.screenshot import capture_screen, capture_active_window
from jarvis.vision.accessibility import get_system_context, format_context_for_llm
from jarvis.vision.vision_analyzer import (
    describe_screen,
    answer_about_screen,
    read_text_from_screen
)


def vision_command(
    action: str = "describe",
    question: str = "",
    capture_mode: str = "full"
) -> Dict[str, Any]:
    """
    Ejecuta comandos de visión.
    
    Args:
        action: Acción a realizar
            - "describe" - Describe qué hay en pantalla
            - "answer" - Responde pregunta sobre pantalla (requiere question)
            - "read" - Lee todo el texto en pantalla (OCR)
            - "context" - Solo obtiene contexto (app activa, URL, etc.)
        question: Pregunta sobre la pantalla (para action="answer")
        capture_mode: "full" (pantalla completa) o "window" (ventana activa)
    
    Returns:
        Dict con ok, result o error
    """
    action = (action or "describe").lower().strip()
    capture_mode = (capture_mode or "full").lower().strip()
    
    # Obtener API key de Groq
    api_key = os.getenv("GROQ_API_KEY", "")
    
    if not api_key and action != "context":
        return {
            "ok": False,
            "error": "Falta GROQ_API_KEY para análisis de visión"
        }
    
    try:
        # Obtener contexto del sistema
        context = get_system_context()
        context_str = format_context_for_llm(context)
        
        # Si solo quiere contexto
        if action == "context":
            app = context['active_app']
            result = f"Aplicación activa: {app['name']}"
            if app['window_title']:
                result += f"\nVentana: {app['window_title']}"
            if app['url']:
                result += f"\nURL: {app['url']}"
            
            return {
                "ok": True,
                "result": result,
                "context": context
            }
        
        # Capturar pantalla
        if capture_mode == "window":
            _, img_base64 = capture_active_window()
        else:
            _, img_base64 = capture_screen()
        
        if not img_base64:
            return {
                "ok": False,
                "error": "No se pudo capturar la pantalla"
            }
        
        # Ejecutar acción
        if action == "describe":
            description = describe_screen(img_base64, api_key, context_str)
            return {
                "ok": True,
                "result": description,
                "context": context
            }
        
        elif action == "answer":
            if not question:
                return {
                    "ok": False,
                    "error": "Se necesita una pregunta para action='answer'"
                }
            
            answer = answer_about_screen(img_base64, question, api_key, context_str)
            return {
                "ok": True,
                "result": answer,
                "context": context
            }
        
        elif action == "read":
            text = read_text_from_screen(img_base64, api_key)
            return {
                "ok": True,
                "result": text,
                "context": context
            }
        
        else:
            return {
                "ok": False,
                "error": f"Acción desconocida: {action}. Usa: describe, answer, read, context"
            }
        
    except Exception as e:
        return {
            "ok": False,
            "error": f"Error en visión: {str(e)}"
        }
