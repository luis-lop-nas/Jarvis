// JARVIS - Sistema completo
let ws = null;
let isConnected = false;

// Estados de JARVIS
let jarvisState = 'idle';
let isTyping = false;
let chatContainer = null;

// Wake word recognition
let recognition = null;
let isWakeWordListening = false;

// ============================================
// INICIALIZACIÓN
// ============================================

document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 JARVIS UI Loaded');
    initInteractiveParticles();
    connect();
});

// ============================================
// NUBE DE PUNTOS 3D
// ============================================

function initInteractiveParticles() {
    const particlesCanvas = document.getElementById('particles');
    if (!particlesCanvas) return;
    
    const ctx = particlesCanvas.getContext('2d');
    particlesCanvas.width = window.innerWidth;
    particlesCanvas.height = window.innerHeight;
    
    const particles = [];
    const sphereParticleCount = 1200;
    const floatingParticleCount = 400;
    let mouse = { x: particlesCanvas.width / 2, y: particlesCanvas.height / 2 };
    
    // Estados de animación
    let targetCenterX = particlesCanvas.width / 2;
    let targetCenterY = particlesCanvas.height / 2;
    let currentCenterX = targetCenterX;
    let currentCenterY = targetCenterY;
    let targetRadius = 180;
    let currentRadius = 180;
    let targetCompactness = 0.8;
    let currentCompactness = 0.8;
    
    let centerX = particlesCanvas.width / 2;
    let centerY = particlesCanvas.height / 2;
    let sphereRadius = 180;
    
    const ELECTRIC_BLUE = '0, 180, 255';
    const BRIGHT_BLUE = '100, 220, 255';
    const MOUSE_RADIUS_SQ = 22500;
    const MOUSE_RADIUS = 150;
    
    // Seguir el ratón
    let mouseUpdateScheduled = false;
    particlesCanvas.addEventListener('mousemove', (e) => {
        if (!mouseUpdateScheduled) {
            mouseUpdateScheduled = true;
            requestAnimationFrame(() => {
                mouse.x = e.clientX;
                mouse.y = e.clientY;
                mouseUpdateScheduled = false;
            });
        }
    });
    
    // Click para activar
    particlesCanvas.addEventListener('click', (e) => {
        const dx = e.clientX - targetCenterX;
        const dy = e.clientY - targetCenterY;
        const distance = Math.sqrt(dx * dx + dy * dy);

        if (distance < targetRadius * 1.2 && jarvisState === 'idle') {
            jarvisState = 'compact';
            targetRadius = 110;
            targetCompactness = 1.0;

            setTimeout(() => {
                showSearchBar();
            }, 400);
        }
    });
    
    // Mostrar barra de búsqueda
    function showSearchBar() {
        // Crear contenedor de chat
        chatContainer = document.createElement('div');
        chatContainer.id = 'chatContainer';
        document.body.appendChild(chatContainer);

        // Crear barra
        const searchBar = document.createElement('div');
        searchBar.id = 'jarvisSearchBar';

        const input = document.createElement('input');
        input.type = 'text';
        input.id = 'jarvisSearchInput';
        input.placeholder = 'Pregúntame lo que quieras...';

        // Botón de micrófono
        const micBtn = document.createElement('button');
        micBtn.id = 'jarvisMicBtn';
        micBtn.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/><path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/></svg>';

        // Botón de enviar
        const sendBtn = document.createElement('button');
        sendBtn.id = 'jarvisSendBtn';
        sendBtn.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>';

        searchBar.appendChild(input);
        searchBar.appendChild(sendBtn);
        searchBar.appendChild(micBtn);
        document.body.appendChild(searchBar);

        // Animación de entrada
        setTimeout(() => {
            searchBar.style.opacity = '1';
            searchBar.style.transform = 'translateX(-50%) scale(1)';
        }, 50);

        // --- Micrófono ---
        let mediaRecorder = null;
        let audioChunks = [];
        let isRecording = false;

        micBtn.addEventListener('click', async () => {
            if (isRecording) {
                // Parar grabación
                mediaRecorder.stop();
                return;
            }

            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
                audioChunks = [];

                mediaRecorder.ondataavailable = (e) => {
                    if (e.data.size > 0) audioChunks.push(e.data);
                };

                mediaRecorder.onstop = async () => {
                    isRecording = false;
                    micBtn.classList.remove('recording');
                    stream.getTracks().forEach(t => t.stop());

                    const blob = new Blob(audioChunks, { type: 'audio/webm' });
                    if (blob.size < 1000) return;

                    // Enviar a transcribir
                    micBtn.classList.add('processing');
                    const formData = new FormData();
                    formData.append('audio', blob, 'recording.webm');

                    try {
                        const res = await fetch('/transcribe', { method: 'POST', body: formData });
                        const data = await res.json();
                        if (data.ok && data.text) {
                            input.value = data.text;
                            input.dispatchEvent(new Event('input'));
                            input.focus();
                        }
                    } catch (err) {
                        console.error('Error transcribiendo:', err);
                    }
                    micBtn.classList.remove('processing');
                };

                mediaRecorder.start();
                isRecording = true;
                micBtn.classList.add('recording');
            } catch (err) {
                console.error('Error accediendo al micrófono:', err);
            }
        });

        // Eventos del input y enviar
        sendBtn.addEventListener('click', () => {
            if (input.value.trim()) {
                sendMessageToJarvis(input.value.trim());
                input.value = '';
                isTyping = false;
            }
        });

        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && input.value.trim()) {
                sendMessageToJarvis(input.value.trim());
                input.value = '';
                isTyping = false;
            }
        });

        input.addEventListener('input', () => {
            if (input.value.length > 0) {
                isTyping = true;
                if (jarvisState === 'compact') {
                    jarvisState = 'active';
                    targetCenterX = 70;
                    targetCenterY = 70;
                    targetRadius = 40;
                    chatContainer.classList.add('active');
                }
            } else {
                isTyping = false;
            }
        });

        setTimeout(() => input.focus(), 100);

        // Mostrar briefing si llegó antes de abrir el chat
        if (window._pendingBriefing && window.showBriefing) {
            setTimeout(() => {
                window.showBriefing(window._pendingBriefing);
                window._pendingBriefing = null;
            }, 300);
        }

        // Iniciar escucha de wake word
        initWakeWordDetection(input);
    }

    // Wake word detection usando Web Speech API
    function initWakeWordDetection(inputElement) {
        if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
            console.log('⚠️ Web Speech API no disponible');
            return;
        }

        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        recognition = new SpeechRecognition();
        recognition.continuous = true;
        recognition.interimResults = false;
        recognition.lang = 'es-ES';

        recognition.onresult = (event) => {
            const last = event.results.length - 1;
            const transcript = event.results[last][0].transcript.toLowerCase().trim();

            console.log('🎤 Escuchado:', transcript);

            // Detectar wake word "jarvis"
            if (transcript.includes('jarvis')) {
                console.log('✅ Wake word detectado!');

                // Detener reconocimiento continuo
                if (isWakeWordListening) {
                    recognition.stop();
                    isWakeWordListening = false;
                }

                // Activar micrófono para comando
                const micBtn = document.getElementById('jarvisMicBtn');
                if (micBtn) {
                    micBtn.click();
                }
            }
        };

        recognition.onend = () => {
            // Reiniciar automáticamente si estaba escuchando
            if (isWakeWordListening) {
                try {
                    recognition.start();
                } catch (e) {
                    console.log('Wake word ya está activo');
                }
            }
        };

        recognition.onerror = (event) => {
            if (event.error !== 'no-speech' && event.error !== 'aborted') {
                console.error('Error reconocimiento:', event.error);
            }
        };

        // Botón para activar/desactivar wake word
        const wakeBtn = document.createElement('button');
        wakeBtn.id = 'jarvisWakeBtn';
        wakeBtn.className = 'wake-word-btn';
        wakeBtn.title = 'Escuchar "Jarvis"';
        wakeBtn.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm0 10.99h7c-.53 4.12-3.28 7.79-7 8.94V12H5V6.3l7-3.11v8.8z"/></svg>';

        wakeBtn.addEventListener('click', () => {
            if (isWakeWordListening) {
                // Detener
                recognition.stop();
                isWakeWordListening = false;
                wakeBtn.classList.remove('active');
                console.log('🛑 Wake word desactivado');
            } else {
                // Iniciar
                try {
                    recognition.start();
                    isWakeWordListening = true;
                    wakeBtn.classList.add('active');
                    console.log('🎤 Escuchando "Jarvis"...');
                } catch (e) {
                    console.log('Wake word ya está activo');
                }
            }
        });

        // Agregar botón a la barra de búsqueda
        const searchBar = document.getElementById('jarvisSearchBar');
        if (searchBar) {
            searchBar.appendChild(wakeBtn);
        }
    }

    // Indicador de "pensando" + streaming bubble
    let thinkingEl = null;
    let streamingEl = null;    // bubble activo durante streaming
    let streamingText = '';    // acumulador de texto

    function showThinking() {
        if (!chatContainer || thinkingEl) return;
        thinkingEl = document.createElement('div');
        thinkingEl.className = 'message assistant thinking';
        thinkingEl.innerHTML = '<div class="thinking-dots"><span></span><span></span><span></span></div>';
        chatContainer.appendChild(thinkingEl);
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }
    function hideThinking() {
        if (thinkingEl) {
            thinkingEl.remove();
            thinkingEl = null;
        }
    }

    // Inicia un bubble de streaming (reemplaza el thinking)
    function startStreamBubble() {
        hideThinking();
        if (streamingEl) return;

        streamingText = '';
        streamingEl = document.createElement('div');
        streamingEl.className = 'message assistant streaming';

        const textEl = document.createElement('span');
        textEl.className = 'stream-text';
        streamingEl.appendChild(textEl);

        // Cursor parpadeante
        const cursor = document.createElement('span');
        cursor.className = 'stream-cursor';
        cursor.textContent = '▋';
        streamingEl.appendChild(cursor);

        chatContainer.appendChild(streamingEl);
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    // Añade un chunk al bubble de streaming
    function appendStreamChunk(chunk) {
        if (!streamingEl) startStreamBubble();
        streamingText += chunk;
        const textEl = streamingEl.querySelector('.stream-text');
        if (textEl) {
            textEl.innerHTML = renderContent(streamingText);
            // MathJax si aplica
            if (window.MathJax && MathJax.typesetPromise) {
                MathJax.typesetPromise([textEl]).catch(() => {});
            }
        }
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    // Finaliza el bubble de streaming (quita cursor, añade botones)
    function finishStreamBubble() {
        if (!streamingEl) return;

        // Quitar cursor
        const cursor = streamingEl.querySelector('.stream-cursor');
        if (cursor) cursor.remove();

        // Añadir multiline class si aplica
        const isMultiline = streamingText.includes('\n') || streamingText.length > 80;
        if (isMultiline) streamingEl.classList.add('multiline');
        streamingEl.classList.remove('streaming');

        // Botón copiar
        const copyBtn = document.createElement('button');
        copyBtn.className = 'msg-copy-btn';
        copyBtn.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>';
        const capturedText = streamingText;
        copyBtn.addEventListener('click', () => {
            navigator.clipboard.writeText(capturedText).then(() => {
                copyBtn.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/></svg>';
                setTimeout(() => {
                    copyBtn.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>';
                }, 1500);
            });
        });

        // Botón TTS
        const ttsBtn = document.createElement('button');
        ttsBtn.className = 'msg-tts-btn';
        ttsBtn.title = 'Escuchar mensaje';
        ttsBtn.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>';
        ttsBtn.addEventListener('click', () => speakText(capturedText, ttsBtn));

        streamingEl.appendChild(copyBtn);
        streamingEl.appendChild(ttsBtn);

        streamingEl = null;
        streamingText = '';
        isTyping = false;
    }

    // Enviar mensaje
    function sendMessageToJarvis(message) {
        console.log('📤 Enviando:', message);

        // Mostrar mensaje del usuario
        addMessage(message, 'user');

        if (isConnected && ws) {
            ws.send(JSON.stringify({ message }));
            isTyping = true;
            showThinking();
        } else {
            console.log('❌ WebSocket no conectado');
            setTimeout(() => {
                addMessage('WebSocket no está conectado. Asegúrate de que el servidor esté corriendo.', 'assistant');
                isTyping = false;
            }, 500);
        }
    }

    // Mostrar briefing de bienvenida
    window.showBriefing = function(data) {
        if (!chatContainer) return;
        const { greeting, time, date, system } = data;

        let sysText = '';
        if (system && Object.keys(system).length > 0) {
            const parts = [];
            if (system.cpu_pct !== undefined) parts.push(`CPU ${system.cpu_pct}%`);
            if (system.ram_pct !== undefined) parts.push(`RAM ${system.ram_pct}%`);
            if (system.battery_pct !== undefined) {
                const plug = system.battery_plugged ? '⚡' : '🔋';
                parts.push(`${plug} ${system.battery_pct}%`);
            }
            if (parts.length > 0) sysText = ` | ${parts.join(' · ')}`;
        }

        const content = `**${greeting}, señor.** Son las ${time} del ${date}.${sysText}\n\nTodos los sistemas operativos. ¿En qué puedo asistirle?`;
        addMessage(content, 'assistant briefing');
    };
    
    // TTS: Hablar texto usando el servidor
    async function speakText(text, button) {
        try {
            if (button) {
                button.classList.add('speaking');
                button.disabled = true;
            }

            const response = await fetch('/speak', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text })
            });

            const data = await response.json();

            if (!data.ok) {
                console.error('Error TTS:', data.error);
            }
        } catch (error) {
            console.error('Error llamando TTS:', error);
        } finally {
            if (button) {
                button.classList.remove('speaking');
                button.disabled = false;
            }
        }
    }

    // Renderizar contenido: Markdown + MathJax
    function renderContent(text) {
        let html = text;

        // 1) Proteger bloques LaTeX antes de markdown
        const latexBlocks = [];
        // $$...$$
        html = html.replace(/\$\$([\s\S]*?)\$\$/g, (_, expr) => {
            const placeholder = `%%LATEX_BLOCK_${latexBlocks.length}%%`;
            latexBlocks.push({ expr: expr.trim(), display: true });
            return placeholder;
        });
        // $...$
        html = html.replace(/\$([^\$\n]+?)\$/g, (_, expr) => {
            const placeholder = `%%LATEX_BLOCK_${latexBlocks.length}%%`;
            latexBlocks.push({ expr: expr.trim(), display: false });
            return placeholder;
        });
        // \[...\] y \(...\)
        html = html.replace(/\\\[([\s\S]*?)\\\]/g, (_, expr) => {
            const placeholder = `%%LATEX_BLOCK_${latexBlocks.length}%%`;
            latexBlocks.push({ expr: expr.trim(), display: true });
            return placeholder;
        });
        html = html.replace(/\\\(([\s\S]*?)\\\)/g, (_, expr) => {
            const placeholder = `%%LATEX_BLOCK_${latexBlocks.length}%%`;
            latexBlocks.push({ expr: expr.trim(), display: false });
            return placeholder;
        });

        // 2) Markdown → HTML
        if (typeof marked !== 'undefined') {
            marked.setOptions({ breaks: true, gfm: true });
            html = marked.parse(html);
        } else {
            html = html
                .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                .replace(/\*(.+?)\*/g, '<em>$1</em>')
                .replace(/\n/g, '<br>');
        }

        // 3) Restaurar bloques LaTeX con delimitadores para MathJax
        for (let i = 0; i < latexBlocks.length; i++) {
            const { expr, display } = latexBlocks[i];
            const wrapped = display ? `$$${expr}$$` : `$${expr}$`;
            html = html.replace(`%%LATEX_BLOCK_${i}%%`, wrapped);
        }

        return html;
    }

    // Agregar mensaje al chat
    function addMessage(content, type) {
        if (!chatContainer) return;

        const msgEl = document.createElement('div');
        msgEl.className = `message ${type}`;

        const textEl = document.createElement('span');
        textEl.innerHTML = renderContent(content);

        const copyBtn = document.createElement('button');
        copyBtn.className = 'msg-copy-btn';
        copyBtn.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>';
        copyBtn.addEventListener('click', () => {
            navigator.clipboard.writeText(content).then(() => {
                copyBtn.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/></svg>';
                setTimeout(() => {
                    copyBtn.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/></svg>';
                }, 1500);
            });
        });

        // Botón TTS solo para mensajes del asistente
        let ttsBtn = null;
        if (type === 'assistant') {
            ttsBtn = document.createElement('button');
            ttsBtn.className = 'msg-tts-btn';
            ttsBtn.title = 'Escuchar mensaje';
            ttsBtn.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>';
            ttsBtn.addEventListener('click', () => speakText(content, ttsBtn));
        }

        // Multilínea: botón abajo-derecha; una línea: centrado vertical
        const isMultiline = content.includes('\n') || content.length > 80;
        if (isMultiline) {
            msgEl.classList.add('multiline');
        }

        msgEl.appendChild(textEl);
        msgEl.appendChild(copyBtn);
        if (ttsBtn) {
            msgEl.appendChild(ttsBtn);
        }
        chatContainer.appendChild(msgEl);

        // MathJax: procesar LaTeX en el mensaje recién añadido
        if (window.MathJax && MathJax.typesetPromise) {
            MathJax.typesetPromise([msgEl]).catch(() => {});
        }

        chatContainer.scrollTop = chatContainer.scrollHeight;
    }
    
    // Exponer funciones globalmente para el WebSocket handler
    window.receiveJarvisMessage = function(content) {
        hideThinking();
        finishStreamBubble();
        addMessage(content, 'assistant');
        isTyping = false;
    };

    window.appendStreamChunk = function(chunk) {
        appendStreamChunk(chunk);
    };

    window.finishStreamBubble = function() {
        finishStreamBubble();
    };
    
    // Clase de partícula de esfera
    class SphereParticle {
        constructor(index) {
            const phi = Math.acos(1 - 2 * (index + 0.5) / sphereParticleCount);
            const theta = Math.PI * (1 + Math.sqrt(5)) * index;

            this.perfectX = Math.cos(theta) * Math.sin(phi);
            this.perfectY = Math.sin(theta) * Math.sin(phi);
            this.perfectZ = Math.cos(phi);

            this.baseX = this.perfectX;
            this.baseY = this.perfectY;
            this.baseZ = this.perfectZ;
            this.x = this.baseX;
            this.y = this.baseY;
            this.z = this.baseZ;

            this.size = Math.random() * 0.8 + 0.5;
            this.isSphere = true;

            // Transición individual - velocidad MUY variada para dispersión
            this.localCenterX = targetCenterX;
            this.localCenterY = targetCenterY;
            this.localRadius = targetRadius;
            // Distribución amplia: pocas muy rápidas, muchas medianas, algunas rezagadas
            const r = Math.random();
            this.transitionSpeed = 0.015 + r * r * 0.12;
            // Desvío curvo: ángulo aleatorio y magnitud grande → caminos muy distintos
            const deviationAngle = Math.random() * Math.PI * 2;
            const deviationMag = Math.random() * 350 + 100;
            this.pathDeviationX = Math.cos(deviationAngle) * deviationMag;
            this.pathDeviationY = Math.sin(deviationAngle) * deviationMag;
            // Cada partícula tiene su propia "curva" (cuántas oscilaciones hace en el camino)
            this.pathWobbleFreq = Math.random() * 2 + 0.5;
            this.pathPhase = 0;

            // Movimiento orgánico (ondas superpuestas) - más rápido en idle
            this.driftPhaseX1 = Math.random() * Math.PI * 2;
            this.driftPhaseX2 = Math.random() * Math.PI * 2;
            this.driftPhaseY1 = Math.random() * Math.PI * 2;
            this.driftPhaseY2 = Math.random() * Math.PI * 2;
            this.driftPhaseZ1 = Math.random() * Math.PI * 2;
            this.driftPhaseZ2 = Math.random() * Math.PI * 2;
            this.driftFreqX1 = Math.random() * 0.018 + 0.006;
            this.driftFreqX2 = Math.random() * 0.028 + 0.012;
            this.driftFreqY1 = Math.random() * 0.016 + 0.006;
            this.driftFreqY2 = Math.random() * 0.025 + 0.01;
            this.driftFreqZ1 = Math.random() * 0.014 + 0.005;
            this.driftFreqZ2 = Math.random() * 0.022 + 0.008;
            this.driftAmplitude = Math.random() * 0.08 + 0.03;

            // Rotación - un poco más rápida
            this.rotSpeedY = (Math.random() - 0.5) * 0.0008;
            this.rotSpeedX = (Math.random() - 0.5) * 0.0006;
            this.rotY = Math.random() * Math.PI * 2;
            this.rotX = Math.random() * Math.PI * 2;
            this.pulseOffset = Math.random() * Math.PI * 2;
            this.pulseSpeed = Math.random() * 0.004 + 0.001;

            this.screenX = 0;
            this.screenY = 0;
            this.scale = 1;
        }

        update(time) {
            // Cada partícula interpola hacia el target a su propio ritmo
            const dx = targetCenterX - this.localCenterX;
            const dy = targetCenterY - this.localCenterY;
            const dist = Math.sqrt(dx * dx + dy * dy);

            if (dist > 10) {
                // En transición: camino curvo y sinuoso
                this.pathPhase += this.transitionSpeed * 0.8;
                const wobble = Math.sin(this.pathPhase * Math.PI * this.pathWobbleFreq);
                const distFactor = Math.min(dist / 100, 1);
                // Velocidad mínima para que las últimas no se arrastren
                const speed = Math.max(this.transitionSpeed, 0.04);
                this.localCenterX += dx * speed + this.pathDeviationX * wobble * speed * distFactor * 0.5;
                this.localCenterY += dy * speed + this.pathDeviationY * wobble * speed * distFactor * 0.5;
            } else if (dist > 0.5) {
                // Cerca del destino: snap rápido sin curvas
                this.localCenterX += dx * 0.15;
                this.localCenterY += dy * 0.15;
            }
            this.localRadius += (targetRadius - this.localRadius) * Math.max(this.transitionSpeed, 0.04) * 1.5;

            // Movimiento orgánico con ondas superpuestas
            const driftX = Math.sin(time * this.driftFreqX1 + this.driftPhaseX1) * this.driftAmplitude
                         + Math.sin(time * this.driftFreqX2 + this.driftPhaseX2) * this.driftAmplitude * 0.5;
            const driftY = Math.sin(time * this.driftFreqY1 + this.driftPhaseY1) * this.driftAmplitude
                         + Math.sin(time * this.driftFreqY2 + this.driftPhaseY2) * this.driftAmplitude * 0.5;
            const driftZ = Math.sin(time * this.driftFreqZ1 + this.driftPhaseZ1) * this.driftAmplitude * 0.7
                         + Math.sin(time * this.driftFreqZ2 + this.driftPhaseZ2) * this.driftAmplitude * 0.35;

            const imperfection = 1 - currentCompactness;

            this.baseX = this.perfectX + driftX * (0.3 + imperfection * 2);
            this.baseY = this.perfectY + driftY * (0.3 + imperfection * 2);
            this.baseZ = this.perfectZ + driftZ * (0.3 + imperfection * 2);

            // Rotación
            this.rotY += this.rotSpeedY;
            this.rotX += this.rotSpeedX;

            const cosY = Math.cos(this.rotY);
            const sinY = Math.sin(this.rotY);
            const cosX = Math.cos(this.rotX);
            const sinX = Math.sin(this.rotX);

            const rx = this.baseX * cosY - this.baseZ * sinY;
            const rz = this.baseX * sinY + this.baseZ * cosY;
            const ry = this.baseY * cosX - rz * sinX;
            const finalZ = this.baseY * sinX + rz * cosX;

            this.x = rx;
            this.y = ry;
            this.z = finalZ;

            // Proyección con posición local
            this.scale = 300 / (300 + this.z * this.localRadius);
            this.screenX = this.localCenterX + this.x * this.localRadius * this.scale;
            this.screenY = this.localCenterY + this.y * this.localRadius * this.scale;

            // Reacción sutil al ratón - TODAS las partículas, siempre
            const mdx = mouse.x - this.screenX;
            const mdy = mouse.y - this.screenY;
            const mDistSq = mdx * mdx + mdy * mdy;

            if (mDistSq < MOUSE_RADIUS_SQ && mDistSq > 1) {
                const mDist = Math.sqrt(mDistSq);
                const force = (MOUSE_RADIUS - mDist) / MOUSE_RADIUS;
                const angle = Math.atan2(mdy, mdx);
                // Empuje suave: se apartan un poco del cursor
                this.screenX -= Math.cos(angle) * force * force * 8;
                this.screenY -= Math.sin(angle) * force * force * 8;
            }

            this.pulseOffset += this.pulseSpeed;
        }

        draw() {
            const size = this.size * this.scale;
            const depth = (this.z + 1) * 0.5;
            const mdx = mouse.x - this.screenX;
            const mdy = mouse.y - this.screenY;
            const mouseDist = Math.sqrt(mdx * mdx + mdy * mdy);

            let opacity = 0.7 + depth * 0.2;
            opacity += Math.sin(this.pulseOffset) * 0.25;

            if (mouseDist < 200) {
                opacity += (200 - mouseDist) * 0.002;
            }
            opacity = Math.min(opacity, 1);

            const size2 = size * 1.5;
            const size3 = size * 2.5;

            ctx.globalAlpha = opacity * 0.3;
            ctx.fillStyle = `rgb(${ELECTRIC_BLUE})`;
            ctx.beginPath();
            ctx.arc(this.screenX, this.screenY, size3, 0, Math.PI * 2);
            ctx.fill();

            ctx.globalAlpha = opacity * 0.7;
            ctx.fillStyle = `rgb(${BRIGHT_BLUE})`;
            ctx.beginPath();
            ctx.arc(this.screenX, this.screenY, size2, 0, Math.PI * 2);
            ctx.fill();

            ctx.globalAlpha = opacity;
            ctx.fillStyle = 'rgb(255, 255, 255)';
            ctx.beginPath();
            ctx.arc(this.screenX, this.screenY, size, 0, Math.PI * 2);
            ctx.fill();

            ctx.globalAlpha = 1;
        }
    }
    
    class FloatingParticle {
        constructor() {
            this.x = Math.random() * particlesCanvas.width;
            this.y = Math.random() * particlesCanvas.height;
            this.baseX = this.x;
            this.baseY = this.y;
            this.size = Math.random() * 0.8 + 0.5;
            this.speedX = (Math.random() - 0.5) * 0.15;
            this.speedY = (Math.random() - 0.5) * 0.15;
            this.angle = Math.random() * Math.PI * 2;
            this.angleSpeed = (Math.random() - 0.5) * 0.003;
            this.orbitRadius = Math.random() * 5 + 2;
            this.opacity = Math.random() * 0.2 + 0.25;
            this.isSphere = false;
            this.pulseOffset = Math.random() * Math.PI * 2;
            this.pulseSpeed = Math.random() * 0.004 + 0.001;
        }

        update() {
            this.baseX += this.speedX;
            this.baseY += this.speedY;
            this.angle += this.angleSpeed;
            this.pulseOffset += this.pulseSpeed;

            this.x = this.baseX + Math.cos(this.angle) * this.orbitRadius;
            this.y = this.baseY + Math.sin(this.angle) * this.orbitRadius;

            // Reacción sutil al cursor
            const dx = mouse.x - this.x;
            const dy = mouse.y - this.y;
            const distSq = dx * dx + dy * dy;
            if (distSq < 40000 && distSq > 1) {
                const dist = Math.sqrt(distSq);
                const force = (200 - dist) / 200;
                const angle = Math.atan2(dy, dx);
                this.x -= Math.cos(angle) * force * force * 5;
                this.y -= Math.sin(angle) * force * force * 5;
            }

            // Wrap suave por los bordes
            if (this.baseX < -50) this.baseX = particlesCanvas.width + 50;
            if (this.baseX > particlesCanvas.width + 50) this.baseX = -50;
            if (this.baseY < -50) this.baseY = particlesCanvas.height + 50;
            if (this.baseY > particlesCanvas.height + 50) this.baseY = -50;
        }

        draw() {
            const pulse = Math.sin(this.pulseOffset) * 0.08;
            const finalOpacity = this.opacity + pulse;

            // Glow exterior
            ctx.globalAlpha = finalOpacity * 0.3;
            ctx.fillStyle = `rgb(${ELECTRIC_BLUE})`;
            ctx.beginPath();
            ctx.arc(this.x, this.y, this.size * 3, 0, Math.PI * 2);
            ctx.fill();

            // Punto principal - siempre encendido
            ctx.globalAlpha = finalOpacity;
            ctx.fillStyle = `rgb(${BRIGHT_BLUE})`;
            ctx.beginPath();
            ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
            ctx.fill();

            ctx.globalAlpha = 1;
        }
    }
    
    // Crear partículas
    for (let i = 0; i < sphereParticleCount; i++) {
        particles.push(new SphereParticle(i));
    }
    for (let i = 0; i < floatingParticleCount; i++) {
        particles.push(new FloatingParticle());
    }
    
    const sphereParticles = particles.filter(p => p.isSphere);
    const floatingParticles = particles.filter(p => !p.isSphere);
    
    // Animar
    let time = 0;
    function animateParticles() {
        time++;

        // Compactness global (afecta el drift orgánico)
        currentCompactness += (targetCompactness - currentCompactness) * 0.008;

        ctx.clearRect(0, 0, particlesCanvas.width, particlesCanvas.height);
        
        if (time % 2 === 0) {
            ctx.globalAlpha = 1;
            for (let i = 0; i < sphereParticles.length; i += 8) {
                const p1 = sphereParticles[i];
                
                for (let j = i + 1; j < Math.min(i + 2, sphereParticles.length); j++) {
                    const p2 = sphereParticles[j];
                    const dx = p1.x - p2.x;
                    const dy = p1.y - p2.y;
                    const dz = p1.z - p2.z;
                    const dist3D = dx * dx + dy * dy + dz * dz;
                    
                    if (dist3D < 0.09) {
                        ctx.strokeStyle = `rgba(${ELECTRIC_BLUE}, 0.1)`;
                        ctx.lineWidth = 0.5;
                        ctx.beginPath();
                        ctx.moveTo(p1.screenX, p1.screenY);
                        ctx.lineTo(p2.screenX, p2.screenY);
                        ctx.stroke();
                    }
                }
            }
        }
        
        sphereParticles.sort((a, b) => a.z - b.z);
        
        for (let i = 0; i < sphereParticles.length; i++) {
            sphereParticles[i].update(time);
            sphereParticles[i].draw();
        }
        
        for (let i = 0; i < floatingParticles.length; i++) {
            floatingParticles[i].update();
            floatingParticles[i].draw();
        }
        
        requestAnimationFrame(animateParticles);
    }
    
    animateParticles();
    
    window.addEventListener('resize', () => {
        particlesCanvas.width = window.innerWidth;
        particlesCanvas.height = window.innerHeight;
    });
}

// ============================================
// WEBSOCKET
// ============================================

function connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;
    
    try {
        ws = new WebSocket(wsUrl);
        ws.onopen = () => { 
            isConnected = true;
            console.log('✅ WebSocket conectado');
        };
        ws.onclose = () => { 
            isConnected = false;
            console.log('❌ WebSocket desconectado - reintentando...');
            setTimeout(connect, 3000);
        };
        ws.onmessage = handleMessage;
        ws.onerror = (error) => {
            console.error('❌ WebSocket error:', error);
        };
    } catch (error) {
        console.error('❌ WebSocket connection error:', error);
        setTimeout(connect, 3000);
    }
}

function handleMessage(event) {
    try {
        const data = JSON.parse(event.data);

        switch (data.type) {
            case 'briefing':
                // Briefing proactivo al conectar — mostrar solo si hay chatContainer
                if (chatContainer && window.showBriefing) {
                    window.showBriefing(data.data);
                } else {
                    // Guardar para mostrar cuando el chat esté listo
                    window._pendingBriefing = data.data;
                }
                break;

            case 'token':
                // Chunk de streaming: acumular en bubble activo
                if (window.appendStreamChunk) {
                    window.appendStreamChunk(data.content);
                }
                break;

            case 'done':
                // Fin del streaming: finalizar bubble
                if (window.finishStreamBubble) {
                    window.finishStreamBubble();
                }
                break;

            case 'assistant_message':
                // Mensaje completo (fallback sin streaming)
                if (window.receiveJarvisMessage) {
                    window.receiveJarvisMessage(data.content);
                }
                break;

            case 'error':
                if (window.receiveJarvisMessage) {
                    window.receiveJarvisMessage(`⚠️ ${data.content}`);
                }
                break;

            default:
                console.log('📥 Mensaje desconocido:', data);
        }
    } catch (error) {
        console.error('❌ Error procesando mensaje:', error);
    }
}

console.log('✨ JARVIS - All systems operational');
