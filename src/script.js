// src/script.js
document.addEventListener('DOMContentLoaded', () => {
  const app = {
    // DOM references
    micToggle: document.getElementById('mic-toggle'),
    statusLabel: document.getElementById('voice-status'),
    waveformRing: document.querySelector('.waveform-ring'),
    speakerToggle: document.getElementById('speaker-toggle'),
    volumeMeter: document.getElementById('volume-meter'),
    clockEl: document.getElementById('clock'),
    chatLog: document.getElementById('chat-log'),
    userInput: document.getElementById('user-input'),
    sendBtn: document.getElementById('send-btn'),
    voiceToggleBtn: document.getElementById('voice-toggle-btn'),
    memoryList: document.getElementById('memory-list'),
    actionLog: document.querySelector('#action-log'),
    tabButtons: document.querySelectorAll('.tab-btn'),
    tabPanels: document.querySelectorAll('.tab-panel'),
    memoryMap: document.getElementById('memory-map'),

    // State
    isListening: false,
    isSpeaking: false,
    volumeLevel: 0,

    init() {
      this.bindEvents();
      this.startClock();
      this.loadSampleData();
    },

    bindEvents() {
      // Mic toggle
      this.micToggle.addEventListener('click', () => {
        this.isListening = !this.isListening;
        this.micToggle.classList.toggle('active', this.isListening);
        this.statusLabel.textContent = this.isListening ? 'Listening' : 'Idle';
        this.waveformRing.style.opacity = this.isListening ? '0.2' : '0';
        // Simulate volume animation
        if (this.isListening) this.animateVolume();
      });

      // Send message
      this.sendBtn.addEventListener('click', () => this.sendMessage());
      this.userInput.addEventListener('keypress', e => {
        if (e.key === 'Enter') this.sendBtn.click();
      });

      // Voice toggle button (placeholder)
      this.voiceToggleBtn.addEventListener('click', () => {
        alert('Voice input mode toggled (not implemented)');
      });

      // Tab switching
      this.tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
          const tab = btn.dataset.tab;
          this.tabButtons.forEach(b => b.classList.toggle('active', b === btn));
          this.tabPanels.forEach(p => p.classList.toggle('active', p.id === `panel-${tab}`));
        });
      });

      // Sample memory delete (demo)
      this.memoryList.addEventListener('click', e => {
        if (e.target.classList.contains('delete-btn')) {
          const li = e.target.closest('.memory-item');
          li.remove();
          this.logAction(`Deleted memory item`);
        }
      });
    },

    sendMessage() {
      const text = this.userInput.value.trim();
      if (!text) return;
      this.addMessage('user', text);
      this.userInput.value = '';
      // Show thinking animation
      if (this.memoryMap) {
        this.memoryMap.classList.add('thinking');
        this.memoryMap.classList.remove('speaking');
      }
      // Simulate bot reply after delay
      setTimeout(() => {
        const reply = this.mockBotResponse(text);
        this.addMessage('assistant', reply);
        // Stop thinking, start speaking
        if (this.memoryMap) {
          this.memoryMap.classList.remove('thinking');
          this.memoryMap.classList.add('speaking');
        }
        this.speak(reply);
      }, 800);
    },

    addMessage(type, content) {
      const div = document.createElement('div');
      div.classList.add('message', type);
      div.textContent = content;
      this.chatLog.appendChild(div);
      this.chatLog.scrollTop = this.chatLog.scrollHeight;
    },

    mockBotResponse(input) {
      const lower = input.toLowerCase();
      if (lower.includes('hello') || lower.includes('hi')) return 'Hello! How can I assist you today?';
      if (lower.includes('weather')) return 'I cannot fetch real‑time weather yet, but you can check a weather site.';
      if (lower.includes('time')) return `The current time is ${new Date().toLocaleTimeString()}.`;
      return `You said: "${input}". I’m still learning how to respond.`;
    },

    startClock() {
      const update = () => {
        const now = new Date();
        this.clockEl.textContent = now.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
      };
      update();
      setInterval(update, 1000);
    },

    animateVolume() {
      if (!this.isListening) return;
      this.volumeLevel = Math.random();
      const percent = (this.volumeLevel * 100).toFixed(0);
      this.volumeMeter.style.setProperty('--fill', `${percent}%`);
      // Instead manipulate a child element
      let bar = this.volumeMeter.querySelector('.volume-fill');
      if (!bar) {
        bar = document.createElement('div');
        bar.className = 'volume-fill';
        this.volumeMeter.appendChild(bar);
      }
      bar.style.width = `${percent}%`;
      requestAnimationFrame(() => this.animateVolume());
    },

    speak(text) {
      if ('speechSynthesis' in window) {
        const utter = new SpeechSynthesisUtterance(text);
        utter.onend = () => {
          if (this.memoryMap) {
            this.memoryMap.classList.remove('speaking');
            // optional: add idle class or remove all
            // this.memoryMap.classList.add('idle');
          }
        };
        speechSynthesis.speak(utter);
      } else {
        // Fallback: just stop speaking after a short delay
        setTimeout(() => {
          if (this.memoryMap) {
            this.memoryMap.classList.remove('speaking');
          }
        }, 3000);
      }
    },

    logAction(msg) {
      const li = document.createElement('li');
      li.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
      this.actionLog.appendChild(li);
      this.actionLog.scrollTop = this.actionLog.scrollHeight;
    },

    loadSampleData() {
      // Add a few memory items
      const samples = [
        {key: 'Preference', value: 'Prefers concise answers'},
        {key: 'Habit', value: 'Checks email at 8 AM'},
        {key: 'Entity', value: 'Project Orion – internal codename'},
        {key: 'Correction', value: 'Old: “release, "release"'},
      ];
      const sampleCorrection = {key: 'Correction', value: 'Old: “annual report 2022” → New: “annual report 2023”'};
      samples.push(sampleCorrection);
      samples.forEach(item => {
        const li = document.createElement('li');
        li.className = 'memory-item';
        li.innerHTML = `<span class="key">${item.key}:</span> <span class="value">${item.value}</span><button class="delete-btn" aria-label="Delete">×</button>`;
        this.memoryList.appendChild(li);
      });
      // Add a sample action log entry
      this.logAction('Application started');
    }
  };

  app.init();
});