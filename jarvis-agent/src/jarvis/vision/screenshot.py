"""
screenshot.py

Captura de pantalla en macOS.
"""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import Optional

try:
    from PIL import Image
    import Quartz
    SCREENSHOT_AVAILABLE = True
except ImportError:
    SCREENSHOT_AVAILABLE = False


def capture_screen(output_path: Optional[Path] = None) -> tuple[Optional[Path], Optional[str]]:
    """
    Captura la pantalla completa.
    
    Returns:
        (path, base64_string) - Ruta del archivo guardado y string base64
    """
    if not SCREENSHOT_AVAILABLE:
        return None, None
    
    try:
        # Capturar pantalla usando Quartz
        region = Quartz.CGRectInfinite
        image = Quartz.CGWindowListCreateImage(
            region,
            Quartz.kCGWindowListOptionOnScreenOnly,
            Quartz.kCGNullWindowID,
            Quartz.kCGWindowImageDefault
        )
        
        # Obtener dimensiones
        width = Quartz.CGImageGetWidth(image)
        height = Quartz.CGImageGetHeight(image)
        
        # Crear buffer de bytes
        bytes_per_row = Quartz.CGImageGetBytesPerRow(image)
        pixel_data = Quartz.CGDataProviderCopyData(
            Quartz.CGImageGetDataProvider(image)
        )
        
        # Convertir a PIL Image
        pil_image = Image.frombytes(
            'RGBA',
            (width, height),
            pixel_data,
            'raw',
            'BGRA'
        )
        
        # Convertir a RGB (sin alpha)
        pil_image = pil_image.convert('RGB')
        
        # Guardar si se especifica ruta
        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            pil_image.save(output_path, 'PNG')
        
        # Generar base64
        buffer = BytesIO()
        pil_image.save(buffer, format='PNG')
        img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        return output_path, img_base64
        
    except Exception as e:
        print(f"Error capturando pantalla: {e}")
        return None, None


def capture_active_window(output_path: Optional[Path] = None) -> tuple[Optional[Path], Optional[str]]:
    """
    Captura solo la ventana activa.
    
    Returns:
        (path, base64_string)
    """
    if not SCREENSHOT_AVAILABLE:
        return None, None
    
    try:
        # Obtener lista de ventanas
        window_list = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID
        )
        
        # Encontrar ventana activa (la primera en la lista generalmente)
        active_window = None
        for window in window_list:
            layer = window.get('kCGWindowLayer', 0)
            if layer == 0:  # Ventanas normales
                active_window = window
                break
        
        if not active_window:
            # Fallback a pantalla completa
            return capture_screen(output_path)
        
        # Obtener bounds de la ventana
        bounds = active_window['kCGWindowBounds']
        x = int(bounds['X'])
        y = int(bounds['Y'])
        width = int(bounds['Width'])
        height = int(bounds['Height'])
        
        # Capturar región específica
        region = Quartz.CGRectMake(x, y, width, height)
        
        image = Quartz.CGWindowListCreateImage(
            region,
            Quartz.kCGWindowListOptionOnScreenOnly,
            Quartz.kCGNullWindowID,
            Quartz.kCGWindowImageDefault
        )
        
        # Convertir a PIL
        img_width = Quartz.CGImageGetWidth(image)
        img_height = Quartz.CGImageGetHeight(image)
        bytes_per_row = Quartz.CGImageGetBytesPerRow(image)
        pixel_data = Quartz.CGDataProviderCopyData(
            Quartz.CGImageGetDataProvider(image)
        )
        
        pil_image = Image.frombytes(
            'RGBA',
            (img_width, img_height),
            pixel_data,
            'raw',
            'BGRA'
        )
        
        pil_image = pil_image.convert('RGB')
        
        # Guardar
        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            pil_image.save(output_path, 'PNG')
        
        # Base64
        buffer = BytesIO()
        pil_image.save(buffer, format='PNG')
        img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        return output_path, img_base64
        
    except Exception as e:
        print(f"Error capturando ventana: {e}")
        return capture_screen(output_path)
