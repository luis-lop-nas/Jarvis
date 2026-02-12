#!/usr/bin/env python3
"""
Script para inicializar la base de conocimiento con documentos predefinidos.
"""

import sys
from pathlib import Path

# Añadir src al path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from jarvis.knowledge.knowledge_base import KnowledgeBase


def load_markdown_files(kb: KnowledgeBase, seed_dir: Path):
    """Carga archivos markdown del directorio seed."""
    
    if not seed_dir.exists():
        print(f"❌ Directorio {seed_dir} no existe")
        return
    
    md_files = list(seed_dir.glob("*.md"))
    
    if not md_files:
        print(f"⚠️ No hay archivos .md en {seed_dir}")
        return
    
    print(f"\n📚 Cargando {len(md_files)} documentos...\n")
    
    for md_file in md_files:
        try:
            content = md_file.read_text(encoding='utf-8')
            
            lines = content.split('\n')
            title = "Sin título"
            for line in lines:
                if line.startswith('# '):
                    title = line[2:].strip()
                    break
            
            filename = md_file.stem
            if 'python' in filename.lower():
                category = 'python'
            elif 'fastapi' in filename.lower() or 'api' in filename.lower():
                category = 'web'
            elif 'git' in filename.lower():
                category = 'version-control'
            else:
                category = 'general'
            
            doc_id = kb.add_tutorial(
                title=title,
                content=content,
                category=category,
                source=f"seed/{md_file.name}"
            )
            
            print(f"✅ {title}")
            print(f"   Categoría: {category}")
            print(f"   ID: {doc_id}\n")
            
        except Exception as e:
            print(f"❌ Error cargando {md_file.name}: {e}\n")


def main():
    print("=" * 60)
    print("🧠 INICIALIZANDO BASE DE CONOCIMIENTO DE JARVIS")
    print("=" * 60)
    
    kb = KnowledgeBase(persist_directory="data/knowledge")
    
    project_root = Path(__file__).parent.parent
    seed_dir = project_root / "data" / "knowledge_seed"
    
    load_markdown_files(kb, seed_dir)
    
    total = kb.count()
    print("=" * 60)
    print(f"✅ Inicialización completa")
    print(f"📊 Total documentos en knowledge base: {total}")
    print("=" * 60)
    
    print("\n💡 Ahora puedes:")
    print("   - Buscar: 'qué sabes sobre FastAPI'")
    print("   - Listar: 'lista mi conocimiento'")
    print("   - Añadir más: 'aprende esto: ...'")
    print()


if __name__ == "__main__":
    main()
