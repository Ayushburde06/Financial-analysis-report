"""
llm_client.py - Centralized LLM Execution Engine

Model architecture:
  - DeepSeek V4 Pro (Azure AI) → Stage 11: Narrative reasoning & analysis (PRIMARY)
  - DeepSeek V4 Pro (Azure AI) → Stage 12: Fact verification / hallucination audit
  - DeepSeek R1 (Bedrock)      → Fallback if Azure is unavailable
  - GPT-5-mini (Azure OpenAI)  → Stage 08: Structured JSON financial extraction
"""
import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

try:
    _REQUEST_TIMEOUT = int(os.getenv("LLM_REQUEST_TIMEOUT", "60"))
except ValueError:
    _REQUEST_TIMEOUT = 60
try:
    _MAX_ATTEMPTS = max(1, int(os.getenv("LLM_MAX_ATTEMPTS", "2")))
except ValueError:
    _MAX_ATTEMPTS = 2

# ── Azure AI DeepSeek V4 Pro config ───────────────────────────────────────────
_AZURE_ENDPOINT   = os.getenv("AZURE_DEEPSEEK_ENDPOINT", "https://pavanshevankar9295-7639-resource.openai.azure.com")
_AZURE_DEPLOYMENT = os.getenv("AZURE_DEEPSEEK_DEPLOYMENT", "DeepSeek-V4-Pro")
_AZURE_API_KEY    = os.getenv("AZURE_DEEPSEEK_KEY", "")
_AZURE_API_VER    = os.getenv("AZURE_DEEPSEEK_API_VERSION", "2025-01-01-preview")

# ── Azure OpenAI GPT-5-mini config ────────────────────────────────────────────
_GPT5_ENDPOINT   = os.getenv("AZURE_GPT5_ENDPOINT", "")
_GPT5_API_KEY    = os.getenv("AZURE_GPT5_KEY", "")
_GPT5_DEPLOYMENT = os.getenv("AZURE_GPT5_DEPLOYMENT", "gpt-5-mini")


def call_azure_deepseek(system_prompt: str, user_prompt: str,
                        max_tokens: int = 8192, temperature: float = 0.3) -> str:
    """
    PRIMARY model: DeepSeek V4 Pro via Azure AI.
    Used for all narrative generation and claim verification.
    Falls back to Bedrock R1 if Azure is unavailable.
    """
    # Do not spend network time retrying an unconfigured provider. The normal
    # Bedrock fallback below remains available when it is configured.
    if not _AZURE_API_KEY:
        print("     [LLM Client] Azure DeepSeek key missing; using fallback directly.")
        return call_bedrock_deepseek(system_prompt, user_prompt)

    url = (f"{_AZURE_ENDPOINT}/openai/deployments/{_AZURE_DEPLOYMENT}"
           f"/chat/completions?api-version={_AZURE_API_VER}")

    headers = {
        "Content-Type": "application/json",
        "api-key": _AZURE_API_KEY,
    }
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "max_tokens":  max_tokens,
        "temperature": temperature,
    }

    max_attempts = _MAX_ATTEMPTS
    base_delay   = 5

    for attempt in range(1, max_attempts + 1):
        try:
            print(f"     [LLM Client] Calling Azure DeepSeek V4 Pro [Attempt {attempt}/{max_attempts}]...")
            response = requests.post(url, headers=headers, json=payload, timeout=_REQUEST_TIMEOUT)

            if response.status_code == 200:
                data    = response.json()
                choices = data.get("choices", [])
                if choices:
                    text = choices[0].get("message", {}).get("content", "")
                    if text:
                        print(f"     [LLM Client] Azure DeepSeek V4 Pro responded ({len(text)} chars).")
                        return text
                    print("     [LLM Client] WARNING: Azure returned empty content. Raw:", str(data)[:300])
                else:
                    print("     [LLM Client] Unexpected response:", str(data)[:300])

            elif response.status_code == 429:
                delay = base_delay * (2 ** (attempt - 1))
                print(f"     [LLM Client] Rate limit (429). Waiting {delay}s...")
                time.sleep(delay)
                continue

            elif response.status_code in (500, 503):
                delay = 5 * attempt
                print(f"     [LLM Client] Server error ({response.status_code}). Waiting {delay}s...")
                time.sleep(delay)
                continue

            else:
                print(f"     [LLM Client] Azure Error {response.status_code}: {response.text[:400]}")

        except Exception as e:
            print(f"     [LLM Client] Request Exception: {e}")

        if attempt < max_attempts:
            time.sleep(3)

    # Fallback to Bedrock R1
    print("     [LLM Client] Azure DeepSeek V4 Pro exhausted. Falling back to Bedrock R1...")
    return call_bedrock_deepseek(system_prompt, user_prompt)


# Keep old name as alias so no other file breaks
call_bedrock_deepseek_primary = call_azure_deepseek


def call_bedrock_deepseek(system_prompt: str, user_prompt: str) -> str:
    """
    FALLBACK: DeepSeek R1 via AWS Bedrock.
    Only called when Azure DeepSeek V4 Pro is unavailable.
    """
    token = os.getenv("AWS_BEARER_TOKEN_BEDROCK")
    if not token:
        print("     [LLM Client] ERROR: AWS_BEARER_TOKEN_BEDROCK missing. No fallback available.")
        return ""

    url = "https://bedrock-runtime.us-east-1.amazonaws.com/model/us.deepseek.r1-v1:0/invoke"
    headers = {
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {token}",
    }
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "max_tokens":  8192,
        "temperature": 0.3,
    }

    max_attempts = _MAX_ATTEMPTS
    base_delay   = 10

    for attempt in range(1, max_attempts + 1):
        try:
            print(f"     [LLM Client] Bedrock R1 fallback [Attempt {attempt}/{max_attempts}]...")
            response = requests.post(url, headers=headers, json=payload, timeout=_REQUEST_TIMEOUT)

            if response.status_code == 200:
                data    = response.json()
                choices = data.get("choices", [])
                if choices:
                    msg  = choices[0].get("message", {})
                    text = msg.get("content") or msg.get("reasoning_content") or ""
                    if text:
                        print(f"     [LLM Client] Bedrock R1 responded ({len(text)} chars).")
                        return text

            elif response.status_code == 429:
                delay = base_delay * (2 ** (attempt - 1))
                print(f"     [LLM Client] Rate limit (429). Waiting {delay}s...")
                time.sleep(delay)
                continue

            elif response.status_code == 503:
                time.sleep(5 * attempt)
                continue

            else:
                print(f"     [LLM Client] Bedrock Error {response.status_code}: {response.text[:300]}")

        except Exception as e:
            print(f"     [LLM Client] Request Exception: {e}")

        if attempt < max_attempts:
            time.sleep(3)

    print("     [LLM Client] All Bedrock R1 retries failed. Returning empty string.")
    return ""


def call_gpt5_mini(system_prompt: str, user_prompt: str,
                   max_tokens: int = 8192, temperature: float = 0.1,
                   json_mode: bool = True) -> str:
    """
    GPT-5-mini via Azure OpenAI.
    Used for Stage 08 structured JSON financial extraction (deterministic).
    Falls back to Azure DeepSeek V4 Pro on failure.
    """
    if not _GPT5_API_KEY or not _GPT5_ENDPOINT:
        print("     [LLM Client] WARNING: AZURE_GPT5_KEY or AZURE_GPT5_ENDPOINT not set. "
              "Skipping GPT-5-mini, using DeepSeek fallback directly.")
        return call_azure_deepseek(system_prompt, user_prompt, temperature=0.1)
    url = f"{_GPT5_ENDPOINT}/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "api-key": _GPT5_API_KEY,
    }
    payload = {
        "model": _GPT5_DEPLOYMENT,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "max_completion_tokens": max_tokens,
        # NOTE: GPT-5-mini only supports default temperature (1) — do not set it
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    max_attempts = _MAX_ATTEMPTS
    for attempt in range(1, max_attempts + 1):
        try:
            print(f"     [LLM Client] Calling GPT-5-mini via Azure [Attempt {attempt}/{max_attempts}]...")
            response = requests.post(url, headers=headers, json=payload, timeout=_REQUEST_TIMEOUT)

            if response.status_code == 200:
                data    = response.json()
                choices = data.get("choices", [])
                if choices:
                    text = choices[0].get("message", {}).get("content", "")
                    if text:
                        print(f"     [LLM Client] GPT-5-mini responded ({len(text)} chars).")
                        return text
                    print("     [LLM Client] WARNING: GPT-5-mini returned empty content. Raw:", str(data)[:300])
                else:
                    print("     [LLM Client] Unexpected response:", str(data)[:300])

            elif response.status_code == 429:
                delay = 5 * attempt
                print(f"     [LLM Client] Rate limit (429). Waiting {delay}s...")
                time.sleep(delay)
                continue

            elif response.status_code in (500, 503):
                delay = 5 * attempt
                print(f"     [LLM Client] Server error ({response.status_code}). Waiting {delay}s...")
                time.sleep(delay)
                continue

            else:
                print(f"     [LLM Client] GPT-5-mini Error {response.status_code}: {response.text[:400]}")

        except Exception as e:
            print(f"     [LLM Client] Request Exception: {e}")

        if attempt < max_attempts:
            time.sleep(2)

    print("     [LLM Client] GPT-5-mini failed. Falling back to Azure DeepSeek V4 Pro...")
    return call_azure_deepseek(system_prompt, user_prompt, temperature=0.1)


def call_bedrock_mistral_large(system_prompt: str, user_prompt: str) -> str:
    """
    Now routes to GPT-5-mini via Azure OpenAI.
    (Was Mistral Large 3 via AWS Bedrock — replaced per user request.)
    Falls back to Azure DeepSeek V4 Pro on failure.
    """
    return call_gpt5_mini(system_prompt, user_prompt)


def call_mistral_extraction(system_prompt: str, user_prompt: str) -> str:
    """Alias — routes to GPT-5-mini via Azure OpenAI for JSON extraction."""
    return call_gpt5_mini(system_prompt, user_prompt)


def call_mistral_direct(system_prompt: str, user_prompt: str) -> str:
    """Backward-compatible alias — now routes to Azure DeepSeek V4 Pro."""
    return call_azure_deepseek(system_prompt, user_prompt)
