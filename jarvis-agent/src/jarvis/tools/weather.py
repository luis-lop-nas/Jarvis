"""
weather.py

Tool: weather
Consulta el clima actual de cualquier ciudad usando wttr.in (sin API key).
"""

from __future__ import annotations

from typing import Any, Dict, List

import requests

_WMO_CODES = {
    0: "despejado", 1: "casi despejado", 2: "parcialmente nublado", 3: "nublado",
    45: "niebla", 48: "niebla con escarcha",
    51: "llovizna ligera", 53: "llovizna moderada", 55: "llovizna densa",
    61: "lluvia ligera", 63: "lluvia moderada", 65: "lluvia intensa",
    71: "nieve ligera", 73: "nieve moderada", 75: "nieve intensa",
    80: "chubascos ligeros", 81: "chubascos moderados", 82: "chubascos intensos",
    85: "chubascos de nieve ligeros", 86: "chubascos de nieve intensos",
    95: "tormenta eléctrica", 96: "tormenta con granizo ligero",
    99: "tormenta con granizo intenso",
}


def _wttr_json(city: str) -> Dict[str, Any]:
    """Obtiene clima via wttr.in JSON API."""
    url = f"https://wttr.in/{requests.utils.quote(city)}?format=j1"
    r = requests.get(url, timeout=10, headers={"User-Agent": "curl/7.0"})
    r.raise_for_status()
    return r.json()


def run_weather(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Args:
      - city: Ciudad (obligatorio, ej: "Madrid", "Barcelona", "New York")
      - days: Pronóstico días adicionales (0-2, default 0 = solo hoy)

    Returns: dict con temperatura, descripción, humedad, viento, etc.
    """
    city = str(args.get("city", "")).strip()
    if not city:
        return {"ok": False, "error": "Falta args['city']. Ejemplo: 'Madrid'"}

    days = max(0, min(int(args.get("days", 0)), 2))

    try:
        data = _wttr_json(city)
    except requests.exceptions.Timeout:
        return {"ok": False, "error": "Timeout consultando wttr.in"}
    except requests.exceptions.HTTPError as e:
        return {"ok": False, "error": f"Error HTTP: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"Error obteniendo clima: {e}"}

    try:
        current_list = data.get("current_condition", [])
        if not current_list:
            return {"ok": False, "error": "API no devolvió condiciones actuales"}
        current = current_list[0]

        nearest_list = data.get("nearest_area", [])
        nearest = nearest_list[0] if nearest_list else {}

        city_name = (nearest.get("areaName") or [{}])[0].get("value", city)
        country = (nearest.get("country") or [{}])[0].get("value", "")

        temp_c = int(current.get("temp_C", 0))
        feels_c = int(current.get("FeelsLikeC", temp_c))
        humidity = int(current.get("humidity", 0))
        wind_kmh = int(current.get("windspeedKmph", 0))
        wind_dir = current.get("winddir16Point", "N")
        visibility_km = int(current.get("visibility", 0))
        uv_index = current.get("uvIndex", "N/A")

        desc_raw = (current.get("weatherDesc") or [{}])[0].get("value", "")
        # Intentar código WMO si viene
        wmo = int(current.get("weatherCode", -1))
        desc = _WMO_CODES.get(wmo, desc_raw.lower() or "desconocido")

        result: Dict[str, Any] = {
            "ok": True,
            "city": city_name,
            "country": country,
            "current": {
                "temp_c": temp_c,
                "feels_like_c": feels_c,
                "description": desc,
                "humidity_pct": humidity,
                "wind_kmh": wind_kmh,
                "wind_direction": wind_dir,
                "visibility_km": visibility_km,
                "uv_index": uv_index,
            },
        }

        # Pronóstico por días
        if days > 0:
            forecast: List[Dict[str, Any]] = []
            weather_days = data.get("weather", [])
            for i, day_data in enumerate(weather_days[:days + 1]):
                if i == 0:
                    continue  # Hoy ya está en current
                max_c = int(day_data.get("maxtempC", 0))
                min_c = int(day_data.get("mintempC", 0))
                date_str = day_data.get("date", "")
                hourly = day_data.get("hourly", [])
                hourly_mid = hourly[4] if len(hourly) > 4 else (hourly[-1] if hourly else {})
                desc_day = (hourly_mid.get("weatherDesc") or [{}])[0].get("value", "")
                forecast.append({
                    "date": date_str,
                    "max_c": max_c,
                    "min_c": min_c,
                    "description": desc_day.lower(),
                })
            result["forecast"] = forecast

        return result

    except (KeyError, IndexError, ValueError) as e:
        return {"ok": False, "error": f"Error procesando respuesta de clima: {e}"}
