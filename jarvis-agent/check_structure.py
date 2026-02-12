"""Verifica la estructura del proyecto Jarvis"""
from pathlib import Path

def check_structure():
    base = Path(".")
    
    # Estructura esperada
    expected = {
        "Archivos raíz": [
            ".env",
            "pyproject.toml", 
            "setup.py",
            "README.md"
        ],
        "src/jarvis/": [
            "__init__.py",
            "config.py",
            "main.py"
        ],
        "src/jarvis/agent/": [
            "__init__.py",
            "prompts.py",
            "runner.py",
            "state.py",
            "tool_agent.py"
        ],
        "src/jarvis/tools/": [
            "__init__.py",
            "registry.py",
            "shell.py",
            "filesystem.py",
            "open_app.py",
            "run_code.py",
            "web_search.py"
        ],
        "src/jarvis/ui/": [
            "__init__.py",
            "cli.py"
        ],
        "src/jarvis/voice/": [
            "__init__.py",
            "tts.py",
            "stt.py",
            "wake_word.py",
            "voice_loop.py"
        ],
        "src/jarvis/memory/": [
            "__init__.py",
            "schema.sql",
            "store.py"
        ],
        "sandbox/docker/": [
            "Dockerfile.python",
            "Dockerfile.node"
        ]
    }
    
    print("=" * 60)
    print("VERIFICACIÓN DE ESTRUCTURA - JARVIS")
    print("=" * 60)
    
    missing = []
    found = []
    
    for folder, files in expected.items():
        print(f"\n📁 {folder}")
        for file in files:
            filepath = base / folder / file if folder != "Archivos raíz" else base / file
            if filepath.exists():
                print(f"  ✅ {file}")
                found.append(str(filepath))
            else:
                print(f"  ❌ {file} - FALTA")
                missing.append(str(filepath))
    
    print("\n" + "=" * 60)
    print(f"RESUMEN: {len(found)} archivos OK, {len(missing)} archivos FALTAN")
    print("=" * 60)
    
    if missing:
        print("\n🔴 ARCHIVOS FALTANTES:")
        for m in missing:
            print(f"  - {m}")
    else:
        print("\n🟢 ¡Todos los archivos necesarios están presentes!")
    
    return len(missing) == 0

if __name__ == "__main__":
    check_structure()
