"""
Enhanced LLM client for the AI Assistant.
Supports multiple backends (Ollama, OpenAI-compatible) with streaming capabilities.
Now supports image input for multimodal models.
"""
import json
import re
import time
from typing import Callable, Generator, List, Optional, Dict, Any
from pathlib import Path

import sys
import base64

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


def _format_message_for_provider(message: Dict[str, Any], provider: str) -> Dict[str, Any]:
    """
    Convert a message to the format expected by the LLM provider.
    Handles text-only messages and messages with images.
    """
    # Make a copy to avoid modifying the original
    msg = message.copy()

    # If there are no images, return the message as is (for text-only)
    if "images" not in msg or not msg["images"]:
        return msg

    images = msg.pop("images")  # Remove and get the list of base64 strings
    content = msg.get("content", "")

    if provider == "ollama":
        # For Ollama, we keep the content as a string and add the images list
        # The Ollama API expects: {"role": "...", "content": "...", "images": ["base64", ...]}
        msg["images"] = images
        # Note: The content string can be empty or contain text; the model will use both.
        return msg
    elif provider == "openai":
        # For OpenAI, we need to convert the content into a list of content parts
        # If there's text, we add a text object; for each image, we add an image_url object
        content_parts = []
        if content:
            content_parts.append({"type": "text", "text": content})
        for img in images:
            # Assume the image is base64 encoded; we'll use the data URL format
            # We don't know the image type, so we'll use a generic prefix; the model might infer it.
            # Alternatively, we could require the caller to specify the type, but for simplicity,
            # we'll use "image/jpeg" as a common default. The user should ensure the image is JPEG.
            # A better approach would be to have the caller provide the full data URL, but we'll
            # keep it simple and assume JPEG.
            content_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64:{img}"
                }
            })
        msg["content"] = content_parts
        return msg
    else:
        # Fallback: return the message as is (might break, but we don't know other providers)
        return msg


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
        found = False
        for pulled in pulled_models:
            if pulled == model or pulled.startswith(model_base + ":"):
                found = True
                break

        if not found and log_callback:
            log_callback(
                f"WARN: Model '{model}' not found in Ollama. "
                f"Available: {', '.join(pulled_models[:5])}{'...' if len(pulled_models) > 5 else ''}"
            )
        return found
    except Exception as e:
        if log_callback:
            log_callback(f"WARN: Could not check model availability: {e}")
        return True  # Fail open to avoid blocking


def call_llm(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    timeout: int = 120,
) -> Dict[str, Any]:
    """
    Non-streaming chat request. Routes to Ollama or OpenAI-compatible backend.
    Now supports image input via the "images" key in message dictionaries.

    Returns:
        {"content": str, "tool_calls": list}
    """
    url, model = get_llm_settings()
    provider = get_llm_provider()

    # Format messages for the specific provider (handle images)
    formatted_messages = [_format_message_for_provider(msg, provider) for msg in messages]

    if provider == "openai":
        endpoint = f"{url}/v1/chat/completions"
        payload: Dict[str, Any] = {
            "model": model,
            "messages": formatted_messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        try:
            resp = requests.post(endpoint, json=payload, timeout=timeout)
            resp.raise_for_status()
            choice = resp.json().get("choices", [{}])[0]
            msg = choice.get("message", {})
            # OpenAI tool_calls format -> normalise to Ollama-style
            raw_tc = msg.get("tool_calls") or []
            tc_list = [
                {
                    "id": t.get("id", ""),
                    "function": {
                        "name": t["function"]["name"],
                        "arguments": (
                            json.loads(t["function"]["arguments"])
                            if isinstance(t["function"].get("arguments"), str)
                            else t["function"].get("arguments", {})
                        ),
                    },
                }
                for t in raw_tc
            ]
            return {
                "content": (msg.get("content") or "").strip(),
                "tool_calls": tc_list,
            }
        except Exception as e:
            raise RuntimeError(f"OpenAI-compatible LLM call failed: {e}")

    # Ollama
    endpoint = f"{url}/api/chat"
    payload = {
        "model": model,
        "messages": formatted_messages,
        "stream": False,
        "keep_alive": -1,
        "options": {"num_predict": 150, "num_gpu": 99},
    }
    if tools:
        # Ollama tool format: we assume the tools are already in Ollama format
        # (the same as OpenAI format? Actually, Ollama uses the same format as OpenAI for tools)
        # We'll pass them as is.
        payload["tools"] = tools

    try:
        resp = requests.post(endpoint, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        msg = data.get("message", {})
        return {
            "content": (msg.get("content") or "").strip(),
            "tool_calls": msg.get("tool_calls") or [],
        }
    except requests.exceptions.ConnectionError as e:
        print(f"[LLM] ConnectionError — trying to restart Ollama… ({e})")
        if ensure_ollama_running():
            try:
                resp = requests.post(endpoint, json=payload, timeout=timeout)
                resp.force_for_status()
                data = resp.json()
                msg = data.get("message", {})
                return {
                    "content": (msg.get("content") or "").strip(),
                    "tool_calls": msg.get("tool_calls") or [],
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
    Simple text-only generation (no tools, no images).
    Used by planner, executor, error_handler, etc.
    """
    url, default_model = get_llm_settings()
    m = model or default_model
    endpoint = f"{url}/api/chat"
    provider = get_llm_provider()

    messages: List[Dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # Format messages for the provider (text-only, so no image handling needed here)
    formatted_messages = [_format_message_for_provider(msg, provider) for msg in messages]

    payload = {"model": m, "messages": formatted_messages, "stream": False, "keep_alive": -1, "options": {"num_predict": 600}}

    try:
        resp = requests.post(endpoint, json=payload, timeout=timeout)
        resp.raise_for_status()
        return (resp.json().get("message", {}).get("content") or "").strip()
    except requests.exceptions.ConnectionError:
        if ensure_ollama_running():
            try:
                resp = requests.post(endpoint, json=payload, timeout=timeout)
                resp.raise_for_status()
                return (resp.json().get("message", {}).get("content") or "").strip()
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
        with requests.post(endpoint, json=payload, timeout=timeout, stream=True) as resp:
            resp.raise_for_status()
            full_content = ""
            buffer = ""
            # Tool call fragments: index -> {"id", "function": {"name", "arguments"}}
            tc_fragments: Dict[int, Dict[str, Any]] = {}

            for raw in resp.iter_lines():
                if not raw:
                    continue
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

                # Yield complete sentences as they accumulate
                while True:
                    m = _SENT_END.search(buffer)
                    if not m:
                        break
                    sentence = buffer[: m.start() + 1].strip()
                    buffer = buffer[m.end():]
                    if sentence:
                        yield {"type": "sentence", "text": sentence}

                # Accumulate streaming tool-call fragments
                for tc in (delta.get("tool_calls") or []):
                    idx = tc.get("index", 0)
                    if idx not in tc_fragments:
                        tc_fragments[idx] = {"id": "", "function": {"name": "", "arguments": ""}}
                    frag = tc_fragments[idx]
                    fid = tc.get("id", "")
                    if fid:
                        fid = fid
                    else:
                        fid = ""
                    frag["id"] = fid
                    fn = tc.get("function", {})
                    frag["function"]["name"] += fn.get("name") or ""
                    frag["function"]["arguments"] += fn.get("arguments") or ""

                finish = choice.get("finish_reason")
                if finish in ("stop", "tool_calls", "length"):
                    break

            # Flush any trailing content
            if buffer.strip():
                yield {"type": "sentence", "text": buffer.strip()}

            # Parse accumulated tool-call argument strings -> dicts
            tool_calls: List[Dict[str, Any]] = []
            for idx in sorted(tc_fragments):
                frag = tc_fragments[idx]
                args = frag["function"]["arguments"]
                try:
                    args = json.loads(args)
                except Exception:
                    pass   # leave as raw string; _execute_tool handles it
                tool_calls.append({
                    "id": frag["id"],
                    "function": {"name": frag["function"]["name"], "arguments": args},
                })

            yield {
                "type": "done",
                "content": full_content.strip(),
                "tool_calls": tool_calls,
            }

    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"Cannot reach OpenAI-compatible server at {url}. "
            "Make sure LM Studio / LocalAI / Jan is running and the server is started."
        )
    except requests.exceptions.Timeout:
        raise RuntimeError("OpenAline-compatible stream timed out.")
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"OpenAline-compatible HTTP error: {e.response.status_code}")
    except Exception as e:
        raise RuntimeError(f"OpenAline-compatible stream failed: {e}")


def call_llm_stream(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    timeout: int = 120,
) -> Generator[Dict[str, Any], None, None]:
    """
    Streaming chat request. Routes to Ollama or OpenAI-compatible backend.
    Yields:
        {"type": "sentence", "text": str}   — each complete sentence as it arrives
        {"type": "done", "content": str, "tool_calls": list}  — when stream ends
    Note: Image input is not supported in streaming mode for simplicity.
          For vision tasks, use the non-blocking call_llm instead.
    """
    provider = get_llm_provider()
    if provider == "openai":
        yield from _stream_openai(messages, tokens, timeout)
        return

    # Ollama streaming
    url, model = get_llm_settings()
    endpoint = f"{url}/api/chat"

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,  # Note: we do not format messages for images here because streaming with images is complex and not required for now.
        "stream": True,
        "keep_alive": -1,
        "options": {"num_predict": 150, "num_gpu": 99},
    }
    if tools:
        payload["tools"] = tools

    def _do_stream() -> Generator[Dict[str, Any], None, None]:
        with requests.post(endpoint, json=payload, timeout=timeout, stream=True) as resp:
            resp.raise_for_status()
            full_content = ""
            tool_cats: List[Dict[str, Any]] = []
            buffer = ""

            for raw in resp.iter_lines():
                if not raw:
                    continue
                try:
                    chunk = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg = chunk.get("message", {})
                delta = msg.get("content") or ""

                full_content += delta
                buffer += delta

                # Yield complete sentences as they accumulate
                while True:
                    m = _SENT_END.search(buffer)
                    if not m:
                        break
                    sentence = buffer[: m.start() + 1].strip()
                    buffer = buffer[m.end():]
                    if sentence:
                        yield {"type": "sentence", "text": sentence}

                tc = msg.get("tool_calls") or []
                if tc:
                    for t in tc:
                        tool_cats.append(t)

                if chunk.get("done"):
                    if buffer.strip():
                        yield {"type": "sentence", "text": buffer.strip()}

                    yield {
                        "type": "done",
                        "content": full_content.strip(),
                        "tool_calls": tool_cats,
                    }
                    return

    try:
        yield from _do_stream()
    except requests.exceptions.ConnectionError as e:
        print(f"[LLM] Stream ConnectionError — trying to restart Ollama… ({e})")
        if ensure_ollama_running():
            yield from _do_stream()
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