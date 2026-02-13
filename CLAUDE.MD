cat > Claude.md << 'EOF'
# JARVIS - Advanced AI Assistant

## 📋 Descripción del Proyecto

JARVIS (Just A Rather Very Intelligent System) es un asistente de IA avanzado con interfaz web interactiva, capacidades de voz, visión por computadora y gestión de conocimiento mediante RAG.

## 🏗️ Arquitectura del Sistema

### Componentes Principales

1. **Frontend Web (Interfaz Visual)**
   - Nube de puntos 3D interactiva (1200 partículas esféricas + 200 flotantes)
   - Animaciones suaves con física de partículas
   - Barra de búsqueda dinámica
   - Chat en tiempo real via WebSocket

2. **Backend (Python)**
   - FastAPI para servidor web
   - WebSocket para comunicación en tiempo real
   - Procesamiento de IA híbrido (Groq + Ollama)
   - Sistema RAG con ChromaDB

3. **Capacidades de IA**
   - **Groq API**: Respuestas conversacionales rápidas
     - Modelo: `llama-3.3-70b-versatile` (texto)
     - Modelo: `llama-3.2-90b-vision-preview` (visión)
   - **Ollama**: Tareas con herramientas habilitadas
   - **Voice**: STT (Speech-to-Text) y TTS (Text-to-Speech)
   - **Vision**: Análisis de pantalla usando APIs de accesibilidad + capturas

## 📁 Estructura del Proyecto
```
jarvis-agent/
├── src/
│   └── jarvis/
│       ├── agent/           # Lógica del agente IA
│       ├── memory/          # Sistema de memoria (ChromaDB)
│       ├── voice/           # STT/TTS
│       ├── vision/          # Computer vision
│       ├── web/             # Servidor web
│       │   ├── server.py    # FastAPI server
│       │   └── static/      # Frontend
│       │       ├── index.html
│       │       ├── style.css
│       │       └── app.js
│       ├── tools/           # Herramientas del agente
│       └── config.py        # Configuración
├── data/                    # ChromaDB storage
├── scripts/                 # Scripts auxiliares
├── .env                     # Variables de entorno
├── pyproject.toml          # Dependencias Python
└── Claude.md               # Este archivo
```

## 🎨 Sistema Visual (Frontend)

### Nube de Puntos 3D

**Características:**
- **1200 partículas** en distribución de Fibonacci (esfera)
- **200 partículas flotantes** ambientales
- **Física individual**: cada partícula con rotación, velocidad y comportamiento únicos
- **Interactividad con ratón**: 40% de partículas reaccionan (optimización)
- **Profundidad 3D**: proyección perspectiva con sorting por eje Z

**Parámetros de Velocidad (LENTOS para elegancia):**
- Rotación: `0.0004` (esfera) / `0.004` (flotantes)
- Ruido: `0.00002` 
- Transiciones: `0.004` (muy suave)
- Pulso: `0.002-0.004`

**Estados del Sistema:**
1. **idle**: Esfera al 80% de perfección, centro de pantalla
2. **compact**: Al hacer click, se compacta a 100% (transición ~2s)
3. **active**: Al escribir, se mueve arriba-izquierda y vibra orgánicamente

### Colores
- Azul eléctrico: `RGB(0, 180, 255)`
- Azul brillante: `RGB(100, 220, 255)`
- Núcleo: Blanco con glow

## 🔧 Tecnologías Utilizadas

### Backend
- **Python 3.12**
- **FastAPI** + **python-multipart**: Servidor web
- **WebSocket**: Comunicación en tiempo real
- **ChromaDB** + **sentence-transformers**: Vector database
- **Groq API**: LLM rápido para conversación
- **Ollama**: LLM local con tools
- **macOS Frameworks**: Quartz (screenshots), AppKit (app context)

### Frontend
- **Vanilla JavaScript**: Sin frameworks
- **Canvas API**: Renderizado de partículas
- **WebSocket API**: Comunicación bidireccional
- **CSS3**: Animaciones y estilos

## 🚀 Instalación y Uso

### 1. Configurar Entorno
```bash
cd /Users/luichi/Documents/Jarvis/jarvis-agent
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Configurar Variables de Entorno

Archivo `.env`:
```env
GROQ_API_KEY=tu_clave_aqui
# Otras configuraciones...
```

### 3. Iniciar Servidor Web
```bash
source .venv/bin/activate
PYTHONPATH=src uvicorn jarvis.web.server:app --host 0.0.0.0 --port 8000
```

Luego abrir: `http://localhost:8000`

### 4. Usar JARVIS en Terminal (CLI)
```bash
source .venv/bin/activate
python -m jarvis.cli
```

## 🎯 Flujo de Interacción Web

1. **Usuario ve la esfera** (estado idle, 80% perfecta, partículas lentas)
2. **Click en la esfera** → Compactación suave a 100% (~2 segundos)
3. **Aparece barra de búsqueda** (animación de 1.2s)
4. **Usuario escribe** → JARVIS se mueve arriba-izquierda + vibración orgánica
5. **Enter** → Envío por WebSocket
6. **JARVIS vibra** mientras procesa
7. **Respuesta aparece** en chat + JARVIS deja de vibrar

## 🔌 WebSocket API

### Cliente → Servidor
```json
{
  "message": "texto del usuario"
}
```

### Servidor → Cliente
```json
{
  "type": "assistant_message",
  "content": "respuesta de JARVIS"
}
```

## 🧠 Sistema de Memoria (RAG)

- **ChromaDB**: Vector database
- **sentence-transformers**: Embeddings
- **Capacidad**: Diseñado para 5,000 documentos
- **Persistencia**: Almacenamiento local en `data/`

## 🎤 Capacidades de Voz

- **STT**: Speech-to-Text para comandos de voz
- **TTS**: Text-to-Speech para respuestas audibles
- **Wake Word**: "Hey Jarvis" (configurable)

## 👁️ Sistema de Visión

- **Screen Analysis**: Captura y análisis de pantalla
- **Accessibility APIs**: Contexto de aplicación activa (macOS)
- **Groq Vision**: Modelo `llama-3.2-90b-vision-preview`

## 🛠️ Herramientas Disponibles

- **Filesystem**: Operaciones de archivos
- **App Launcher**: Abrir aplicaciones
- **Shell Commands**: Ejecutar comandos
- **Web Search**: Búsqueda en internet
- **VS Code Integration**: Deployment automático de código

## ⚙️ Configuración de Rendimiento

### Optimizaciones Frontend
- **Throttled mouse events**: requestAnimationFrame
- **Cacheo de proyección 2D**: Calculado 1 vez por frame
- **Sorting selectivo**: Solo partículas de esfera
- **Conexiones reducidas**: 1 de cada 8 partículas, cada 2 frames
- **40% de interacción**: Solo algunas partículas reaccionan al ratón

### Velocidades Ajustadas
- **Movimiento casi imperceptible** en estado idle
- **Transiciones ultra suaves** (factor 0.004)
- **Vibración orgánica individual** (cada partícula única)

## 📝 Principios de Diseño

1. **Elegancia sobre velocidad**: Movimientos lentos y sutiles
2. **Transiciones naturales**: Curvas de easing suaves
3. **Física realista**: Inercia, fricción, fuerzas
4. **Individualidad**: Cada partícula es única
5. **Respuesta fluida**: 60 FPS sin lag

## 🔄 Enfoque de Desarrollo

- **Iterativo**: Desarrollo en fases incrementales
- **Terminal-first**: Todo por comandos (no GUI)
- **Híbrido**: Combinar múltiples tecnologías (Groq + Ollama)
- **Optimización constante**: Balance rendimiento/calidad

## 🎨 Paleta de Colores

| Elemento | Color | RGB |
|----------|-------|-----|
| Azul eléctrico | `#00B4FF` | `0, 180, 255` |
| Azul brillante | `#64DCFF` | `100, 220, 255` |
| Núcleo | `#FFFFFF` | `255, 255, 255` |
| Fondo | `#000000` | `0, 0, 0` |

## 🐛 Debugging

### Ver logs del servidor:
```bash
# El servidor FastAPI imprime logs en consola
tail -f logs/jarvis.log  # Si existe
```

### Consola del navegador:
- **F12** o **Cmd+Option+I**
- Ver mensajes WebSocket
- Ver errores JavaScript

### Verificar WebSocket:
```javascript
// En consola del navegador
console.log('WS conectado:', isConnected);
```

## 📚 Recursos y Referencias

- **Distribución de Fibonacci**: Para distribución uniforme en esfera
- **Física de partículas**: Inercia, fricción, fuerzas
- **WebSocket**: Comunicación full-duplex
- **Canvas API**: Renderizado 2D de alto rendimiento
- **ChromaDB**: Vector database para RAG

## 🔮 Futuras Mejoras

- [ ] Reconocimiento de voz en web
- [ ] Más herramientas (calendar, email, etc.)
- [ ] Temas personalizables
- [ ] Modo oscuro/claro
- [ ] Historial de conversaciones persistente
- [ ] Mobile responsive
- [ ] Exportar conversaciones
- [ ] Integración con más APIs

## 📄 Licencia

Proyecto personal de desarrollo

## 👤 Autor

**Luichi** - Desarrollador principal

---

**Última actualización**: Febrero 2026
**Versión**: 1.0.0
EOF