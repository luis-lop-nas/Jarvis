let ws = null;
let isConnected = false;
let mediaRecorder = null;
let audioChunks = [];

const messagesDiv = document.getElementById('messages');
const messageInput = document.getElementById('messageInput');
const sendButton = document.getElementById('sendButton');
const voiceButton = document.getElementById('voiceButton');
const statusText = document.getElementById('statusText');
const voiceStatus = document.getElementById('voiceStatus');

function connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;
    
    ws = new WebSocket(wsUrl);
    
    ws.onopen = () => {
        isConnected = true;
        statusText.textContent = 'Conectado';
        console.log('WebSocket conectado');
    };
    
    ws.onclose = () => {
        isConnected = false;
        statusText.textContent = 'Desconectado';
        console.log('WebSocket desconectado');
        setTimeout(connect, 3000);
    };
    
    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        addMessage('Error de conexión', 'error');
    };
    
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleMessage(data);
    };
}

function handleMessage(data) {
    switch (data.type) {
        case 'user_message':
            break;
            
        case 'assistant_message':
            removeTypingIndicator();
            addAssistantMessage(data.content);
            break;
            
        case 'error':
            removeTypingIndicator();
            addMessage(data.content, 'error');
            break;
    }
}

function addMessage(content, type) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${type}`;
    messageDiv.textContent = content;
    
    messagesDiv.appendChild(messageDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function addAssistantMessage(content) {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message assistant speaking';
    
    const textSpan = document.createElement('span');
    textSpan.textContent = content;
    
    const voiceDiv = document.createElement('div');
    voiceDiv.className = 'voice-animation';
    voiceDiv.innerHTML = `
        <div class="voice-bar"></div>
        <div class="voice-bar"></div>
        <div class="voice-bar"></div>
        <div class="voice-bar"></div>
        <div class="voice-bar"></div>
    `;
    
    messageDiv.appendChild(textSpan);
    messageDiv.appendChild(voiceDiv);
    
    messagesDiv.appendChild(messageDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
    
    setTimeout(() => {
        messageDiv.classList.remove('speaking');
    }, 3000);
}

function addTypingIndicator() {
    const typingDiv = document.createElement('div');
    typingDiv.className = 'typing-indicator active';
    typingDiv.id = 'typingIndicator';
    typingDiv.innerHTML = `
        <div class="typing-dots">
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
        </div>
    `;
    
    messagesDiv.appendChild(typingDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function removeTypingIndicator() {
    const indicator = document.getElementById('typingIndicator');
    if (indicator) {
        indicator.remove();
    }
}

function sendMessage() {
    const message = messageInput.value.trim();
    
    if (!message || !isConnected) {
        return;
    }
    
    addMessage(message, 'user');
    addTypingIndicator();
    
    ws.send(JSON.stringify({
        message: message
    }));
    
    messageInput.value = '';
    messageInput.focus();
}

// Voice recording
async function startRecording() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);
        audioChunks = [];
        
        mediaRecorder.ondataavailable = (event) => {
            audioChunks.push(event.data);
        };
        
        mediaRecorder.onstop = async () => {
            const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
            await sendAudioForTranscription(audioBlob);
            
            stream.getTracks().forEach(track => track.stop());
        };
        
        mediaRecorder.start();
        voiceButton.classList.add('recording');
        voiceStatus.textContent = '🎤 Grabando... (suelta para enviar)';
        
    } catch (error) {
        console.error('Error accediendo al micrófono:', error);
        voiceStatus.textContent = '❌ Error: No se puede acceder al micrófono';
        addMessage('No se pudo acceder al micrófono. Verifica los permisos del navegador.', 'error');
    }
}

function stopRecording() {
    if (mediaRecorder && mediaRecorder.state === 'recording') {
        mediaRecorder.stop();
        voiceButton.classList.remove('recording');
        voiceStatus.textContent = '⏳ Transcribiendo...';
    }
}

async function sendAudioForTranscription(audioBlob) {
    try {
        const formData = new FormData();
        formData.append('audio', audioBlob, 'recording.webm');
        
        const response = await fetch('/transcribe', {
            method: 'POST',
            body: formData
        });
        
        const result = await response.json();
        
        voiceStatus.textContent = '';
        
        if (result.ok && result.text) {
            const text = result.text.trim();
            
            if (text && text !== "No he detectado voz clara, intenta de nuevo") {
                // Enviar texto transcrito como mensaje
                messageInput.value = text;
                sendMessage();
            } else {
                addMessage('No se detectó voz clara. Intenta de nuevo.', 'error');
            }
        } else {
            addMessage(`Error: ${result.error || 'No se pudo transcribir'}`, 'error');
        }
        
    } catch (error) {
        console.error('Error enviando audio:', error);
        voiceStatus.textContent = '';
        addMessage('Error al procesar el audio', 'error');
    }
}

// Event listeners
sendButton.addEventListener('click', sendMessage);

messageInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

// Voice button - press and hold
voiceButton.addEventListener('mousedown', startRecording);
voiceButton.addEventListener('mouseup', stopRecording);
voiceButton.addEventListener('mouseleave', () => {
    if (mediaRecorder && mediaRecorder.state === 'recording') {
        stopRecording();
    }
});

// Touch events for mobile
voiceButton.addEventListener('touchstart', (e) => {
    e.preventDefault();
    startRecording();
});
voiceButton.addEventListener('touchend', (e) => {
    e.preventDefault();
    stopRecording();
});

connect();
