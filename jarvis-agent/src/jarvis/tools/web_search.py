"""
web_search.py

Tool: web_search
Búsqueda web básica que devuelve resultados (título + url + snippet).

Sin depender de keys:
- Hace GET a DuckDuckGo (HTML)
- Parseo simple para extraer top resultados

Nota:
- Este parser puede romperse si DDG cambia el HTML.
- Cuando quieras lo cambiamos a una API (Brave/SerpAPI) para estabilidad.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Dict, List

import requests


# Regex muy simple para extraer resultados
# (fragil, pero suficiente para arrancar)
_RESULT_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
    r'<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
    re.DOTALL,
)

_TAG_RE = re.compile(r"<.*?>")


def _strip_tags(s: str) -> str:
    """Quita HTML tags y limpia entidades básicas."""
    s = _TAG_RE.sub("", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    s = s.replace("&quot;", '"').replace("&#39;", "'")
    return " ".join(s.split()).strip()


def run_web_search(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Args:
      - query: str (obligatorio)
      - limit: int (opcional, default 5, max 10)

    Returns:
      {
        "query": "...",
        "results": [{"title":..., "url":..., "snippet":...}, ...],
        "fetched_from": "..."
      }
    """
    query = str(args.get("query", "")).strip()
    if not query:
        raise ValueError("Falta args['query'].")

    limit = int(args.get("limit", 5))
    limit = max(1, min(limit, 10))

    url = "https://duckduckgo.com/html/"
    params = {"q": query}

    r = requests.get(url, params=params, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()

    html = r.text
    results: List[Dict[str, str]] = []

    for m in _RESULT_RE.finditer(html):
        href = urllib.parse.unquote(m.group("href"))
        title = _strip_tags(m.group("title"))
        snippet = _strip_tags(m.group("snippet"))
        results.append({"title": title, "url": href, "snippet": snippet})
        if len(results) >= limit:
            break

    return {"query": query, "results": results, "fetched_from": str(r.url)}