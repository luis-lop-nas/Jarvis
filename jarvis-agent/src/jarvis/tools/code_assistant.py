"""
code_assistant.py

Asistente de programación que genera y edita código.
Se integra con VS Code.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional


def code_assistant(
    task: str = "",
    language: str = "python",
    file_path: str = "",
    open_vscode: bool = True,
    workspace: str = "data/workspace"
) -> Dict[str, Any]:
    """
    Genera código según la tarea especificada.
    
    Args:
        task: Descripción de lo que debe programar (obligatorio)
            Ejemplos:
            - "Crea una API REST con FastAPI para gestionar usuarios"
            - "Programa un web scraper que extraiga noticias de ElPais"
            - "Haz un script que analice archivos CSV y genere gráficos"
        language: Lenguaje de programación (python, javascript, typescript, etc.)
        file_path: Ruta del archivo a crear/editar (relativa a workspace)
            Si no se especifica, se genera automáticamente según la tarea
        open_vscode: Si debe abrir VS Code automáticamente (default True)
        workspace: Directorio de trabajo
    
    Returns:
        Dict con ok, result, file_path, code
    """
    task = (task or "").strip()
    language = (language or "python").lower().strip()
    
    if not task:
        return {
            "ok": False,
            "error": "Necesito una descripción de lo que debo programar"
        }
    
    # Obtener API key de Groq para generar el código
    api_key = os.getenv("GROQ_API_KEY", "")
    
    if not api_key:
        return {
            "ok": False,
            "error": "Falta GROQ_API_KEY para generar código"
        }
    
    try:
        from groq import Groq
        
        client = Groq(api_key=api_key)
        
        # Construir prompt para generar código
        prompt = f"""Eres un programador experto. Tu tarea es escribir código limpio, funcional y bien documentado.

Lenguaje: {language}
Tarea: {task}

INSTRUCCIONES:
1. Escribe código completo y funcional
2. Incluye comentarios explicativos
3. Sigue las mejores prácticas del lenguaje
4. Si necesitas múltiples archivos, genera solo el principal y menciona qué otros archivos se necesitarían
5. NO incluyas explicaciones antes o después del código, SOLO código

Genera el código ahora:"""
        
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "user", "content": prompt}
            ],
            max_tokens=4000,
            temperature=0.3,  # Más determinista para código
        )
        
        generated_code = response.choices[0].message.content.strip()
        
        # Limpiar bloques de markdown si los hay
        if generated_code.startswith("```"):
            lines = generated_code.split("\n")
            # Quitar primera línea (```python o similar)
            if lines[0].startswith("```"):
                lines = lines[1:]
            # Quitar última línea (```)
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            generated_code = "\n".join(lines)
        
        # Determinar ruta del archivo
        if not file_path:
            # Generar nombre de archivo automáticamente
            extensions = {
                "python": "py",
                "javascript": "js",
                "typescript": "ts",
                "java": "java",
                "cpp": "cpp",
                "c": "c",
                "rust": "rs",
                "go": "go",
                "ruby": "rb",
                "php": "php",
            }
            ext = extensions.get(language, "txt")
            
            # Crear nombre basado en la tarea (simplificado)
            safe_name = task.lower()[:30].replace(" ", "_")
            safe_name = "".join(c for c in safe_name if c.isalnum() or c == "_")
            file_path = f"{safe_name}.{ext}"
        
        # Crear ruta completa
        workspace_path = Path(workspace).expanduser().resolve()
        workspace_path.mkdir(parents=True, exist_ok=True)
        
        full_path = workspace_path / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Guardar código
        full_path.write_text(generated_code, encoding="utf-8")
        
        result = f"✅ Código generado y guardado en: {full_path}"
        
        # Abrir en VS Code si se solicita
        if open_vscode:
            try:
                # Intentar abrir con 'code' command
                subprocess.run(
                    ["code", str(full_path)],
                    timeout=5,
                    capture_output=True
                )
                result += "\n📝 Abierto en VS Code"
            except FileNotFoundError:
                # Si 'code' no está instalado, abrir con 'open'
                try:
                    subprocess.run(
                        ["open", "-a", "Visual Studio Code", str(full_path)],
                        timeout=5,
                        capture_output=True
                    )
                    result += "\n📝 Abierto en VS Code"
                except:
                    result += "\n⚠️ No se pudo abrir VS Code automáticamente"
        
        return {
            "ok": True,
            "result": result,
            "file_path": str(full_path),
            "code": generated_code,
            "language": language
        }
        
    except Exception as e:
        return {
            "ok": False,
            "error": f"Error generando código: {str(e)}"
        }


def edit_code(
    file_path: str,
    instruction: str,
    workspace: str = "data/workspace"
) -> Dict[str, Any]:
    """
    Edita un archivo de código existente según instrucciones.
    
    Args:
        file_path: Ruta del archivo a editar
        instruction: Instrucción de qué modificar
        workspace: Directorio de trabajo
    
    Returns:
        Dict con ok, result, code
    """
    file_path = (file_path or "").strip()
    instruction = (instruction or "").strip()
    
    if not file_path or not instruction:
        return {
            "ok": False,
            "error": "Necesito la ruta del archivo y la instrucción de edición"
        }
    
    workspace_path = Path(workspace).expanduser().resolve()
    full_path = workspace_path / file_path
    
    if not full_path.exists():
        return {
            "ok": False,
            "error": f"El archivo {file_path} no existe"
        }
    
    # Leer código actual
    try:
        current_code = full_path.read_text(encoding="utf-8")
    except Exception as e:
        return {
            "ok": False,
            "error": f"No se pudo leer el archivo: {e}"
        }
    
    # Obtener API key
    api_key = os.getenv("GROQ_API_KEY", "")
    
    if not api_key:
        return {
            "ok": False,
            "error": "Falta GROQ_API_KEY"
        }
    
    try:
        from groq import Groq
        
        client = Groq(api_key=api_key)
        
        prompt = f"""Eres un programador experto. Debes editar el siguiente código según la instrucción.

CÓDIGO ACTUAL:
```
{current_code}
```

INSTRUCCIÓN: {instruction}

REGLAS:
1. Mantén la estructura y estilo del código original
2. Solo modifica lo necesario según la instrucción
3. Devuelve el código completo modificado
4. NO incluyas explicaciones, SOLO el código

Código modificado:"""
        
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "user", "content": prompt}
            ],
            max_tokens=4000,
            temperature=0.3,
        )
        
        modified_code = response.choices[0].message.content.strip()
        
        # Limpiar markdown
        if modified_code.startswith("```"):
            lines = modified_code.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            modified_code = "\n".join(lines)
        
        # Guardar código modificado
        full_path.write_text(modified_code, encoding="utf-8")
        
        return {
            "ok": True,
            "result": f"✅ Archivo {file_path} modificado correctamente",
            "code": modified_code
        }
        
    except Exception as e:
        return {
            "ok": False,
            "error": f"Error editando código: {e}"
        }
