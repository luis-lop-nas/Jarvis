"""
web_search.py

Tool: web_search
Búsqueda web básica que devuelve resultados (título + url + snippet).

Usa la DuckDuckGo Instant Answer JSON API (sin key, sin scraping HTML):
  GET https://api.duckduckgo.com/?q=QUERY&format=json&no_html=1&skip_disambig=1

Cache LRU en memoria con TTL de 5 minutos para evitar peticiones repetidas.
"""

from __future__ import annotations

import re
import time
import urllib.parse
from typing import Any, Dict, List, Optional

import requests

# ── Cache LRU simple con TTL ──────────────────────────────────────────────────

_search_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
_SEARCH_CACHE_TTL = 300.0  # 5 minutos


def _get_cached(query: str, limit: int) -> Optional[Dict[str, Any]]:
    key = f"{query}:{limit}"
    entry = _search_cache.get(key)
    if entry and (time.monotonic() - entry[0]) < _SEARCH_CACHE_TTL:
        return entry[1]
    return None


def _set_cached(query: str, limit: int, result: Dict[str, Any]) -> None:
    key = f"{query}:{limit}"
    _search_cache[key] = (time.monotonic(), result)
    # Limpiar entradas expiradas si cache supera 50 entradas
    if len(_search_cache) > 50:
        now = time.monotonic()
        for k in list(_search_cache):
            if now - _search_cache[k][0] > _SEARCH_CACHE_TTL:
                del _search_cache[k]


# ── DDG JSON API ──────────────────────────────────────────────────────────────

_DDG_API = "https://api.duckduckgo.com/"
_DDG_HEADERS = {"User-Agent": "Mozilla/5.0 Jarvis/1.0"}


_TAG_RE = re.compile(r"<[^>]+>")
_RESULT_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
    r'<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
    re.DOTALL,
)


def _strip_tags(s: str) -> str:
    s = _TAG_RE.sub("", s)
    return " ".join(
        s.replace("&nbsp;", " ").replace("&amp;", "&")
         .replace("&quot;", '"').replace("&#39;", "'").split()
    ).strip()


def _fetch_ddg_json(query: str, limit: int) -> List[Dict[str, str]]:
    """
    Intenta DDG Instant Answer JSON primero (rápido para preguntas factuales).
    Si devuelve pocos resultados, cae a DDG HTML scraping para búsquedas generales.
    """
    results: List[Dict[str, str]] = []

    # 1. Instant Answer API (Wikipedia/conocimiento, sin clave, muy rápido)
    try:
        params = {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
        r = requests.get(_DDG_API, params=params, timeout=6, headers=_DDG_HEADERS)
        r.raise_for_status()
        data = r.json()

        abstract = data.get("AbstractText", "").strip()
        abstract_url = data.get("AbstractURL", "").strip()
        abstract_src = data.get("AbstractSource", "").strip()
        if abstract and abstract_url:
            results.append({
                "title": abstract_src or abstract_url,
                "url": abstract_url,
                "snippet": abstract,
            })

        for topic in data.get("RelatedTopics", []):
            if len(results) >= limit:
                break
            if "Topics" in topic:
                for sub in topic["Topics"]:
                    if len(results) >= limit:
                        break
                    text = sub.get("Text", "").strip()
                    url = sub.get("FirstURL", "").strip()
                    if text and url:
                        results.append({
                            "title": text.split(" - ")[0] if " - " in text else text[:80],
                            "url": url,
                            "snippet": text,
                        })
            else:
                text = topic.get("Text", "").strip()
                url = topic.get("FirstURL", "").strip()
                if text and url:
                    results.append({
                        "title": text.split(" - ")[0] if " - " in text else text[:80],
                        "url": url,
                        "snippet": text,
                    })
    except Exception:
        pass

    # 2. Fallback HTML scraping si Instant Answer devuelve pocos resultados
    if len(results) < min(2, limit):
        try:
            r2 = requests.get(
                "https://duckduckgo.com/html/",
                params={"q": query},
                timeout=8,
                headers=_DDG_HEADERS,
            )
            r2.raise_for_status()
            seen_urls = {res["url"] for res in results}
            for m in _RESULT_RE.finditer(r2.text):
                href = urllib.parse.unquote(m.group("href"))
                if href in seen_urls:
                    continue
                title = _strip_tags(m.group("title"))
                snippet = _strip_tags(m.group("snippet"))
                results.append({"title": title, "url": href, "snippet": snippet})
                seen_urls.add(href)
                if len(results) >= limit:
                    break
        except Exception:
            pass

    return results[:limit]


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

    # Revisar cache primero
    cached = _get_cached(query, limit)
    if cached is not None:
        return cached

    results = _fetch_ddg_json(query, limit)

    output = {
        "ok": True,
        "query": query,
        "results": results,
        "fetched_from": f"{_DDG_API}?q={query}&format=json",
    }
    _set_cached(query, limit, output)
    return output
