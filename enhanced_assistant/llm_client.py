"""
Enhanced LLM client for the AI Assistant.
Supports multiple backends (Ollama, OpenAI-compatible) with streaming capabilities.
"""
import json
import re
import time
from typing import Callable, Generator, List, Optional, Dict, Any
from pathlib import Path
import sys

import requests

# Import our enhanced config manager
sys.path.append(str(Path(__file__).parent.parent))
from enhanced_assistant.config_manager import get_config, get_llm_provider, get_llm_settings

_SENT_END = re.compile(r'(?<=[.!?])\s+|(?<=\n)\s*\n')

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

def ensure_ollama_running(timeout: int = 15) -> bool:
    """
    For Ollama: ping /api/tags; auto-launch 'ollama serve' if not running.
    For OpenAI-compatible providers: just check if they're reachable.
    Returns True if the LLM server is reachable.
    """
    url, _ = get_llm_settings()
    provider = get_llm_provider()

    if provider == "openai":
        # OpenAI-compatible servers (LM Studio, LocalAI, etc.) must be started by user
        health = f"{url}/v1/models"
        try:
            response = requests.get(health, timeout=5)
            if response.status_code == 200:
                print(f"[LLM] OpenAI-compatible server reachable at {url}")
                return True
            else:
                print(f"[LLM] Server at {url} returned status {response.status_code}")
                return False
        except Exception as e:
            print(f"[LLM] Cannot reach OpenAI-compatible server at {url}: {e}")
            print("      Make sure LM Studio / LocalAI / Jan is running and the server is started.")
            return False

    # Ollama-specific logic
    health = f"{url}/api/tags"

    def _is_up() -> bool:
        try:
            response = requests.get(health, timeout=3)
            return response.status_code == 200
        except Exception:
            return False

    if _is_up():
        return True

    print("[LLM] Ollama not running — attempting to launch 'ollama serve'…")
    try:
        import subprocess
        kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        subprocess.Popen(["ollama", "serve"], **kwargs)
    except FileNotFoundError:
        print("[LLM] 'ollama' command not found. Install Ollama from https://ollama.com")
        return False
    except Exception as e:
        print(f"[LLM] Could not launch Ollama: {e}")
        return False

    # Wait for Ollama to start
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(1.0)
        if _is_up():
            print("[LLM] Ollama started successfully.")
            return True

    print("[LLM] Ollama did not respond within the timeout.")
    return False

def warmup_model(system_prompt: Optional[str] = None) -> bool:
    """
    Pre-load the model and prime Ollama's KV prefix cache.
    This significantly reduces first-token latency for subsequent requests.
    """
    url, model = get_llm_settings()
    provider = get_llm_provider()
    print(f"[LLM] Warming up '{model}' ({provider})…")

    messages: List[Dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": "hi"})

    if provider == "openai":
        # OpenAI-compatible: just fire a minimal request to ensure model is loaded
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "max_tokens": 1,
        }
        try:
            response = requests.post(f"{url}/v1/chat/completions", json=payload, timeout=180)
            response.raise_for_status()
            print(f"[LLM] '{model}' ready (OpenAI-compatible server).")
            return True
        except Exception as e:
            print(f"[LLM] Warmup failed (non-fatal): {e}")
            return False

    # Ollama-specific warmup with KV caching
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "keep_alive": -1,  # Keep model loaded indefinitely
        "options": {"num_predict": 1, "num_gpu": 99},  # Use GPU if available
    }
    try:
        response = requests.post(f"{url}/api/chat", json=payload, timeout=180)
        response.raise_for_status()
        print(f"[LLM] '{model}' loaded and KV cache primed.")
        return True
    except Exception as e:
        print(f"[LLM] Warmup failed (non-fatal): {e}")
        return False

def check_model_available(log_callback: Optional[Callable[[str], None]] = None) -> bool:
    """
    Check if the configured model is available.
    For Ollama: checks if model is pulled.
    For OpenAI-compatible: assumes model is available (can't easily check).

    Args:
        log_callback: Optional callback for logging warnings

    Returns:
        True if model is available or if using non-Ollama provider
    """
    if get_llm_provider() != "ollama":
        return True  # Can't easily check for non-Ollama providers

    url, model = get_llm_settings()
    try:
        response = requests.get(f"{url}/api/tags", timeout=5)
        response.raise_for_status()
        pulled_models = [m.get("name", "") for m in response.json().get("models", [])]
        model_base = model.split(":")[0]

        # Check if model is available (exact match, base name, or with tag)
        found = any(
            m == model or m == model_base or m.startswith(model_base + ":")
            for m in pulled_models
        )

        if not found:
            available = ", ".join(pulled_models) if pulled_models else "none"
            warning_msg = (
                f"WARNING: Model '{model}' is not pulled in Ollama.\n"
                f"         Available: {available}\n"
                f"         Fix: ollama pull {model}"
            )
            print(warning_msg)
            if log_callback:
                log_callback(f"WARNING: '{model}' not found — run: ollama pull {model}")
        return found
    except Exception:
        # Ollama might still be starting up; don't block on this
        return True

def call_llm(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    timeout: int = 120,
) -> Dict[str, Any]:
    """
    Non-streaming chat request. Routes to Ollama or OpenAI-compatible backend.

    Args:
        messages: List of message dictionaries
        tools: Optional list of tool definitions
        timeout: Request timeout in seconds

    Returns:
        Dictionary with "content" (str) and "tool_calls" (list)
    """
    url, model = get_llm_settings()
    provider = get_llm_provider()

    if provider == "openai":
        endpoint = f"{url}/v1/chat/completions"
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "max_tokens": 150,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        try:
            response = requests.post(endpoint, json=payload, timeout=timeout)
            response.raise_for_status()
            result = response.json()
            choice = result.get("choices", [{}])[0]
            message = choice.get("message", {})

            # Normalize OpenAI tool_calls format to match Ollama's format
            raw_tool_calls = message.get("tool_calls") or []
            tool_calls = []
            for tc in raw_tool_calls:
                function_data = tc.get("function", {})
                arguments = function_data.get("arguments", {})
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        pass  # Keep as string if not valid JSON

                tool_calls.append({
                    "id": tc.get("id", ""),
                    "function": {
                        "name": function_data.get("name", ""),
                        "arguments": arguments,
                    },
                })

            return {
                "content": (message.get("content") or "").strip(),
                "tool_calls": tool_calls,
            }
        except Exception as e:
            raise RuntimeError(f"OpenAI-compatible LLM call failed: {e}")

    # Ollama backend
    endpoint = f"{url}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "keep_alive": -1,
        "options": {"num_predict": 150, "num_gpu": 99},
    }
    if tools:
        payload["tools"] = tools

    try:
        response = requests.post(endpoint, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        message = data.get("message", {})

        return {
            "content": (message.get("content") or "").strip(),
            "tool_calls": message.get("tool_calls") or [],
        }
    except requests.exceptions.ConnectionError as e:
        print(f"[LLM] ConnectionError — trying to restart Ollama… ({e})")
        if ensure_ollama_running():
            try:
                response = requests.post(endpoint, json=payload, timeout=timeout)
                response.raise_for_status()
                data = response.json()
                message = data.get("message", {})

                return {
                    "content": (message.get("content") or "").strip(),
                    "tool_calls": message.get("tool_calls") or [],
                }
            except Exception:
                pass
        raise RuntimeError(
            f"Cannot connect to Ollama at {url}. "
            "Make sure Ollama is installed and run: ollama serve"
        )
    except requests.exceptions.Timeout:
        raise RuntimeError("Ollama request timed out after 120 s.")
    except requests.exceptions.HTTPError as e:
        print(f"[LLM] HTTPError: {e.response.status_code} — {e.response.text[:200]}")
        raise RuntimeError(f"Ollama HTTP error: {e.response.status_code}")
    except Exception as e:
        print(f"[LLM] Unexpected error: {type(e).__name__}: {e}")
        raise RuntimeError(f"LLM call failed: {e}")

def call_llm_text(
    prompt: str,
    system: Optional[str] = None,
    model: Optional[str] = None,
    timeout: int = 120,
) -> str:
    """
    Simple text-only generation (no tools).
    Used by planner, executor, error_handler, etc.

    Args:
        prompt: User prompt
        system: Optional system prompt
        model: Optional model name (uses config default if not provided)
        timeout: Request timeout in seconds

    Returns:
        Generated text response
    """
    url, default_model = get_llm_settings()
    model_name = model or default_model
    endpoint = f"{url}/api/chat"

    messages: List[Dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model_name,
        "messages": messages,
        "stream": False,
        "keep_alive": -1,
        "options": {"num_predict": 600},
    }

    try:
        response = requests.post(endpoint, json=payload, timeout=timeout)
        response.raise_for_status()
        return (response.json().get("message", {}).get("content") or "").strip()
    except requests.exceptions.ConnectionError:
        if ensure_ollama_running():
            try:
                response = requests.post(endpoint, json=payload, timeout=timeout)
                response.raise_for_status()
                return (response.json().get("message", {}).get("content") or "").strip()
            except Exception:
                pass
        raise RuntimeError(
            f"Cannot connect to Ollama at {url}. "
            "Make sure Ollama is installed and run: ollama serve"
        )
    except Exception as e:
        raise RuntimeError(f"LLM text call failed: {e}")

def _stream_openai(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    timeout: int,
) -> Generator[Dict[str, Any], None, None]:
    """
    Streaming backend for OpenAI-compatible servers (LM Studio, LocalAI, Jan, etc.).
    Yields sentence chunks and a final "done" event with accumulated content and tool calls.
    """
    url, model = get_llm_settings()
    endpoint = f"{url}/v1/chat/completions"

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "max_tokens": 150,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    try:
        with requests.post(endpoint, json=payload, timeout=timeout, stream=True) as response:
            response.raise_for_status()
            full_content = ""
            buffer = ""
            # Tool call fragments: index -> {"id", "function": {"name", "arguments"}}
            tc_fragments: Dict[int, Dict[str, Any]] = {}

            for raw in response.iter_lines():
                if not raw:
                    continue
                # SSE lines look like: b"data: {...}" or b"data: [DONE]"
                line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue

                choice = chunk.get("choices", [{}])[0]
                delta = choice.get("delta", {})
                text = delta.get("content") or ""

                full_content += text
                buffer += text

                # Yield complete sentences as they arrive
                while True:
                    match = _SENT_END.search(buffer)
                    if not match:
                        break
                    sentence = buffer[: match.start() + 1].strip()
                    buffer = buffer[match.end() :]
                    if sentence:
                        yield {"type": "sentence", "text": sentence}

                # Accumulate streaming tool-call fragments
                for tc in (delta.get("tool_calls") or []):
                    idx = tc.get("index", 0)
                    if idx not in tc_fragments:
                        tc_fragments[idx] = {"id": "", "function": {"name": "", "arguments": ""}}
                    frag = tc_fragments[idx]
                    frag["id"] = frag["id"] or tc.get("id", "")
                    func = tc.get("function", {})
                    frag["function"]["name"] += func.get("name") or ""
                    frag["function"]["arguments"] += func.get("arguments") or ""

                finish_reason = choice.get("finish_reason")
                if finish_reason in ("stop", "tool_calls", "length"):
                    break

            # Flush any remaining content
            if buffer.strip():
                yield {"type": "sentence", "text": buffer.strip()}

            # Parse accumulated tool-call arguments
            tool_calls: List[Dict[str, Any]] = []
            for idx in sorted(tc_fragments):
                frag = tc_fragments[idx]
                args = frag["function"]["arguments"]
                try:
                    args = json.loads(args)
                except Exception:
                    pass  # Keep as raw string if not valid JSON

                tool_calls.append({
                    "id": frag["id"],
                    "function": {
                        "name": frag["function"]["name"],
                        "arguments": args,
                    },
                })

            yield {
                "type": "done",
                "content": full_content.strip(),
                "tool_calls": tool_calls,
            }

    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"Cannot reach OpenAI-compatible server at {url}.\n"
            "Make sure LM Studio / LocalAI / Jan is running and the server is started."
        )
    except requests.exceptions.Timeout:
        raise RuntimeError("OpenAI-compatible stream timed out.")
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"OpenAI-compatible HTTP error: {e.response.status_code}")
    except Exception as e:
        raise RuntimeError(f"OpenAI-compatible stream failed: {e}")

def _do_ollama_stream(
    url: str,
    payload: Dict[str, Any],
) -> Generator[Dict[str, Any], None, None]:
    """Helper function to handle Ollama streaming."""
    with requests.post(f"{url}/api/chat", json=payload, stream=True) as response:
        response.raise_for_status()
        full_content = ""
        buffer = ""
        tool_calls: List[Dict[str, Any]] = []

        for raw in response.iter_lines():
            if not raw:
                continue
            try:
                chunk = json.loads(raw)
            except json.JSONDecodeError:
                continue

            message = chunk.get("message", {})
            delta_content = message.get("content") or ""

            full_content += delta_content
            buffer += delta_content

            # Yield complete sentences as they arrive
            while True:
                match = _SENT_END.search(buffer)
                if not match:
                    break
                sentence = buffer[: match.start() + 1].strip()
                buffer = buffer[match.end() :]
                if sentence:
                    yield {"type": "sentence", "text": sentence}

            # Collect tool calls
            tc = message.get("tool_calls")
            if tc:
                tool_calls.extend(tc)

            if chunk.get("done"):
                if buffer.strip():
                    yield {"type": "sentence", "text": buffer.strip()}

                yield {
                    "type": "done",
                    "content": full_content.strip(),
                    "tool_calls": tool_calls,
                }
                return

def call_llm_stream(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    timeout: int = 120,
) -> Generator[Dict[str, Any], None, None]:
    """
    Streaming chat request. Routes to Ollama or OpenAI-compatible backend.

    Args:
        messages: List of message dictionaries
        tools: Optional list of tool definitions
        timeout: Request timeout in seconds

    Yields:
        {"type": "sentence", "text": str} - each complete sentence as it arrives
        {"type": "done", "content": str, "tool_calls": list} - when stream ends
    """
    provider = get_llm_provider()
    if provider == "openai":
        yield from _stream_openai(messages, tools, timeout)
        return

    url, model = get_llm_settings()
    endpoint = f"{url}/api/chat"

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "keep_alive": -1,
        "options": {"num_predict": 150, "num_gpu": 99},
    }
    if tools:
        payload["tools"] = tools

    def _do_stream() -> Generator[Dict[str, Any], None, None]:
        try:
            yield from _do_ollama_stream(url, payload)
        except requests.exceptions.ConnectionError as e:
            print(f"[LLM] Stream ConnectionError — trying to restart Ollama… ({e})")
            if ensure_ollama_running():
                yield from _do_ollama_stream(url, payload)
                return
            raise RuntimeError(
                f"Cannot connect to Ollama at {url}. "
                "Make sure Ollama is installed and run: ollama serve"
            )
        except requests.exceptions.Timeout:
            raise RuntimeError("Ollama stream timed out.")
        except requests.exceptions.HTTPError as e:
            raise RuntimeError(f"Ollama HTTP error: {e.response.status_code}")
        except Exception as e:
            print(f"[LLM] Stream error: {type(e).__name__}: {e}")
            raise RuntimeError(f"LLM stream failed: {e}")

    yield from _do_stream()


# Compatibility functions for existing main.py code
def ollama_generate(prompt: str) -> str:
    """Generate text using Ollama (non-streaming) - compatibility function."""
    return call_llm_text(prompt)


def get_ollama_model() -> str:
    """Get the default Ollama model - compatibility function."""
    return get_ollama_settings()[1]


def get_ollama_models() -> list:
    """Get list of available Ollama models - compatibility function."""
    try:
        response = requests.get(f"{get_llm_settings()[0]}/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        pass
    return ["llama2"]  # fallback