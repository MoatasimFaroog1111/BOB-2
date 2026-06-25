"""
Unified LLM service for GuardianAI.

Tries Ollama (local Gemma) first, falls back to DeepSeek API.
Both expose an OpenAI-compatible chat completions interface.
"""
import json
import logging
import urllib.request
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "gemma2:9b"
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"


def _call_ollama(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.0,
    timeout: int = 120,
) -> Optional[str]:
    """Try calling local Ollama instance. Returns None if unavailable."""
    url = f"{OLLAMA_BASE_URL}/api/chat"
    data = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {"temperature": temperature},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            res_json = json.loads(response.read().decode("utf-8"))
            return res_json.get("message", {}).get("content", "").strip()
    except Exception as e:
        logger.debug("Ollama unavailable: %s", e)
        return None


def _call_deepseek(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.0,
    timeout: int = 120,
) -> Optional[str]:
    """Call DeepSeek API. Returns None if API key missing or call fails."""
    api_key = settings.DEEPSEEK_API_KEY
    if not api_key:
        return None

    data = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
    }
    req = urllib.request.Request(
        DEEPSEEK_API_URL,
        data=json.dumps(data).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            res_json = json.loads(response.read().decode("utf-8"))
            return res_json["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning("DeepSeek API call failed: %s", e)
        return None


def chat(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.0,
    timeout: int = 120,
) -> Optional[str]:
    """Send a chat completion request. Tries Ollama first, then DeepSeek."""
    result = _call_ollama(system_prompt, user_prompt, temperature, timeout)
    if result:
        logger.info("LLM response from Ollama/Gemma")
        return result

    result = _call_deepseek(system_prompt, user_prompt, temperature, timeout)
    if result is not None:
        logger.info("LLM response from DeepSeek API")
        return result

    logger.warning("No LLM provider available")
    return None
