#!/usr/bin/env python3
"""
Enhanced AI Assistant prototype with improved architecture inspired by MEHDI_W_CLAP.
Features modular design, enhanced memory management, and better LLM integration.
"""

import sys
import os
import json
import uuid
import datetime
import threading
import requests
import base64
import tkinter as tk
from tkinter import scrolledtext, simpledialog, messagebox
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import speech_recognition as sr
from pathlib import Path

# Import our enhanced modules
sys.path.append(str(Path(__file__).parent))
try:
    from enhanced_assistant.config_manager import get_config, ensure_config_dir, config_exists
    from enhanced_assistant.memory_manager import (
        init_db, add_memory, get_memory, update_memory, delete_memory,
        list_memory, get_memory_for_prompt, remember, forget,
        MEMORY_CATEGORIES
    )
    from enhanced_assistant.llm_client import (
        ollama_generate, get_ollama_model, get_ollama_models,
        ensure_ollama_running, warmup_model, call_llm_stream,
        get_llm_provider, get_llm_settings
    )
    from enhanced_assistant.tts_manager import speak_text, stop_speaking, is_speaking
    ENHANCED_MODULES_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Could not import enhanced modules: {e}")
    print("[INFO] Falling back to built-in implementations")
    ENHANCED_MODULES_AVAILABLE = False

# Fallback implementations if enhanced modules are not available
if not ENHANCED_MODULES_AVAILABLE:
    # Configuration paths
    DB_PATH = os.path.join(os.path.expanduser("~"), ".ai_assistant_memory.db")
    HANDOFF_DIR = os.path.join(os.path.expanduser("~"), ".ai_assistant_handoffs")
    OLLAMA_HOST = "http://localhost:11435"

    os.makedirs(HANDOFF_DIR, exist_ok=True)

    # TTS engine (single instance)
    import pyttsx3
    _tts_engine = pyttsx3.init()
    _tts_engine.setProperty('rate', 175)  # words per minute

    def speak_text(text: str):
        """Speak text using pyttsx3 in a non-blocking way."""
        def run():
            _tts_engine.say(text)
            _tts_engine.runAndWait()
        threading.Thread(target=run, daemon=True).start()

    def stop_speaking():
        """Stop TTS (placeholder for compatibility)"""
        pass

    def is_speaking():
        """Check if TTS is active (placeholder)"""
        return False

    # Database functions (simplified versions)
    def init_db():
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS memory_entries (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                context_id TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                strength REAL NOT NULL DEFAULT 1.0,
                source TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.8
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_memory_category_key ON memory_entries(category, key)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_memory_context ON memory_entries(context_id)')
        conn.commit()
        conn.close()

    # ... (other fallback functions would go here but are omitted for brevity)
    # For the sake of this example, we'll assume the enhanced modules work

# ---------- Enhanced Session State ----------
session_turns = []
active_context = None
active_task = None
last_actions = []
permissions_granted = {
    "screen_capture": {"granted": False},
    "webcam": {"granted": False},
    "microphone": {"granted": False},
    "file_access": {"granted": False, "paths": []},
    "app_control": {"granted": False, "allowed_apps": []}
}

def add_turn(user_input: str, agent_response: str, intent: str = "", entities: list = None,
             action_taken: str = "", memory_updates: list = None):
    """Add a conversation turn to session history."""
    turn = {
        "turn_id": str(uuid.uuid4()),
        "timestamp": int(datetime.datetime.now().timestamp() * 1000),
        "user_input": {"type": "text", "content": user_input},
        "agent_response": {"type": "text", "content": agent_response},
        "intent": intent,
        "entities": entities or [],
        "action_taken": action_taken,
        "memory_updates": memory_updates or []
    }
    session_turns.append(turn)
    if len(session_turns) > 20:
        session_turns.pop(0)

def clear_session():
    """Clear the current session state."""
    global session_turns, active_context, active_task, last_actions
    session_turns.clear()
    active_context = None
    active_task = None
    last_actions = []

# ---------- Enhanced Ollama Integration ----------
def get_ollama_models() -> list:
    """Get list of available Ollama models."""
    try:
        response = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            return [m["name"] for m in data.get("models", [])]
    except Exception as e:
        print(f"Ollama error: {e}")
    return []

def get_ollama_model() -> str:
    """Get the default Ollama model."""
    models = get_ollama_models()
    return models[0] if models else "llama2"

def ollama_generate(prompt: str) -> str:
    """Generate text using Ollama (non-streaming)."""
    model = get_ollama_model()
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False
    }
    try:
        response = requests.post(f"{OLLAMA_HOST}/api/generate", json=payload, timeout=30)
        if response.status_code == 200:
            data = response.json()
            return data.get("response", "").strip()
        else:
            return f"[Ollama error: {response.status_code}]"
    except Exception as e:
        return f"[Ollama request failed: {e}]"

def build_prompt(user_text: str) -> str:
    """
    Build a prompt for the LLM incorporating user memories.
    Enhanced version that uses the improved memory system.
    """
    hints = []

    # Get memories from various categories to build context
    if ENHANCED_MODULES_AVAILABLE:
        # Use enhanced memory system
        for category in ["preference", "habit", "correction", "identity"]:
            entries = list_memory(limit=5, category=category)
            for entry in entries:
                if isinstance(entry, dict) and 'value' in entry:
                    hints.append(f"{category}: {entry['key']} = {entry['value']}")

        # Get formatted memory for prompt
        memory_context = get_memory_for_prompt()
        if memory_context:
            hints.append("User Memories:")
            hints.append(memory_content.strip())
    else:
        # Fallback to original implementation
        for cat in ["preference", "habit", "correction"]:
            entries = list_memory(limit=5, category=cat)
            for e in entries:
                hints.append(f"{e['category']}: {e['key']} = {e['value']}")

    memory_text = "\\n".join(hints) if hints else "No specific memories yet."
    system = ("You are a helpful personal assistant. Use the user's memories when relevant. "
              "Keep answers concise but friendly.")
    return f"{system}\\n\\nUser memories:\\n{memory_text}\\n\\nUser says: {user_text}\\n\\nAssistant:"

# ---------- Encryption Helpers ----------
def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive encryption key from passphrase and salt."""
    kdf = PBKDF2HMAC(hashes.SHA256(), length=32, salt=salt, iterations=200_000)
    return kdf.derive(passphrase.encode())

def encrypt_json(data: dict, passphrase: str) -> bytes:
    """Encrypt JSON data using AES-GCM."""
    salt = os.urandom(16)
    key = _derive_key(passphrase, salt)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # GCM nonce
    pt = json.dumps(data).encode()
    ct = aesgcm.encrypt(nonce, pt, None)
    # Format: salt + nonce + ciphertext
    return salt + nonce + ct

def decrypt_json(blob: bytes, passphrase: str) -> dict:
    """Decrypt JSON data using AES-GCM."""
    salt, nonce, ct = blob[:16], blob[16:28], blob[28:]
    key = _derive_key(passphrase, salt)
    aesgcm = AESGCM(key)
    pt = aesgcm.decrypt(nonce, ct, None)
    return json.loads(pt.decode())

# ---------- Enhanced Handoff Functions ----------
def create_handoff(filename: str) -> str:
    """Create an encrypted handoff file for session persistence."""
    handoff = {
        "handoff_meta": {
            "version": "1.0",
            "created_at": int(datetime.datetime.now().timestamp() * 1000),
            "created_by_device_id": str(uuid.getnode()),
            "created_by_app_version": "0.3.0-enhanced"
        },
        "session_state": {
            "session_id": str(uuid.uuid4()),
            "start_time": session_turns[0]["timestamp"] if session_turns else int(datetime.datetime.now().timestamp() * 1000),
            "last_active": session_turns[-1]["timestamp"] if session_turns else int(datetime.datetime.now().timestamp() * 1000),
            "dialogue_turns": session_turns.copy(),
            "active_context": active_context,
            "current_mode": "assistant",
            "active_task": active_task
        },
        "memory_snapshot": {
            "note": "Encrypted blob of selected memory categories.",
            "encrypted_blob": None,
            "categories_included": ["preference", "habit", "entity", "identity"]
        },
        "permissions_granted": permissions_granted,
        "last_actions": last_actions.copy(),
        "export_controls": {
            "can_be_shared": True,
            "sharing_methods": ["encrypted_file"],
            "expiration": "Handoff does not auto-expire in this prototype."
        }
    }

    # Ask for passphrase
    passphrase = simpledialog.askstring("Handoff Encryption",
                                       "Enter a passphrase to encrypt the handoff (leave blank for no encryption):")
    if passphrase is None:  # user pressed Cancel
        raise ValueError("Handoff creation cancelled")

    # Prepare memory blob
    mem_blob = {}
    if ENHANCED_MODULES_AVAILABLE:
        for cat in handoff["memory_snapshot"]["categories_included"]:
            if cat in MEMORY_CATEGORIES:
                mem_blob[cat] = list_memory(limit=50, category=cat)
    else:
        # Fallback for basic memory system
        for cat in handoff["memory_snapshot"]["categories_included"]:
            mem_blob[cat] = list_memory(limit=50, category=cat)

    mem_json = json.dumps(mem_blob)
    if not passphrase or passphrase.strip() == "":
        # No encryption - store plaintext as base64 for uniformity
        handoff["memory_snapshot"]["encrypted_blob"] = base64.b64encode(mem_json.encode()).decode()
        handoff["memory_snapshot"]["encrypted"] = False
    else:
        encrypted = encrypt_json({"data": mem_json}, passphrase)
        handoff["memory_snapshot"]["encrypted_blob"] = base64.b64encode(encrypted).decode()
        handoff["memory_snapshot"]["encrypted"] = True

    path = os.path.join(HANDOFF_DIR, filename)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(handoff, f, indent=2)
    return path

def load_handoff(filename: str):
    """Load and decrypt a handoff file to restore session state."""
    path = os.path.join(HANDOFF_DIR, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Handoff file {filename} not found.")

    with open(path, 'r', encoding='utf-8') as f:
        handoff = json.load(f)

    # Determine if encrypted
    enc_info = handoff.get("memory_snapshot", {})
    is_encrypted = enc_info.get("encrypted", False)
    blob_b64 = enc_info.get("encrypted_blob", "")

    if not blob_b64:
        raise ValueError("No encrypted blob found in handoff.")

    raw = base64.b64decode(blob_b64)
    added = 0

    if is_encrypted:
        # Ask for passphrase
        passphrase = simpledialog.askstring("Handoff Decryption",
                                           "Enter passphrase to decrypt handoff:")
        if passphrase is None:
            raise ValueError("Decryption cancelled")
        try:
            decrypted = decrypt_json(raw, passphrase)
            mem_blob = json.loads(decrypted["data"])
        except Exception as e:
            raise ValueError(f"Decryption failed: {e}")
    else:
        # Plaintext base64
        mem_blob = json.loads(raw.decode())

    # Merge into database (non-overwrite, just add if not exists)
    for category, entries in mem_blob.items():
        if category in MEMORY_CATEGORIES or not ENHANCED_MODULES_AVAILABLE:
            for entry in entries:
                if isinstance(entry, dict) and 'key' in entry and 'value' in entry:
                    key = entry['key']
                    value = str(entry['value'])
                    context_id = entry.get('context_id')

                    # Check if we already have this memory
                    existing = get_memory(category, key, context_id)
                    if not existing:
                        add_memory(category, key, value, context_id=context_id,
                                   strength=0.5, source="handoff_import", confidence=0.6)
                        added += 1

    handoff["_imported_memory_count"] = added

    # Restore session state
    global session_turns, active_context, active_task, last_actions
    session_turns = handoff.get("session_state", {}).get("dialogue_turns", []).copy()
    active_context = handoff.get("session_state", {}).get("active_context")
    active_task = handoff.get("session_state", {}).get("active_task")
    last_actions = handoff.get("last_actions", []).copy()

    return handoff

# ---------- Enhanced GUI ----------
class AssistantApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Enhanced AI Assistant (Ollama)")
        self.geometry("800x600")
        self.configure(bg="#f0f0f0")
        self.create_widgets()

        # Initialize systems
        init_db()
        self.display_system("Enhanced Assistant started. Type commands or chat.")

        # Check LLM availability
        self.check_llm_status()

    def create_widgets(self):
        """Create the GUI components."""
        # Chat display
        self.chat = scrolledtext.ScrolledText(self, wrap=tk.WORD, state='disabled',
                                              width=90, height=25, bg="#ffffff")
        self.chat.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        # Entry frame
        entry_frame = tk.Frame(self)
        entry_frame.pack(fill=tk.X, padx=10, pady=(0,10))

        self.entry = tk.Entry(entry_frame, font=("Arial", 12))
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
        self.entry.bind("<Return>", self.on_enter)

        self.send_btn = tk.Button(entry_frame, text="Send", command=self.on_send)
        self.send_btn.pack(side=tk.RIGHT)

        # Mic button
        self.mic_btn = tk.Button(entry_frame, text="🎤", width=3, command=self.on_mic)
        self.mic_btn.pack(side=tk.RIGHT, padx=(0,5))

        # Button frame
        btn_frame = tk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=(0,10))

        tk.Button(btn_frame, text="Save Handoff", command=self.cmd_save_handoff).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Load Handoff", command=self.cmd_load_handoff).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="View Memory", command=self.cmd_view_memory).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="View Habits", command=self.cmd_view_habits).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Clear Session", command=self.cmd_clear_session).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Help", command=self.cmd_help).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="LLM Status", command=self.cmd_llm_status).pack(side=tk.LEFT, padx=5)

    def display_system(self, message: str):
        """Display a system message in the chat."""
        self.chat.configure(state='normal')
        self.chat.insert(tk.END, f"System: {message}\\n")
        self.chat.configure(state='disabled')
        self.chat.see(tk.END)

    def display_user(self, message: str):
        """Display a user message in the chat."""
        self.chat.configure(state='normal')
        self.chat.insert(tk.END, f"You: {message}\\n")
        self.chat.configure(state='disabled')
        self.chat.see(tk.END)

    def display_agent(self, message: str):
        """Display an agent message in the chat."""
        self.chat.configure(state='normal')
        self.chat.insert(tk.END, f"Agent: {message}\\n")
        self.chat.configure(state='disabled')
        self.chat.see(tk.END)

    def on_enter(self, event):
        """Handle Enter key press."""
        self.on_send()

    def on_send(self):
        """Handle sending a message."""
        user_text = self.entry.get().strip()
        if not user_text:
            return

        self.display_user(user_text)
        self.entry.delete(0, tk.END)

        # Show typing indicator
        self.display_agent("...")

        # Get response in a separate thread to avoid freezing UI
        def get_response():
            try:
                prompt = build_prompt(user_text)
                # Use streaming if available for better UX
                if ENHANCED_MODULES_AVAILABLE:
                    # Collect streaming response
                    response_parts = []
                    for chunk in call_llm_stream([
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": user_text}
                    ]):
                        if chunk["type"] == "sentence":
                            response_parts.append(chunk["text"])
                        elif chunk["type"] == "done":
                            break
                    agent_response = " ".join(response_parts).strip()
                    if not agent_response:
                        agent_response = "[No response generated]"
                else:
                    # Fallback to non-streaming
                    agent_response = ollama_generate(prompt)

                # Update UI in main thread
                self.after(0, self._handle_response, user_text, agent_response)
            except Exception as e:
                self.after(0, self._handle_error, str(e))

        threading.Thread(target=get_response, daemon=True).start()

    def _handle_response(self, user_text: str, agent_response: str):
        """Handle the LLM response (called in main thread)."""
        # Remove typing indicator
        self.chat.configure(state='normal')
        self.chat.delete("end-3l", "end-1l")  # Remove the "..."
        self.chat.configure(state='disabled')

        # Display actual response
        self.display_agent(agent_response)

        # Speak response
        speak_text(agent_response)

        # Log turn
        add_turn(user_input=user_text, agent_response=agent_response)

    def _handle_error(self, error_msg: str):
        """Handle an error (called in main thread)."""
        self.chat.configure(state='normal')
        self.chat.delete("end-3l", "end-1l")  # Remove the "..."
        self.chat.configure(state='disabled')

        self.display_agent(f"[Error: {error_msg}]")
        speak_text(f"I encountered an error: {error_msg}")

    def on_mic(self):
        """Handle microphone button press."""
        self.display_system("Listening...")

        def worker():
            text = listen_and_transcribe()
            self.after(0, lambda: self.entry.delete(0, tk.END))
            self.after(0, lambda: self.entry.insert(tk.END, text))
            self.after(0, lambda: self.display_system("Listening stopped."))
            # Auto-send after short delay
            self.after(300, self.on_send)

        threading.Thread(target=worker, daemon=True).start()

    # ----- Command handlers -----
    def cmd_help(self):
        """Show help information."""
        help_text = (
            "Enhanced AI Assistant Commands:\\n"
            "/set <category> <key> <value>   - Store a memory\\n"
            "/get <category> <key>           - Retrieve a memory\\n"
            "/list [<category>]              - Show recent memories\\n"
            "/forget <category> <key>        - Forget a memory\\n"
            "/handoff <filename>             - Save session to encrypted file\\n"
            "/load <filename>                - Load session from file\\n"
            "/clear                          - Clear current session\\n"
            "/help                           - Show this help\\n"
            "/llm_status                     - Check LLM connection\\n"
            "/warmup                         - Warm up the LLM model\\n"
            "Or just type a message to chat with the assistant."
        )
        self.display_system(help_text)

    def cmd_save_handoff(self):
        """Handle saving a handoff."""
        filename = simpledialog.askstring("Save Handoff",
                                         "Enter filename for handoff (e.g., session.json):")
        if filename is None:
            self.display_system("Handoff creation cancelled.")
            return
        if not filename:
            messagebox.showwarning("Input needed", "Filename cannot be empty.")
            return
        if not filename.endswith(".json"):
            filename += ".json"
        try:
            path = create_handoff(filename)
            self.display_system(f"Handoff saved to {path}")
        except ValueError as ve:
            if str(ve) == "Handoff creation cancelled":
                self.display_system("Handoff creation cancelled.")
            else:
                messagebox.showerror("Error", str(ve))
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save handoff: {e}")

    def cmd_load_handoff(self):
        """Handle loading a handoff."""
        filename = simpledialog.askstring("Load Handoff",
                                         "Enter filename to load (e.g., session.json):")
        if filename is None:
            self.display_system("Handoff loading cancelled.")
            return
        if not filename:
            messagebox.showwarning("Input needed", "Filename cannot be empty.")
            return
        if not filename.endswith(".json"):
            filename += ".json"
        try:
            handoff = load_handoff(filename)
            added = handoff.get("_imported_memory_count", 0)
            self.display_system(f"Handoff loaded from {filename}. "
                               f"Session restored. Imported {added} new memory items.")
        except ValueError as ve:
            if str(ve) == "Decryption cancelled":
                self.display_system("Handoff loading cancelled.")
            else:
                messagebox.showerror("Error", str(ve))
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load handoff: {e}")

    def cmd_clear_session(self):
        """Handle clearing the session."""
        if messagebox.askyesno("Clear Session", "Clear current conversation session?"):
            clear_session()
            self.display_system("Session cleared.")

    def cmd_view_memory(self):
        """View recent memory entries."""
        mems = list_memory(limit=10)
        if not mems:
            self.display_system("No memory entries yet.")
            return
        lines = ["Recent memory entries:"]
        for m in mems:
            if isinstance(m, dict):
                lines.append(f"- [{m.get('category', '?')}] {m.get('key', '?')} = {m.get('value', '?')} "
                           f"(strength {m.get('strength', 0):.1f})")
            else:
                lines.append(f"- {m}")
        self.display_system("\\n".join(lines))

    def cmd_view_habits(self):
        """View habit entries."""
        habs = list_memory(limit=10, category="habit")
        if not habs:
            self.display_system("No habit entries yet.")
            return
        lines = ["Habit entries:"]
        for h in habs:
            if isinstance(h, dict):
                lines.append(f"- {h.get('key', '?')}: {h.get('value', '?')} "
                           f"(strength {h.get('strength', 0):.1f})")
            else:
                lines.append(f"- {h}")
        self.display_system("\\n".join(lines))

    def cmd_llm_status(self):
        """Check and display LLM status."""
        self.display_system("Checking LLM status...")

        def check_status():
            try:
                if ENHANCED_MODULES_AVAILABLE:
                    provider = get_llm_provider()
                    url, model = get_llm_settings()

                    if provider == "ollama":
                        if ensure_ollama_running(timeout=5):
                            models = get_ollama_models()
                            self.after(0, lambda: self.display_system(
                                f"Ollama is running at {url}\\n"
                                f"Available models: {', '.join(models[:5])}{'...' if len(models) > 5 else ''}\\n"
                                f"Using model: {model}"
                            ))
                        else:
                            self.after(0, lambda: self.display_system(
                                f"Cannot connect to Ollama at {url}.\\n"
                                "Please ensure Ollama is installed and running."
                            ))
                    else:  # openai-compatible
                        # Simple ping test
                        try:
                            response = requests.get(f"{url}/v1/models", timeout=5)
                            if response.status_code == 200:
                                self.after(0, lambda: self.display_system(
                                    f"OpenAI-compatible server is reachable at {url}\\n"
                                    f"Using model: {model}"
                                ))
                            else:
                                self.after(0, lambda: self.display_system(
                                    f"Server at {url} returned status {response.status_code}"
                                ))
                        except Exception as e:
                            self.after(0, lambda: self.display_system(
                                f"Cannot connect to server at {url}: {e}"
                            ))
                else:
                    # Original implementation
                    models = get_ollama_models()
                    if models:
                        self.after(0, lambda: self.display_system(
                            f"Ollama is available.\\n"
                            f"Available models: {', '.join(models[:5])}{'...' if len(models) > 5 else ''}\\n"
                            f"Using model: {get_ollama_model()}"
                        ))
                    else:
                        self.after(0, lambda: self.display_system(
                            "Ollama does not appear to be running.\\n"
                            "Please start Ollama with: ollama serve"
                        ))
            except Exception as e:
                self.after(0, lambda: self.display_system(f"Error checking LLM status: {e}"))

        threading.Thread(target=check_status, daemon=True).start()

    def cmd_warmup(self):
        """Warm up the LLM model."""
        self.display_system("Warming up LLM model...")

        def warmup():
            try:
                if ENHANCED_MODULES_AVAILABLE:
                    success = warmup_model("You are a helpful assistant.")
                    if success:
                        self.after(0, lambda: self.display_system("Model warmed up successfully."))
                    else:
                        self.after(0, lambda: self.display_system("Model warmup completed (may have had minor issues)."))
                else:
                    self.after(0, lambda: self.display_system(
                        "Model warmup feature requires enhanced modules.\\n"
                        "Using basic Ollama interaction instead."
                    ))
            except Exception as e:
                self.after(0, lambda: self.display_system(f"Error during warmup: {e}"))

        threading.Thread(target=warmup, daemon=True).start()

def listen_and_transcribe() -> str:
    """Capture audio from microphone and return transcribed text."""
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        recognizer.adjust_for_ambient_noise(source, duration=0.5)
        try:
            audio = recognizer.listen(source, timeout=5, phrase_time_limit=8)
            return recognizer.recognize_google(audio)
        except sr.WaitTimeoutError:
            return "[Listening timed out]"
        except sr.UnknownValueError:
            return "[Could not understand audio]"
        except sr.RequestError as e:
            return f"[Speech recognition error: {e}]"

if __name__ == "__main__":
    app = AssistantApp()
    app.mainloop()