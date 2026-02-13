// JARVIS - JavaScript con Nube de Puntos 3D Interactiva Ultra Optimizada
let currentView = 'home';
let ws = null;
let isConnected = false;

// DOM Elements
const particlesCanvas = document.getElementById('particles');
const chatInput = document.getElementById('chatInput');
const sendBtn = document.getElementById('sendBtn');
const messagesList = document.getElementById('messagesList');
const typingIndicator = document.getElementById('typingIndicator');

// ============================================
// INICIALIZACIÓN
// ============================================

document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 JARVIS UI Loaded');
    initInteractiveParticles();
    setupEventListeners();
    positionOrbitalMenu();
    connect();
});

// ============================================
// NUBE DE PUNTOS 3D INTERACTIVA ULTRA OPTIMIZADA
// ============================================

function initInteractiveParticles() {
    if (!particlesCanvas) return;
    
    const ctx = particlesCanvas.getContext('2d');
    particlesCanvas.width = window.innerWidth;
    particlesCanvas.height = window.innerHeight;
    
    const particles = [];
    const sphereParticleCount = 1200;
    const floatingParticleCount = 200;
    let mouse = { x: particlesCanvas.width / 2, y: particlesCanvas.height / 2 };
    
    // Estados de JARVIS
    let jarvisState = 'idle'; // idle, compact, active
    let targetCenterX = particlesCanvas.width / 2;
    let targetCenterY = particlesCanvas.height / 2;
    let currentCenterX = targetCenterX;
    let currentCenterY = targetCenterY;
    let targetRadius = 180;
    let currentRadius = 180;
    let targetCompactness = 0.8;
    let currentCompactness = 0.8;
    let isTyping = false;
    let typingVibration = 0;
    
    // Centro de la esfera
    let centerX = particlesCanvas.width / 2;
    let centerY = particlesCanvas.height / 2;
    let sphereRadius = 180;
    
    // Azul eléctrico
    const ELECTRIC_BLUE = '0, 180, 255';
    const BRIGHT_BLUE = '100, 220, 255';
    
    // Precalcular constantes
    const MOUSE_RADIUS_SQ = 22500;
    const MOUSE_RADIUS = 150;
    
    // Seguir el ratón (throttled)
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
    
    // Click en el canvas para activar JARVIS
    particlesCanvas.addEventListener('click', (e) => {
        const dx = e.clientX - currentCenterX;
        const dy = e.clientY - currentCenterY;
        const distance = Math.sqrt(dx * dx + dy * dy);
        
        if (distance < currentRadius && jarvisState === 'idle') {
            jarvisState = 'compact';
            targetRadius = 150;
            targetCompactness = 1.0;
            
            setTimeout(() => {
                showSearchBar();
            }, 1500); // Más tiempo para ver la transición
        }
    });
    
    // Función para mostrar barra de búsqueda
    function showSearchBar() {
        const searchBar = document.createElement('div');
        searchBar.id = 'jarvisSearchBar';
        
        const input = document.createElement('input');
        input.type = 'text';
        input.id = 'jarvisSearchInput';
        input.placeholder = 'Pregúntame lo que quieras...';
        input.style.cssText = `
            width: 600px;
            max-width: 90%;
            padding: 15px 20px;
            font-size: 16px;
            background: rgba(0, 0, 0, 0.7);
            border: 2px solid rgba(0, 180, 255, 0.5);
            border-radius: 25px;
            color: white;
            outline: none;
            font-family: 'Inter', sans-serif;
            transition: all 1.2s cubic-bezier(0.23, 1, 0.32, 1);
            backdrop-filter: blur(10px);
        `;
        
        searchBar.style.cssText = `
            position: fixed;
            bottom: 40px;
            left: 50%;
            transform: translateX(-50%) translateY(20px);
            z-index: 1000;
            opacity: 0;
            transition: all 1.2s cubic-bezier(0.23, 1, 0.32, 1);
        `;
        
        searchBar.appendChild(input);
        document.body.appendChild(searchBar);
        
        // Animación de entrada MUY suave
        requestAnimationFrame(() => {
            setTimeout(() => {
                searchBar.style.opacity = '1';
                searchBar.style.transform = 'translateX(-50%) translateY(0)';
            }, 50);
        });
        
        // Enviar mensaje al presionar Enter
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && input.value.trim()) {
                sendMessageToJarvis(input.value.trim());
                input.value = '';
                isTyping = false;
            }
        });
        
        // Activar cuando empieza a escribir
        input.addEventListener('input', () => {
            if (input.value.length > 0) {
                isTyping = true;
                if (jarvisState === 'compact') {
                    jarvisState = 'active';
                    targetCenterX = 120;
                    targetCenterY = 120;
                    targetRadius = 60;
                }
            } else {
                isTyping = false;
            }
        });
        
        input.addEventListener('focus', () => {
            input.style.borderColor = 'rgba(0, 180, 255, 1)';
            input.style.boxShadow = '0 0 20px rgba(0, 180, 255, 0.5)';
        });
        
        input.addEventListener('blur', () => {
            input.style.borderColor = 'rgba(0, 180, 255, 0.5)';
            input.style.boxShadow = 'none';
        });
        
        setTimeout(() => input.focus(), 100);
    }
    
    // Función para enviar mensaje a JARVIS
    function sendMessageToJarvis(message) {
        console.log('Enviando mensaje:', message);
        
        if (isConnected && ws) {
            ws.send(JSON.stringify({ message }));
            isTyping = false;
            
            // Mostrar indicador de que JARVIS está procesando
            setTimeout(() => {
                isTyping = true;
            }, 100);
        } else {
            console.log('WebSocket no conectado');
        }
    }
    
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
            
            this.interactsWithMouse = Math.random() > 0.6;
            
            // Vibración orgánica individual - MUY SUTIL
            this.vibrationPhase = Math.random() * Math.PI * 2;
            this.vibrationSpeed = Math.random() * 0.04 + 0.05; // MUY lento
            this.vibrationAmplitude = Math.random() * 0.8 + 0.4; // MUY pequeña
            
            this.noiseOffset = Math.random() * 1000;
            this.noiseSpeed = Math.random() * 0.0001 + 0.00005; // EXTREMADAMENTE lento
            this.rotSpeedY = (Math.random() - 0.5) * 0.0008; // EXTREMADAMENTE lento
            this.rotSpeedX = (Math.random() - 0.5) * 0.0006; // EXTREMADAMENTE lento
            this.rotY = Math.random() * Math.PI * 2;
            this.rotX = Math.random() * Math.PI * 2;
            this.reactionStrength = Math.random() * 0.8 + 0.4;
            this.pulseOffset = Math.random() * Math.PI * 2;
            this.pulseSpeed = Math.random() * 0.008 + 0.005; // MUY lento
            
            this.screenX = 0;
            this.screenY = 0;
            this.scale = 1;
        }
        
        update(time) {
            // Transiciones EXTREMADAMENTE SUAVES
            currentCenterX += (targetCenterX - currentCenterX) * 0.008; // MUY lento
            currentCenterY += (targetCenterY - currentCenterY) * 0.008; // MUY lento
            currentRadius += (targetRadius - currentRadius) * 0.008; // MUY lento
            currentCompactness += (targetCompactness - currentCompactness) * 0.005; // MUY lento
            
            centerX = currentCenterX;
            centerY = currentCenterY;
            sphereRadius = currentRadius;
            
            // Calcular posición base
            const imperfection = 1 - currentCompactness;
            const randomOffset = (Math.random() - 0.5) * imperfection;
            
            this.baseX = this.perfectX + randomOffset;
            this.baseY = this.perfectY + randomOffset * 0.8;
            this.baseZ = this.perfectZ + randomOffset * 0.6;
            
            // Vibración orgánica individual - MUY SUTIL
            let vibrationX = 0;
            let vibrationY = 0;
            let vibrationZ = 0;
            
            if (isTyping && jarvisState === 'active') {
                this.vibrationPhase += this.vibrationSpeed;
                vibrationX = Math.sin(this.vibrationPhase) * this.vibrationAmplitude * 0.008;
                vibrationY = Math.cos(this.vibrationPhase * 1.3) * this.vibrationAmplitude * 0.008;
                vibrationZ = Math.sin(this.vibrationPhase * 0.7) * this.vibrationAmplitude * 0.005;
            }
            
            // Rotaciones individuales
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
            
            const noise = Math.sin(time * this.noiseSpeed + this.noiseOffset) * 0.015; // MUY poco ruido
            
            this.x = rx + noise + vibrationX;
            this.y = ry + noise * 0.7 + vibrationY;
            this.z = finalZ + noise * 0.5 + vibrationZ;
            
            // Proyección 2D
            this.scale = 300 / (300 + this.z * sphereRadius);
            this.screenX = centerX + this.x * sphereRadius * this.scale;
            this.screenY = centerY + this.y * sphereRadius * this.scale;
            
            // Interacción con ratón
            if (this.interactsWithMouse && jarvisState === 'idle') {
                const dx = mouse.x - this.screenX;
                const dy = mouse.y - this.screenY;
                const distSq = dx * dx + dy * dy;
                
                if (distSq < MOUSE_RADIUS_SQ) {
                    const dist = Math.sqrt(distSq);
                    const force = (MOUSE_RADIUS - dist) / MOUSE_RADIUS;
                    const angle = Math.atan2(dy, dx);
                    const push = force * 0.4 * this.reactionStrength;
                    
                    this.x -= Math.cos(angle) * push * 0.3;
                    this.y -= Math.sin(angle) * push * 0.3;
                }
            }
            
            this.pulseOffset += this.pulseSpeed;
        }
        
        draw() {
            const size = this.size * this.scale;
            
            const depth = (this.z + 1) * 0.5;
            const dx = mouse.x - this.screenX;
            const dy = mouse.y - this.screenY;
            const mouseDist = Math.sqrt(dx * dx + dy * dy);
            
            let opacity = 0.7 + depth * 0.2;
            opacity += Math.sin(this.pulseOffset) * 0.25;
            
            if (mouseDist < 200) {
                opacity += (200 - mouseDist) * 0.002;
            }
            opacity = Math.min(opacity, 1);
            
            const size2 = size * 1.5;
            const size3 = size * 2.5;
            
            // Glow exterior
            ctx.globalAlpha = opacity * 0.3;
            ctx.fillStyle = `rgb(${ELECTRIC_BLUE})`;
            ctx.beginPath();
            ctx.arc(this.screenX, this.screenY, size3, 0, Math.PI * 2);
            ctx.fill();
            
            // Partícula principal
            ctx.globalAlpha = opacity * 0.7;
            ctx.fillStyle = `rgb(${BRIGHT_BLUE})`;
            ctx.beginPath();
            ctx.arc(this.screenX, this.screenY, size2, 0, Math.PI * 2);
            ctx.fill();
            
            // Núcleo brillante
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
            this.size = Math.random() * 1.2 + 0.4;
            this.speedX = (Math.random() - 0.5) * 0.15; // MUY lento
            this.speedY = (Math.random() - 0.5) * 0.15; // MUY lento
            this.angle = Math.random() * Math.PI * 2;
            this.angleSpeed = (Math.random() - 0.5) * 0.008; // MUY lento
            this.orbitRadius = Math.random() * 4 + 2;
            this.opacity = Math.random() * 0.3 + 0.5;
            this.isSphere = false;
            this.pulseOffset = Math.random() * Math.PI * 2;
            this.pulseSpeed = Math.random() * 0.01 + 0.005; // MUY lento
        }
        
        update() {
            this.baseX += this.speedX;
            this.baseY += this.speedY;
            this.angle += this.angleSpeed;
            this.pulseOffset += this.pulseSpeed;
            
            this.x = this.baseX + Math.cos(this.angle) * this.orbitRadius;
            this.y = this.baseY + Math.sin(this.angle) * this.orbitRadius;
            
            if (this.baseX < -50) this.baseX = particlesCanvas.width + 50;
            if (this.baseX > particlesCanvas.width + 50) this.baseX = -50;
            if (this.baseY < -50) this.baseY = particlesCanvas.height + 50;
            if (this.baseY > particlesCanvas.height + 50) this.baseY = -50;
        }
        
        draw() {
            const pulse = Math.sin(this.pulseOffset) * 0.25;
            const finalOpacity = Math.min(this.opacity + pulse, 1);
            const size2 = this.size * 2;
            
            ctx.globalAlpha = finalOpacity * 0.5;
            ctx.fillStyle = `rgb(${BRIGHT_BLUE})`;
            ctx.beginPath();
            ctx.arc(this.x, this.y, size2, 0, Math.PI * 2);
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
        ctx.clearRect(0, 0, particlesCanvas.width, particlesCanvas.height);
        
        // Conexiones
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
// ORBITAL MENU POSITIONING
// ============================================

function positionOrbitalMenu() {
    const menuItems = document.querySelectorAll('.menu-orbit-item');
    const radius = 200;
    const centerX = window.innerWidth / 2;
    const centerY = window.innerHeight / 2;
    const angleStep = (Math.PI * 2) / menuItems.length;
    
    menuItems.forEach((item, index) => {
        const angle = angleStep * index - Math.PI / 2;
        const x = centerX + Math.cos(angle) * radius;
        const y = centerY + Math.sin(angle) * radius;
        
        item.style.left = `${x}px`;
        item.style.top = `${y}px`;
    });
}

// ============================================
// EVENT LISTENERS
// ============================================

function setupEventListeners() {
    const menuItems = document.querySelectorAll('.menu-orbit-item');
    menuItems.forEach(item => {
        item.addEventListener('click', () => {
            const view = item.getAttribute('data-view');
            navigateToView(view);
            menuItems.forEach(mi => mi.classList.remove('active'));
            item.classList.add('active');
        });
    });
    
    if (chatInput) {
        chatInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                sendMessage();
            }
        });
    }
    
    if (sendBtn) {
        sendBtn.addEventListener('click', sendMessage);
    }
    
    const colorOptions = document.querySelectorAll('.color-option');
    colorOptions.forEach(option => {
        option.addEventListener('click', () => {
            const color = option.getAttribute('data-color');
            changeThemeColor(color);
            colorOptions.forEach(opt => opt.classList.remove('active'));
            option.classList.add('active');
        });
    });
}

// ============================================
// NAVIGATION
// ============================================

function navigateToView(viewName) {
    if (currentView === viewName) return;
    
    const currentViewEl = document.getElementById(`${currentView}View`);
    const newViewEl = document.getElementById(`${viewName}View`);
    
    if (!newViewEl) return;
    
    if (currentViewEl) {
        currentViewEl.classList.remove('active');
    }
    
    newViewEl.classList.add('active');
    currentView = viewName;
    
    if (viewName === 'chat' && chatInput) {
        setTimeout(() => chatInput.focus(), 300);
    }
}

window.navigateToView = navigateToView;

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
            console.log('❌ WebSocket desconectado');
            setTimeout(connect, 3000);
        };
        ws.onmessage = handleMessage;
    } catch (error) {
        console.error('WebSocket error:', error);
    }
}

function handleMessage(event) {
    try {
        const data = JSON.parse(event.data);
        
        if (data.type === 'assistant_message') {
            hideTypingIndicator();
            addAssistantMessage(data.content);
            
            // JARVIS deja de vibrar cuando termina de responder
            isTyping = false;
        }
    } catch (error) {
        console.error('Message error:', error);
    }
}

// ============================================
// CHAT FUNCTIONS
// ============================================

function sendMessage() {
    const message = chatInput.value.trim();
    if (!message) return;
    
    addUserMessage(message);
    chatInput.value = '';
    showTypingIndicator();
    
    if (isConnected && ws) {
        ws.send(JSON.stringify({ message }));
    } else {
        setTimeout(() => {
            hideTypingIndicator();
            addAssistantMessage('Demo mode - Backend not connected');
        }, 1000);
    }
}

function addUserMessage(content) {
    const msgEl = document.createElement('div');
    msgEl.className = 'message user-message';
    msgEl.innerHTML = `
        <div class="message-bubble">
            <p>${escapeHtml(content)}</p>
            <span class="message-time">${getTime()}</span>
        </div>
    `;
    messagesList.appendChild(msgEl);
    scrollToBottom(messagesList.parentElement);
}

function addAssistantMessage(content) {
    const msgEl = document.createElement('div');
    msgEl.className = 'message assistant-message';
    msgEl.innerHTML = `
        <div class="message-avatar">
            <div class="mini-orb"></div>
        </div>
        <div class="message-bubble">
            <p>${escapeHtml(content)}</p>
            <span class="message-time">${getTime()}</span>
        </div>
    `;
    messagesList.appendChild(msgEl);
    scrollToBottom(messagesList.parentElement);
}

function showTypingIndicator() {
    if (typingIndicator) typingIndicator.classList.add('active');
}

function hideTypingIndicator() {
    if (typingIndicator) typingIndicator.classList.remove('active');
}

// ============================================
// THEME
// ============================================

function changeThemeColor(color) {
    document.documentElement.style.setProperty('--primary', color);
}

// ============================================
// UTILITIES
// ============================================

function scrollToBottom(el) {
    if (!el) return;
    requestAnimationFrame(() => {
        el.scrollTop = el.scrollHeight;
    });
}

function getTime() {
    const now = new Date();
    return `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

console.log('✨ JARVIS - All systems operational');
