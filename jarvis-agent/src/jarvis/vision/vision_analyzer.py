"""
vision_analyzer.py

Análisis de imágenes usando Groq Vision API.
"""

from __future__ import annotations

from typing import Optional, Dict, Any


def analyze_image_with_groq(
    image_base64: str,
    prompt: str,
    api_key: str,
    model: str = "llama-3.2-90b-vision-preview"
) -> Dict[str, Any]:
    """
    Analiza una imagen usando Groq Vision API.
    
    Args:
        image_base64: Imagen en formato base64
        prompt: Pregunta o instrucción sobre la imagen
        api_key: Groq API key
        model: Modelo a usar
    
    Returns:
        {
            'ok': bool,
            'description': str,
            'error': str (si ok=False)
        }
    """
    try:
        from groq import Groq
        
        client = Groq(api_key=api_key)
        
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_base64}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=1000,
            temperature=0.5
        )
        
        description = response.choices[0].message.content.strip()
        
        return {
            'ok': True,
            'description': description
        }
        
    except Exception as e:
        return {
            'ok': False,
            'error': f"Error analizando imagen: {str(e)}"
        }


def describe_screen(
    image_base64: str,
    api_key: str,
    context: Optional[str] = None
) -> str:
    """
    Describe lo que hay en la pantalla.
    
    Args:
        image_base64: Captura de pantalla en base64
        api_key: Groq API key
        context: Contexto adicional (app activa, URL, etc.)
    
    Returns:
        Descripción de la pantalla
    """
    prompt = "Describe brevemente qué hay en esta pantalla. Sé conciso y menciona los elementos principales."
    
    if context:
        prompt = f"Contexto: {context}\n\n{prompt}"
    
    result = analyze_image_with_groq(image_base64, prompt, api_key)
    
    if result['ok']:
        return result['description']
    else:
        return f"Error: {result.get('error', 'No se pudo analizar')}"


def answer_about_screen(
    image_base64: str,
    question: str,
    api_key: str,
    context: Optional[str] = None
) -> str:
    """
    Responde una pregunta específica sobre la pantalla.
    
    Args:
        image_base64: Captura de pantalla en base64
        question: Pregunta del usuario
        api_key: Groq API key
        context: Contexto adicional
    
    Returns:
        Respuesta a la pregunta
    """
    prompt = f"Basándote en esta imagen, responde: {question}"
    
    if context:
        prompt = f"Contexto: {context}\n\n{prompt}"
    
    result = analyze_image_with_groq(image_base64, prompt, api_key)
    
    if result['ok']:
        return result['description']
    else:
        return f"Error: {result.get('error', 'No se pudo analizar')}"


def read_text_from_screen(
    image_base64: str,
    api_key: str
) -> str:
    """
    Extrae y lee todo el texto visible en la pantalla (OCR).
    
    Args:
        image_base64: Captura de pantalla en base64
        api_key: Groq API key
    
    Returns:
        Texto extraído
    """
    prompt = """Lee y extrae TODO el texto visible en esta imagen.
    Transcribe el texto exactamente como aparece, manteniendo el formato y estructura.
    Si hay múltiples secciones, sepáralas claramente."""
    
    result = analyze_image_with_groq(image_base64, prompt, api_key)
    
    if result['ok']:
        return result['description']
    else:
        return f"Error: {result.get('error', 'No se pudo leer texto')}"
