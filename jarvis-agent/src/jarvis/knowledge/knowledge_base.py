"""
knowledge_base.py

Sistema RAG (Retrieval-Augmented Generation) con ChromaDB.
Permite a Jarvis recordar y consultar información técnica.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    import chromadb
    from chromadb.config import Settings
    from sentence_transformers import SentenceTransformer
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False


class KnowledgeBase:
    """Base de conocimiento vectorial para Jarvis."""
    
    def __init__(self, persist_directory: str = "data/knowledge"):
        """
        Inicializa la base de conocimiento.
        
        Args:
            persist_directory: Directorio donde persistir la base de datos
        """
        if not CHROMADB_AVAILABLE:
            raise ImportError("ChromaDB no instalado. Ejecuta: pip3 install chromadb sentence-transformers")
        
        self.persist_dir = Path(persist_directory).expanduser().resolve()
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        
        # Inicializar ChromaDB
        self.client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=Settings(anonymized_telemetry=False)
        )
        
        # Colección principal de conocimiento
        self.collection = self.client.get_or_create_collection(
            name="jarvis_knowledge",
            metadata={"description": "Knowledge base for Jarvis assistant"}
        )
        
        print(f"📚 Knowledge base inicializada: {self.collection.count()} documentos")
    
    def add_document(
        self,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        doc_id: Optional[str] = None
    ) -> str:
        """
        Añade un documento a la base de conocimiento.
        
        Args:
            content: Contenido del documento (texto, código, etc.)
            metadata: Metadatos opcionales (título, tags, fuente, etc.)
            doc_id: ID personalizado (si no se provee, se genera automáticamente)
        
        Returns:
            ID del documento añadido
        """
        if not content.strip():
            raise ValueError("El contenido no puede estar vacío")
        
        # Generar ID si no se provee
        if not doc_id:
            doc_id = str(uuid.uuid4())
        
        # Preparar metadatos
        meta = metadata or {}
        meta.setdefault("type", "general")
        
        # Añadir a ChromaDB
        self.collection.add(
            documents=[content],
            metadatas=[meta],
            ids=[doc_id]
        )
        
        return doc_id
    
    def add_code_snippet(
        self,
        code: str,
        language: str,
        description: str,
        tags: Optional[List[str]] = None
    ) -> str:
        """
        Añade un snippet de código.
        
        Args:
            code: Código fuente
            language: Lenguaje de programación
            description: Descripción de qué hace
            tags: Tags opcionales
        
        Returns:
            ID del snippet
        """
        content = f"{description}\n\nLenguaje: {language}\n\n```{language}\n{code}\n```"
        
        metadata = {
            "type": "code",
            "language": language,
            "description": description,
            "tags": ",".join(tags) if tags else ""
        }
        
        return self.add_document(content, metadata)
    
    def add_tutorial(
        self,
        title: str,
        content: str,
        category: str,
        source: Optional[str] = None
    ) -> str:
        """
        Añade un tutorial o guía.
        
        Args:
            title: Título del tutorial
            content: Contenido completo
            category: Categoría (python, javascript, devops, etc.)
            source: URL o fuente original
        
        Returns:
            ID del tutorial
        """
        metadata = {
            "type": "tutorial",
            "title": title,
            "category": category,
            "source": source or ""
        }
        
        return self.add_document(content, metadata)
    
    def search(
        self,
        query: str,
        n_results: int = 5,
        filter_metadata: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Busca documentos relevantes.
        
        Args:
            query: Consulta de búsqueda
            n_results: Número de resultados a retornar
            filter_metadata: Filtros opcionales (ej: {"type": "code"})
        
        Returns:
            Lista de documentos relevantes con sus metadatos
        """
        results = self.collection.query(
            query_texts=[query],
            n_results=n_results,
            where=filter_metadata
        )
        
        # Formatear resultados
        documents = []
        for i in range(len(results['ids'][0])):
            documents.append({
                'id': results['ids'][0][i],
                'content': results['documents'][0][i],
                'metadata': results['metadatas'][0][i],
                'distance': results['distances'][0][i] if 'distances' in results else None
            })
        
        return documents
    
    def get_by_id(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Obtiene un documento por su ID."""
        try:
            result = self.collection.get(ids=[doc_id])
            if result['ids']:
                return {
                    'id': result['ids'][0],
                    'content': result['documents'][0],
                    'metadata': result['metadatas'][0]
                }
            return None
        except:
            return None
    
    def delete(self, doc_id: str) -> bool:
        """Elimina un documento."""
        try:
            self.collection.delete(ids=[doc_id])
            return True
        except:
            return False
    
    def list_all(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Lista todos los documentos."""
        result = self.collection.get(limit=limit)
        
        documents = []
        for i in range(len(result['ids'])):
            documents.append({
                'id': result['ids'][i],
                'content': result['documents'][i][:200] + "...",  # Preview
                'metadata': result['metadatas'][i]
            })
        
        return documents
    
    def count(self) -> int:
        """Retorna el número total de documentos."""
        return self.collection.count()
    
    def clear_all(self) -> None:
        """⚠️ ELIMINA TODA LA BASE DE CONOCIMIENTO."""
        self.client.delete_collection("jarvis_knowledge")
        self.collection = self.client.get_or_create_collection(
            name="jarvis_knowledge",
            metadata={"description": "Knowledge base for Jarvis assistant"}
        )
        print("🗑️ Base de conocimiento limpiada")
