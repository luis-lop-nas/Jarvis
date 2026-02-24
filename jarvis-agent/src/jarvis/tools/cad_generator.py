"""
cad_generator.py

Tool: cad_generator
Genera modelos 3D paramétricos a partir de descripciones en lenguaje natural.

Flujo (acción 'create'):
  1. LLM convierte la descripción → código build123d
  2. Validación de seguridad vía AST (bloquea imports/llamadas peligrosas)
  3. Ejecución en un subproceso aislado con sys.executable
  4. Reintentos automáticos (hasta 3) enviando el error de compilación de vuelta al LLM
  5. El STL resultante se guarda en ~/Documents/Jarvis/models/
  6. Contexto de sesión persistente para iteraciones

Acciones disponibles:
  create         — Genera o itera un modelo 3D (acción por defecto)
  list           — Lista modelos STL existentes y sesiones guardadas
  open           — Abre un STL en el visor por defecto de macOS
  delete_session — Elimina una sesión del historial

Instalación:
    pip install build123d          # build123d con OpenCASCADE

Uso desde JARVIS:
    "Crea un cubo de 50mm con un agujero central de 10mm de radio"
    "Hazlo más alto, que mida 80mm"   ← usa el session_id devuelto antes
    "Lista mis modelos 3D"
    "Abre el último modelo que generé"
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

_MODELS_DIR   = Path.home() / "Documents" / "Jarvis" / "models"
_SESSION_FILE = _MODELS_DIR / ".cad_sessions.json"
_TEMP_SCRIPT  = _MODELS_DIR / "_jarvis_cad_temp.py"

_MAX_RETRIES  = 3
_EXEC_TIMEOUT = 120   # segundos máximos de ejecución build123d

# Módulos permitidos en el código generado
_ALLOWED_IMPORTS = frozenset({"build123d", "math"})

# Funciones Python peligrosas que nunca debe usar el código generado
_BLOCKED_CALLS = frozenset({"eval", "exec", "compile", "__import__", "breakpoint"})

# Módulos peligrosos que no deben referenciarse
_BLOCKED_MODULES = frozenset({
    "os", "sys", "subprocess", "socket", "shutil", "pathlib",
    "tempfile", "io", "importlib", "pickle", "ctypes", "cffi",
    "requests", "urllib", "http", "ftplib", "smtplib",
})

# ---------------------------------------------------------------------------
# Prompt del sistema para el LLM
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert 3D CAD developer using the build123d Python library (v0.7+).
Your task is to generate Python code that creates a 3D solid matching the user's description.

ABSOLUTE RULES:
1. Start with: from build123d import *
2. You may also: import math  (nothing else)
3. Never redefine OUTPUT_STL — it is pre-injected by the system
4. Assign the final solid to a variable named: result_part
5. End with exactly: export_stl(result_part, OUTPUT_STL)
6. All dimensions in millimeters
7. Fillet/chamfer radius ≤ 2 mm to avoid geometry failures
8. Output ONLY a ```python ... ``` block — no prose outside

BOOLEAN OPERATIONS:
- Add material:      Box(…) / Cylinder(…) / Sphere(…)  (default mode=Mode.ADD)
- Remove material:   Box(…, mode=Mode.SUBTRACT) or Hole(radius, depth)
- Intersect:         Box(…, mode=Mode.INTERSECT)

VERIFIED PATTERNS:

```python
# ── Simple box ─────────────────────────────────────────────────────────────
from build123d import *
with BuildPart() as model:
    Box(50, 50, 20)
result_part = model.part
export_stl(result_part, OUTPUT_STL)
```

```python
# ── Box with central through-hole ──────────────────────────────────────────
from build123d import *
with BuildPart() as model:
    Box(50, 50, 20)
    with Locations((0, 0, 0)):
        Hole(radius=8, depth=20)
result_part = model.part
export_stl(result_part, OUTPUT_STL)
```

```python
# ── Cylinder ───────────────────────────────────────────────────────────────
from build123d import *
with BuildPart() as model:
    Cylinder(radius=25, height=40)
result_part = model.part
export_stl(result_part, OUTPUT_STL)
```

```python
# ── Hollow cylinder (pipe) ─────────────────────────────────────────────────
from build123d import *
with BuildPart() as model:
    Cylinder(radius=20, height=60)
    Cylinder(radius=15, height=60, mode=Mode.SUBTRACT)
result_part = model.part
export_stl(result_part, OUTPUT_STL)
```

```python
# ── Ring / washer ──────────────────────────────────────────────────────────
from build123d import *
with BuildPart() as model:
    Cylinder(radius=25, height=6)
    Cylinder(radius=16, height=6, mode=Mode.SUBTRACT)
result_part = model.part
export_stl(result_part, OUTPUT_STL)
```

```python
# ── Box with rounded edges (all) ───────────────────────────────────────────
from build123d import *
with BuildPart() as model:
    Box(60, 40, 30)
    fillet(model.edges(), radius=2)
result_part = model.part
export_stl(result_part, OUTPUT_STL)
```

```python
# ── Box with top-edge fillet only ──────────────────────────────────────────
from build123d import *
with BuildPart() as model:
    Box(60, 40, 25)
    fillet(model.edges().filter_by(Axis.Z), radius=2)
result_part = model.part
export_stl(result_part, OUTPUT_STL)
```

```python
# ── Grid of holes ──────────────────────────────────────────────────────────
from build123d import *
with BuildPart() as model:
    Box(80, 80, 10)
    with GridLocations(20, 20, 3, 3):
        Hole(radius=4, depth=10)
result_part = model.part
export_stl(result_part, OUTPUT_STL)
```

```python
# ── Polar holes in a disc ──────────────────────────────────────────────────
from build123d import *
with BuildPart() as model:
    Cylinder(radius=40, height=10)
    with PolarLocations(25, 6):
        Hole(radius=4, depth=10)
result_part = model.part
export_stl(result_part, OUTPUT_STL)
```

```python
# ── Sphere ─────────────────────────────────────────────────────────────────
from build123d import *
with BuildPart() as model:
    Sphere(radius=30)
result_part = model.part
export_stl(result_part, OUTPUT_STL)
```

```python
# ── Torus ──────────────────────────────────────────────────────────────────
from build123d import *
with BuildPart() as model:
    Torus(major_radius=30, minor_radius=8)
result_part = model.part
export_stl(result_part, OUTPUT_STL)
```

```python
# ── Cone ───────────────────────────────────────────────────────────────────
from build123d import *
with BuildPart() as model:
    Cone(bottom_radius=25, top_radius=5, height=50)
result_part = model.part
export_stl(result_part, OUTPUT_STL)
```

```python
# ── Pyramid (sharp cone) ───────────────────────────────────────────────────
from build123d import *
with BuildPart() as model:
    Cone(bottom_radius=30, top_radius=0, height=50)
result_part = model.part
export_stl(result_part, OUTPUT_STL)
```

```python
# ── Box with chamfered edge ────────────────────────────────────────────────
from build123d import *
with BuildPart() as model:
    Box(60, 60, 30)
    chamfer(model.edges().filter_by(Axis.Z)[-1:], length=2)
result_part = model.part
export_stl(result_part, OUTPUT_STL)
```

```python
# ── Union of box and cylinder ──────────────────────────────────────────────
from build123d import *
with BuildPart() as model:
    Box(60, 60, 10)
    with Locations((0, 0, 10)):
        Cylinder(radius=20, height=40)
result_part = model.part
export_stl(result_part, OUTPUT_STL)
```

```python
# ── Box with cylindrical pocket (blind hole) ───────────────────────────────
from build123d import *
with BuildPart() as model:
    Box(60, 60, 30)
    with Locations((0, 0, 0)):
        Cylinder(radius=20, height=20, mode=Mode.SUBTRACT)
result_part = model.part
export_stl(result_part, OUTPUT_STL)
```

```python
# ── Two cylinders stacked (stepped pin) ────────────────────────────────────
from build123d import *
with BuildPart() as model:
    Cylinder(radius=15, height=10)
    with Locations((0, 0, 10)):
        Cylinder(radius=8, height=30)
result_part = model.part
export_stl(result_part, OUTPUT_STL)
```
"""

_ITERATION_PROMPT = """\
Below is the current build123d Python code for the model.
Apply the user's modification request while keeping the overall structure.
Follow the same rules as before. Output ONLY the modified ```python ... ``` block.

CURRENT CODE:
```python
{existing_code}
```

MODIFICATION REQUEST: {description}
"""

# ---------------------------------------------------------------------------
# Detección del LLM disponible
# ---------------------------------------------------------------------------

def _detect_llm() -> Optional[Dict]:
    """Devuelve config del mejor LLM disponible. Prioridad: Claude > Groq > Gemini."""
    # Claude (activo explícitamente)
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if key and os.getenv("USE_CLAUDE", "false").lower() == "true":
        return {"provider": "claude", "api_key": key,
                "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")}
    # Groq (activo explícitamente)
    key = os.getenv("GROQ_API_KEY", "").strip()
    if key and os.getenv("USE_GROQ", "false").lower() == "true":
        return {"provider": "groq", "api_key": key,
                "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")}
    # Gemini (activo explícitamente)
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if key and os.getenv("USE_GEMINI", "false").lower() == "true":
        return {"provider": "gemini", "api_key": key,
                "model": os.getenv("GEMINI_MODEL", "gemini-2.0-flash")}
    # Fallback: cualquier key disponible (en orden de preferencia)
    if (k := os.getenv("ANTHROPIC_API_KEY", "").strip()):
        return {"provider": "claude", "api_key": k, "model": "claude-sonnet-4-6"}
    if (k := os.getenv("GROQ_API_KEY", "").strip()):
        return {"provider": "groq", "api_key": k, "model": "llama-3.3-70b-versatile"}
    if (k := os.getenv("GEMINI_API_KEY", "").strip()):
        return {"provider": "gemini", "api_key": k, "model": "gemini-2.0-flash"}
    return None


def _call_llm(system: str, user: str, llm: Dict) -> str:
    """Llama al LLM y devuelve el texto de respuesta."""
    provider = llm["provider"]
    api_key  = llm["api_key"]
    model    = llm["model"]

    if provider == "claude":
        from anthropic import Anthropic  # type: ignore
        client = Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text

    elif provider == "groq":
        import requests  # type: ignore
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json={"model": model,
                  "messages": [{"role": "system", "content": system},
                                {"role": "user",   "content": user}],
                  "temperature": 0.2,
                  "max_tokens": 2048},
            timeout=45,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    elif provider == "gemini":
        import requests  # type: ignore
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048},
        }
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent?key={api_key}")
        resp = requests.post(url, json=payload, timeout=45)
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]

    raise ValueError(f"Proveedor LLM desconocido: {provider}")


# ---------------------------------------------------------------------------
# Extracción y validación de código
# ---------------------------------------------------------------------------

_CODE_BLOCK_RE = re.compile(
    r"```(?:python)?\s*\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)


def extract_code(text: str) -> Optional[str]:
    """
    Extrae el bloque de código Python de la respuesta del LLM.
    Devuelve el bloque más largo encontrado (```python…``` o ```…```), o None.
    """
    matches = _CODE_BLOCK_RE.findall(text)
    if not matches:
        return None
    return max(matches, key=len).strip()


def validate_code(code: str) -> Tuple[bool, str]:
    """
    Valida el código CAD generado vía análisis AST.

    Comprueba:
    - Sintaxis Python válida
    - Solo imports de build123d y math
    - Sin llamadas a funciones peligrosas (eval, exec, __import__…)
    - Sin referencias directas a módulos del sistema (os, sys, subprocess…)
    - Presencia de 'result_part' y 'export_stl'

    Returns:
        (is_safe: bool, reason: str)
    """
    if not code or not code.strip():
        return False, "Código vacío"

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"Error de sintaxis: {e}"

    for node in ast.walk(tree):
        # ── Imports ──────────────────────────────────────────────────────────
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top not in _ALLOWED_IMPORTS:
                    return False, (
                        f"Import no permitido: '{alias.name}'. "
                        "Solo se permiten build123d y math."
                    )

        if isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                if top not in _ALLOWED_IMPORTS:
                    return False, (
                        f"Import no permitido: '{node.module}'. "
                        "Solo se permiten build123d y math."
                    )

        # ── Llamadas peligrosas ───────────────────────────────────────────────
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in _BLOCKED_CALLS:
                    return False, f"Función peligrosa bloqueada: {node.func.id}()"

            if isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name):
                    if node.func.value.id in _BLOCKED_MODULES:
                        return False, (
                            f"Acceso a módulo peligroso bloqueado: "
                            f"{node.func.value.id}.{node.func.attr}()"
                        )

    # ── Presencia de elementos obligatorios ──────────────────────────────────
    if "result_part" not in code:
        return False, "El código debe asignar el modelo a 'result_part'"

    if "export_stl" not in code:
        return False, "El código debe llamar a export_stl(result_part, OUTPUT_STL)"

    return True, "ok"


def inject_output_path(code: str, output_path: Path) -> str:
    """
    Prepend la definición de OUTPUT_STL al código generado.
    Usa forward-slashes (posix) para evitar problemas en cualquier plataforma.
    """
    header = f"OUTPUT_STL = {output_path.as_posix()!r}\n\n"
    return header + code


# ---------------------------------------------------------------------------
# Ejecución local del código CAD
# ---------------------------------------------------------------------------

def execute_cad_code(code: str, output_path: Path, timeout: int = _EXEC_TIMEOUT) -> Tuple[bool, str]:
    """
    Ejecuta el código build123d en un subproceso aislado (sys.executable).

    Args:
        code:        Código Python completo (ya incluye OUTPUT_STL = …).
        output_path: Ruta donde se espera el STL resultante.
        timeout:     Timeout en segundos (default 120).

    Returns:
        (success: bool, message: str)
        success=True  → message es stdout del script.
        success=False → message es stderr/descripción del error.
    """
    _MODELS_DIR.mkdir(parents=True, exist_ok=True)

    script = _TEMP_SCRIPT
    try:
        script.write_text(code, encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(_MODELS_DIR),
        )

        if result.returncode != 0:
            err = (result.stderr or result.stdout or "Sin salida de error").strip()
            # Recortar trazas largas de OCC para que el LLM pueda digerirlas
            if len(err) > 2000:
                err = err[-2000:]
            return False, err

        if not output_path.exists():
            return False, (
                f"El script terminó sin error pero no creó el STL en: {output_path}. "
                f"Stdout: {result.stdout[:500]}"
            )

        return True, result.stdout.strip()

    except subprocess.TimeoutExpired:
        return False, f"Timeout: la ejecución superó {timeout}s"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    finally:
        try:
            script.unlink(missing_ok=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Nombres de archivo y sesiones
# ---------------------------------------------------------------------------

def make_output_path(description: str, name: Optional[str] = None) -> Path:
    """
    Genera una ruta STL única basada en description (o name si se proporciona)
    más un timestamp para garantizar unicidad.
    """
    _MODELS_DIR.mkdir(parents=True, exist_ok=True)
    base = name if name else description
    safe = re.sub(r"[^\w\s-]", "", base.lower())
    safe = re.sub(r"[\s-]+", "_", safe).strip("_")[:40]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return _MODELS_DIR / f"{safe}_{timestamp}.stl"


def load_session(session_id: str) -> Optional[Dict]:
    """Carga una sesión CAD persistida. Devuelve None si no existe."""
    if not _SESSION_FILE.exists():
        return None
    try:
        data = json.loads(_SESSION_FILE.read_text(encoding="utf-8"))
        return data.get("sessions", {}).get(session_id)
    except Exception:
        return None


def save_session(session_id: str, session_data: Dict) -> None:
    """Persiste o actualiza una sesión CAD en el JSON de sesiones."""
    _MODELS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if _SESSION_FILE.exists():
            try:
                store = json.loads(_SESSION_FILE.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                store = {"sessions": {}}
        else:
            store = {"sessions": {}}

        store["sessions"][session_id] = session_data
        _SESSION_FILE.write_text(
            json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        print(f"[CadGenerator] No se pudo guardar la sesión: {e}")


def _load_all_sessions() -> Dict[str, Any]:
    """Devuelve el dict de sesiones completo (vacío si no existe o está corrupto)."""
    if not _SESSION_FILE.exists():
        return {}
    try:
        return json.loads(_SESSION_FILE.read_text(encoding="utf-8")).get("sessions", {})
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Ciclo de generación con reintentos
# ---------------------------------------------------------------------------

def _generate_with_retries(
    description: str,
    existing_code: Optional[str],
    output_path: Path,
    llm: Dict,
    max_retries: int = _MAX_RETRIES,
) -> Tuple[bool, str, str, int]:
    """
    Intenta generar y ejecutar código CAD hasta max_retries veces.
    En cada fallo reenvía el error al LLM para que lo corrija.

    Returns:
        (success, final_code, error_message, attempts_used)
    """
    last_error: str = ""
    last_code:  str = ""

    for attempt in range(1, max_retries + 1):
        print(f"[CadGenerator] Intento {attempt}/{max_retries}")

        # ── Construir prompt ──────────────────────────────────────────────────
        if existing_code:
            user_prompt = _ITERATION_PROMPT.format(
                existing_code=existing_code,
                description=description,
            )
            if last_error:
                user_prompt += (
                    f"\n\nNOTA: El intento anterior falló con este error:\n"
                    f"```\n{last_error}\n```\n"
                    "Por favor corrige el problema."
                )
        else:
            user_prompt = f"Create a 3D model: {description}"
            if last_error:
                user_prompt += (
                    f"\n\nNOTA: El intento anterior falló con este error:\n"
                    f"```\n{last_error}\n```\n"
                    "Por favor corrige el problema."
                )

        # ── Llamar al LLM ─────────────────────────────────────────────────────
        try:
            raw_response = _call_llm(_SYSTEM_PROMPT, user_prompt, llm)
        except Exception as e:
            last_error = f"Error LLM: {e}"
            continue

        # ── Extraer código ────────────────────────────────────────────────────
        code = extract_code(raw_response)
        if not code:
            last_error = "El LLM no devolvió un bloque de código Python."
            continue

        last_code = code

        # ── Validar código ────────────────────────────────────────────────────
        valid, reason = validate_code(code)
        if not valid:
            last_error = f"Validación de seguridad fallida: {reason}"
            existing_code = None  # Regenerar desde cero si hay violación de seguridad
            continue

        # ── Inyectar OUTPUT_STL + ejecutar ────────────────────────────────────
        full_code = inject_output_path(code, output_path)
        success, msg = execute_cad_code(full_code, output_path)

        if success:
            return True, code, "", attempt

        last_error = msg
        if existing_code:
            existing_code = code  # el LLM intentará corregir su propia versión

    return False, last_code, last_error, max_retries


# ---------------------------------------------------------------------------
# Acciones individuales
# ---------------------------------------------------------------------------

def _action_create(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Genera un nuevo modelo 3D o itera sobre uno existente (via session_id).

    Args:
        description (str): Descripción en lenguaje natural. (obligatorio)
        session_id  (str): ID de sesión para iterar sobre un modelo previo. (opcional)
        model_name  (str): Nombre base para el fichero STL. (opcional)
        max_retries (int): Intentos máximos de generación. (default 3)
        open_viewer (bool): Abrir el STL en el visor tras generarlo. (default False)

    Returns:
        {ok, stl_path, description, session_id, code, attempts, model_size_kb, llm_provider}
    """
    description = str(args.get("description", "")).strip()
    if not description:
        return {"ok": False, "error": "Falta args['description']: descripción del modelo 3D."}

    session_id  = str(args.get("session_id", "")).strip() or str(uuid.uuid4())
    model_name  = str(args.get("model_name", "")).strip() or None
    max_retries = int(args.get("max_retries", _MAX_RETRIES))
    open_viewer = bool(args.get("open_viewer", False))

    # ── Detectar LLM ──────────────────────────────────────────────────────────
    llm = _detect_llm()
    if not llm:
        return {
            "ok": False,
            "error": (
                "No hay LLM configurado. "
                "Configura ANTHROPIC_API_KEY, GROQ_API_KEY o GEMINI_API_KEY en .env."
            ),
        }

    # ── Cargar sesión anterior (iteración) ────────────────────────────────────
    session = load_session(session_id)
    existing_code: Optional[str] = session.get("code") if session else None
    if existing_code:
        print(f"[CadGenerator] Iterando sobre sesión '{session_id[:8]}…'")
    else:
        print(f"[CadGenerator] Nueva sesión '{session_id[:8]}…'")

    # ── Ruta de salida ────────────────────────────────────────────────────────
    output_path = make_output_path(description, name=model_name)
    print(f"[CadGenerator] Descripción: {description!r}")
    print(f"[CadGenerator] Salida STL:  {output_path}")

    # ── Generar con reintentos ────────────────────────────────────────────────
    success, final_code, error, attempts = _generate_with_retries(
        description=description,
        existing_code=existing_code,
        output_path=output_path,
        llm=llm,
        max_retries=max_retries,
    )

    if not success:
        return {
            "ok": False,
            "error": (
                f"No se pudo generar el modelo tras {attempts} intento(s). "
                f"Último error: {error}"
            ),
            "code": final_code,
            "attempts": attempts,
            "session_id": session_id,
        }

    # ── Persistir sesión ──────────────────────────────────────────────────────
    now = datetime.now().isoformat()
    session_data = {
        "description": description,
        "code": final_code,
        "stl_path": str(output_path),
        "model_name": model_name or "",
        "updated_at": now,
        "created_at": session.get("created_at", now) if session else now,
        "iterations": (session.get("iterations", 0) if session else 0) + 1,
    }
    save_session(session_id, session_data)

    # ── Tamaño del archivo ────────────────────────────────────────────────────
    size_kb = output_path.stat().st_size / 1024
    print(f"[CadGenerator] ✓ STL generado: {output_path} ({size_kb:.1f} KB)")

    # ── Abrir en visor (opcional) ─────────────────────────────────────────────
    if open_viewer:
        try:
            subprocess.Popen(["open", str(output_path)])
        except Exception as e:
            print(f"[CadGenerator] No se pudo abrir el visor: {e}")

    return {
        "ok": True,
        "stl_path": str(output_path),
        "description": description,
        "session_id": session_id,
        "code": final_code,
        "attempts": attempts,
        "model_size_kb": round(size_kb, 2),
        "llm_provider": llm["provider"],
    }


def _action_list(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Lista los modelos STL existentes y las sesiones guardadas.

    Returns:
        {ok, models: [{filename, path, size_kb, modified}],
             sessions: [{session_id, description, iterations, updated_at, stl_path}],
             models_count, sessions_count, directory}
    """
    _MODELS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Ficheros STL ──────────────────────────────────────────────────────────
    stl_files = sorted(
        _MODELS_DIR.glob("*.stl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    models: List[Dict] = []
    for stl in stl_files:
        stat = stl.stat()
        models.append({
            "filename": stl.name,
            "path": str(stl),
            "size_kb": round(stat.st_size / 1024, 2),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
        })

    # ── Sesiones guardadas ────────────────────────────────────────────────────
    sessions_summary: List[Dict] = []
    for sid, sdata in _load_all_sessions().items():
        sessions_summary.append({
            "session_id": sid,
            "description": sdata.get("description", ""),
            "iterations": sdata.get("iterations", 1),
            "updated_at": sdata.get("updated_at", ""),
            "stl_path": sdata.get("stl_path", ""),
        })
    # Más recientes primero
    sessions_summary.sort(key=lambda s: s["updated_at"], reverse=True)

    return {
        "ok": True,
        "models": models,
        "models_count": len(models),
        "sessions": sessions_summary,
        "sessions_count": len(sessions_summary),
        "directory": str(_MODELS_DIR),
    }


def _action_open(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Abre un fichero STL en el visor por defecto de macOS.
    Acepta 'stl_path' (ruta directa) o 'session_id' (busca la sesión).

    Args:
        stl_path   (str): Ruta absoluta al fichero STL. (alternativa a session_id)
        session_id (str): ID de sesión cuyo STL se quiere abrir.
        open_viewer no hace falta — esta acción siempre abre el visor.

    Returns:
        {ok, stl_path, message}
    """
    stl_path_str = str(args.get("stl_path", "")).strip()
    session_id   = str(args.get("session_id", "")).strip()

    stl_path: Optional[Path] = None

    if stl_path_str:
        stl_path = Path(stl_path_str).expanduser()
    elif session_id:
        session = load_session(session_id)
        if not session:
            return {"ok": False, "error": f"Sesión '{session_id[:8]}…' no encontrada."}
        raw = session.get("stl_path", "")
        if raw:
            stl_path = Path(raw)

    if not stl_path:
        return {
            "ok": False,
            "error": "Proporciona 'stl_path' (ruta al STL) o 'session_id' para abrir un modelo.",
        }

    if not stl_path.exists():
        return {"ok": False, "error": f"Archivo no encontrado: {stl_path}"}

    try:
        subprocess.Popen(["open", str(stl_path)])
        return {
            "ok": True,
            "stl_path": str(stl_path),
            "message": f"Abriendo {stl_path.name} en el visor…",
        }
    except Exception as e:
        return {"ok": False, "error": f"No se pudo abrir el visor: {e}"}


def _action_delete_session(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Elimina una sesión CAD del almacén de sesiones (no borra el fichero STL).

    Args:
        session_id (str): ID de la sesión a eliminar. (obligatorio)

    Returns:
        {ok, session_id, message}
    """
    session_id = str(args.get("session_id", "")).strip()
    if not session_id:
        return {"ok": False, "error": "Falta args['session_id']."}

    if not _SESSION_FILE.exists():
        return {"ok": False, "error": "No hay sesiones guardadas."}

    try:
        store = json.loads(_SESSION_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"ok": False, "error": "El fichero de sesiones está corrupto."}

    sessions = store.get("sessions", {})
    if session_id not in sessions:
        return {"ok": False, "error": f"Sesión '{session_id[:8]}…' no encontrada."}

    del sessions[session_id]
    store["sessions"] = sessions
    _SESSION_FILE.write_text(
        json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return {
        "ok": True,
        "session_id": session_id,
        "message": "Sesión eliminada correctamente.",
    }


# ---------------------------------------------------------------------------
# Entrada principal — dispatch por acción
# ---------------------------------------------------------------------------

def run_cad_generator(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Herramienta de generación 3D CAD.

    Args:
        action (str): Acción a ejecutar (default: 'create').
            create         — Genera o itera un modelo 3D a partir de una descripción.
            list           — Lista modelos STL existentes y sesiones guardadas.
            open           — Abre un STL en el visor (por stl_path o session_id).
            delete_session — Elimina una sesión del historial.

        ── Parámetros de 'create' ──
        description (str): Descripción del modelo en lenguaje natural. (obligatorio)
            Ej: "un cubo de 50mm con un agujero central de 10mm de radio"
            Ej: "hazlo más alto, que mida 80mm"  ← usa session_id para iterar
        session_id  (str): ID de sesión. Si ya existe, modifica ese modelo. (opcional)
        model_name  (str): Nombre base para el fichero STL generado. (opcional)
        max_retries (int): Intentos máximos de generación. (default 3)
        open_viewer (bool): Abrir el STL en el visor al terminar. (default False)

        ── Parámetros de 'open' ──
        stl_path   (str): Ruta absoluta al fichero STL.
        session_id (str): Alternativa a stl_path — busca la ruta en la sesión.

        ── Parámetros de 'delete_session' ──
        session_id (str): ID de la sesión a eliminar. (obligatorio)

    Returns (create):
        {ok, stl_path, description, session_id, code, attempts, model_size_kb, llm_provider}

    Returns (list):
        {ok, models, models_count, sessions, sessions_count, directory}

    Returns (open):
        {ok, stl_path, message}

    Returns (delete_session):
        {ok, session_id, message}
    """
    action = str(args.get("action", "create")).strip().lower()

    if action == "create":
        return _action_create(args)
    elif action == "list":
        return _action_list(args)
    elif action == "open":
        return _action_open(args)
    elif action == "delete_session":
        return _action_delete_session(args)
    else:
        return {
            "ok": False,
            "error": (
                f"Acción desconocida: '{action}'. "
                "Usa: create, list, open, delete_session"
            ),
        }
