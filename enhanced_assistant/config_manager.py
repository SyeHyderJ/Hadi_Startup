"""
Configuration management for the AI Assistant.
Handles loading/saving API keys and settings.
"""
import json
import sys
from pathlib import Path

def get_base_dir() -> Path:
    """Get the base directory for the application."""
    if getattr(sys, "frozen", False):
        # Running as compiled executable
        return Path(sys.executable).parent
    # Running as script
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()
CONFIG_DIR = BASE_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "settings.json"

# Default configuration
_DEFAULTS = {
    "llm_provider": "ollama",  # "ollama" or "openai"
    "llm_url": "http://localhost:11434",
    "llm_model": "llama3.2",
    "tts_engine": "pyttsx3",  # "pyttsx3", "edgetts", "kokoro", "elevenlabs"
    "tts_voice": "en-US-GuyNeural",  # Default for EdgeTTS
    "tts_speed": 1.0,  # For Kokoro
    "elevenlabs_api_key": "",
    "elevenlabs_voice_id": "pNInz6obpgDQGcFmaJgB",
    "kokoro_voice": "af_heart",
    "kokoro_speed": 1.0,
    "stt_engine": "speech_recognition",  # "speech_recognition", "whisper", "vosk"
    "whisper_model": "base",
    "vosk_model": "en-us",
    "memory_encryption_enabled": True,
    "memory_max_chars": 2200,
}

def ensure_config_dir() -> None:
    """Ensure the configuration directory exists."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

def config_exists() -> bool:
    """Check if configuration file exists."""
    return CONFIG_FILE.exists()

def load_config() -> dict:
    """Load configuration from file, merging with defaults."""
    ensure_config_dir()

    if not CONFIG_FILE.exists():
        # Create default config if none exists
        save_config(_DEFAULTS.copy())
        return _DEFAULTS.copy()

    try:
        user_config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        # Merge with defaults (user settings override defaults)
        config = _DEFAULTS.copy()
        config.update(user_config)
        return config
    except Exception as e:
        print(f"[Config] Error loading config: {e}")
        return _DEFAULTS.copy()

def save_config(config: dict) -> None:
    """Save configuration to file."""
    ensure_config_dir()
    try:
        CONFIG_FILE.write_text(
            json.dumps(config, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        print(f"[Config] Error saving config: {e}")

def get_config() -> dict:
    """Get the current configuration."""
    return load_config()

def get_llm_provider() -> str:
    """Returns 'ollama' or 'openai' (covers LM Studio, LocalAI, Jan, etc.)."""
    config = get_config()
    raw = config.get("llm_provider", "ollama").strip().lower()
    return "openai" if raw in ("openai", "lmstudio", "localai", "jan", "llamacpp") else "ollama"

def get_llm_settings() -> tuple[str, str]:
    """Returns (base_url, model_name)."""
    config = get_config()
    url = config.get("llm_url", "http://localhost:11434").rstrip("/")
    model = config.get("llm_model", "llama3.2")
    return url, model

def update_config(key: str, value) -> None:
    """Update a single configuration value."""
    config = load_config()
    config[key] = value
    save_config(config)