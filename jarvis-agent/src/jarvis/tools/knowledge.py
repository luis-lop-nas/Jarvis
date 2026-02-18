"""
knowledge.py

Herramienta para gestionar la base de conocimiento de Jarvis.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from jarvis.knowledge.knowledge_base import KnowledgeBase


# Instancia global de knowledge base
_kb: KnowledgeBase | None = None


def get_knowledge_base() -> KnowledgeBase:
    """Obtiene o crea la instancia de knowledge base."""
    global _kb
    if _kb is None:
        _kb = KnowledgeBase(persist_directory="data/knowledge")
    return _kb


def knowledge_tool(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Gestiona la base de conocimiento de Jarvis.

    Args:
        args: dict con claves:
            - "action": "search", "add", "add_code", "add_tutorial", "list", "delete", "stats"
            - "query": consulta de búsqueda (para search)
            - "content": contenido a guardar
            - "title": título o descripción
            - "language": lenguaje de programación (default "python")
            - "category": categoría (default "general")
            - "tags": tags separados por comas
            - "doc_id": ID del documento (para delete)
            - "n_results": número de resultados (default 3)

    Returns:
        Dict con ok, result o error
    """
    action = str(args.get("action", "search")).lower().strip()
    query = str(args.get("query", ""))
    content = str(args.get("content", ""))
    title = str(args.get("title", ""))
    language = str(args.get("language", "python"))
    category = str(args.get("category", "general"))
    tags = str(args.get("tags", ""))
    doc_id = str(args.get("doc_id", ""))
    n_results = int(args.get("n_results", 3))
    
    try:
        kb = get_knowledge_base()
        
        # SEARCH - Buscar información
        if action == "search":
            if not query:
                return {
                    "ok": False,
                    "error": "Necesito una consulta para buscar"
                }
            
            results = kb.search(query, n_results=n_results)
            
            if not results:
                return {
                    "ok": True,
                    "result": f"No encontré información sobre '{query}' en mi base de conocimiento."
                }
            
            # Formatear resultados
            output = f"📚 Encontré {len(results)} resultado(s) sobre '{query}':\n\n"
            
            for i, doc in enumerate(results, 1):
                meta = doc['metadata']
                doc_type = meta.get('type', 'general')
                
                output += f"{i}. "
                
                if doc_type == 'code':
                    output += f"[Código {meta.get('language', '')}] {meta.get('description', '')}\n"
                elif doc_type == 'tutorial':
                    output += f"[Tutorial] {meta.get('title', '')}\n"
                else:
                    output += f"{doc['content'][:150]}...\n"
                
                output += f"   ID: {doc['id']}\n\n"
            
            return {
                "ok": True,
                "result": output.strip(),
                "results": results
            }
        
        # ADD - Añadir documento general
        elif action == "add":
            if not content:
                return {
                    "ok": False,
                    "error": "Necesito contenido para añadir"
                }
            
            metadata = {
                "type": "general",
                "title": title or "Sin título"
            }
            
            doc_id = kb.add_document(content, metadata)
            
            return {
                "ok": True,
                "result": f"✅ Documento añadido a mi base de conocimiento\nID: {doc_id}",
                "doc_id": doc_id
            }
        
        # ADD_CODE - Añadir snippet de código
        elif action == "add_code":
            if not content:
                return {
                    "ok": False,
                    "error": "Necesito el código para añadir"
                }
            
            if not title:
                return {
                    "ok": False,
                    "error": "Necesito una descripción del código"
                }
            
            tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
            
            doc_id = kb.add_code_snippet(
                code=content,
                language=language,
                description=title,
                tags=tag_list
            )
            
            return {
                "ok": True,
                "result": f"✅ Código {language} añadido a mi base de conocimiento\nDescripción: {title}\nID: {doc_id}",
                "doc_id": doc_id
            }
        
        # ADD_TUTORIAL - Añadir tutorial
        elif action == "add_tutorial":
            if not content or not title:
                return {
                    "ok": False,
                    "error": "Necesito título y contenido del tutorial"
                }
            
            doc_id = kb.add_tutorial(
                title=title,
                content=content,
                category=category
            )
            
            return {
                "ok": True,
                "result": f"✅ Tutorial añadido a mi base de conocimiento\nTítulo: {title}\nCategoría: {category}\nID: {doc_id}",
                "doc_id": doc_id
            }
        
        # LIST - Listar documentos
        elif action == "list":
            docs = kb.list_all(limit=20)
            
            if not docs:
                return {
                    "ok": True,
                    "result": "Mi base de conocimiento está vacía."
                }
            
            output = f"📚 Tengo {kb.count()} documento(s) en mi base de conocimiento:\n\n"
            
            for doc in docs:
                meta = doc['metadata']
                doc_type = meta.get('type', 'general')
                
                if doc_type == 'code':
                    output += f"• [Código {meta.get('language', '')}] {meta.get('description', '')}\n"
                elif doc_type == 'tutorial':
                    output += f"• [Tutorial] {meta.get('title', '')} ({meta.get('category', '')})\n"
                else:
                    output += f"• {meta.get('title', 'Sin título')}\n"
                
                output += f"  ID: {doc['id']}\n"
            
            return {
                "ok": True,
                "result": output.strip()
            }
        
        # DELETE - Eliminar documento
        elif action == "delete":
            if not doc_id:
                return {
                    "ok": False,
                    "error": "Necesito el ID del documento a eliminar"
                }
            
            success = kb.delete(doc_id)
            
            if success:
                return {
                    "ok": True,
                    "result": f"✅ Documento {doc_id} eliminado de mi base de conocimiento"
                }
            else:
                return {
                    "ok": False,
                    "error": f"No encontré el documento {doc_id}"
                }
        
        # STATS - Estadísticas
        elif action == "stats":
            count = kb.count()
            
            return {
                "ok": True,
                "result": f"📊 Estadísticas de mi base de conocimiento:\n\nTotal documentos: {count}"
            }
        
        else:
            return {
                "ok": False,
                "error": f"Acción desconocida: {action}. Usa: search, add, add_code, add_tutorial, list, delete, stats"
            }
        
    except Exception as e:
        return {
            "ok": False,
            "error": f"Error en knowledge base: {str(e)}"
        }
