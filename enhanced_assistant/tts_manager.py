"""
Text-to-Speech functionality for the AI Assistant.
Currently uses pyttsx3 but designed to be extensible.
"""
import threading
import io
import os
from pathlib import Path
import sys

# Add the enhanced_assistant directory to the path
sys.path.append(str(Path(__file__).parent))

try:
    import pyttsx3
    PYTTSX3_AVAILABLE = True
except ImportError:
    PYTTSX3_AVAILABLE = False
    print("[TTS] Warning: pyttsx3 not available. TTS functionality will be limited.")

# Initialize pygame mixer for audio playback (optional)
try:
    import pygame
    pygame.mixer.init()
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False
    print("[TTS] Warning: pygame not available. Audio playback via pygame disabled.")
except Exception as e:
    PYGAME_AVAILABLE = False
    print(f"[TTS] Warning: Could not initialize pygame mixer: {e}")

class TTSManager:
    """Manages text-to-speech operations."""

    def __init__(self):
        self.engine = None
        self.is_speaking = False
        self._lock = threading.Lock()
        self._initialize_engine()

    def _initialize_engine(self):
        """Initialize the TTS engine."""
        if not PYTTSX3_AVAILABLE:
            print("[TTS] Cannot initialize TTS engine: pyttsx3 not available")
            return

        try:
            self.engine = pyttsx3.init()
            # Configure speech properties
            self.engine.setProperty('rate', 175)    # Words per minute
            self.engine.setProperty('volume', 0.9)  # Volume (0.0 to 1.0)
            print("[TTS] TTS engine initialized successfully")
        except Exception as e:
            print(f"[TTS] Failed to initialize TTS engine: {e}")
            self.engine = None

    def speak(self, text: str, callback=None):
        """
        Speak the given text.

        Args:
            text: The text to speak
            callback: Optional function to call when speech completes
        """
        if not text.strip():
            if callback:
                callback()
            return

        if not self.engine:
            print("[TTS] TTS engine not available")
            if callback:
                callback()
            return

        def _speak_task():
            with self._lock:
                if self.is_speaking:
                    # If already speaking, wait a bit or skip
                    pass
                self.is_speaking = True

            try:
                self.engine.say(text)
                self.engine.runAndWait()
            except Exception as e:
                print(f"[TTS] Error during speech: {e}")
            finally:
                with self._lock:
                    self.is_speaking = False
                if callback:
                    try:
                        callback()
                    except Exception as e:
                        print(f"[TTS] Error in callback: {e}")

        # Run in a separate thread to avoid blocking
        thread = threading.Thread(target=_speak_task, daemon=True)
        thread.start()

    def stop(self):
        """Stop any ongoing speech."""
        with self._lock:
            if self.is_speaking and self.engine:
                try:
                    self.engine.stop()
                except Exception as e:
                    print(f"[TTS] Error stopping speech: {e}")
                finally:
                    self.is_speaking = False

    def is_busy(self):
        """Check if the TTS engine is currently speaking."""
        with self._lock:
            return self.is_speaking

    def set_property(self, property_name: str, value):
        """
        Set a TTS engine property.

        Args:
            property_name: Name of the property to set
            value: Value to set the property to
        """
        if self.engine:
            try:
                self.engine.setProperty(property_name, value)
            except Exception as e:
                print(f"[TTS] Error setting property {property_name}: {e}")

    def get_property(self, property_name: str):
        """
        Get a TTS engine property.

        Args:
            property_name: Name of the property to get

        Returns:
            The value of the property, or None if not available
        """
        if self.engine:
            try:
                return self.engine.getProperty(property_name)
            except Exception as e:
                print(f"[TTS] Error getting property {property_name}: {e}")
                return None
        return None

    def get_available_voices(self):
        """
        Get list of available voices.

        Returns:
            List of voice dictionaries, or empty list if not available
        """
        if not self.engine:
            return []

        try:
            voices = self.engine.getProperty('voices')
            return voices
        except Exception as e:
            print(f"[TTS] Error getting voices: {e}")
            return []

# Global TTS manager instance
_tts_manager = None

def get_tts_manager():
    """Get or create the global TTS manager instance."""
    global _tts_manager
    if _tts_manager is None:
        _tts_manager = TTSManager()
    return _tts_manager

def speak_text(text: str, callback=None):
    """
    Convenience function to speak text using the global TTS manager.

    Args:
        text: The text to speak
        callback: Optional function to call when speech completes
    """
    tts_manager = get_tts_manager()
    tts_manager.speak(text, callback)

def stop_speaking():
    """Stop any ongoing speech."""
    tts_manager = get_tts_manager()
    tts_manager.stop()

def is_speaking():
    """Check if the TTS engine is currently speaking."""
    tts_manager = get_tts_manager()
    return tts_manager.is_busy()