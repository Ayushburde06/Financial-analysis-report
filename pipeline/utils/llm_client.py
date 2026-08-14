"""
llm_client.py - Centralized LLM Execution Engine

Model architecture (current):
  - Azure Document Intelligence → Stage 01 OCR (not an LLM)
  - Parallel multimodel after OCR (USE_MULTIMODEL=1):
      Extraction: GPT-5.6 Luna + DeepSeek V4 Pro → merge JSON (Luna wins conflicts)
      Narrative:  GPT-5.6 Luna + DeepSeek V4 Pro → keep the stronger section of each
  - If multimodel is off: Luna first, DeepSeek fallback
"""
import os
import json
import re
import time
import base64
from concurrent.futures import ThreadPoolExecutor
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

_USE_DEEPSEEK = os.getenv("USE_DEEPSEEK_V4", "1").strip().lower() in ("1", "true", "yes")
_USE_MULTIMODEL = os.getenv("USE_MULTIMODEL", "1").strip().lower() in ("1", "true", "yes")

# ── Azure AI DeepSeek V4 Pro (disabled unless USE_DEEPSEEK_V4=1) ──────────────
_AZURE_ENDPOINT   = os.getenv("AZURE_DEEPSEEK_ENDPOINT", "")
_AZURE_DEPLOYMENT = os.getenv("AZURE_DEEPSEEK_DEPLOYMENT", "DeepSeek-V4-Pro")
_AZURE_API_KEY    = os.getenv("AZURE_DEEPSEEK_KEY", "")
_AZURE_API_VER    = os.getenv("AZURE_DEEPSEEK_API_VERSION", "2025-01-01-preview")

# ── Azure OpenAI GPT-5.6 Luna ─────────────────────────────────────────────────
_GPT5_ENDPOINT   = (os.getenv("AZURE_GPT5_ENDPOINT", "") or "").rstrip("/")
_GPT5_API_KEY    = os.getenv("AZURE_GPT5_KEY", "")
_GPT5_DEPLOYMENT = os.getenv("AZURE_GPT5_DEPLOYMENT", "gpt-5.6-luna")
try:
    _EXTRACTION_TIMEOUT = int(os.getenv("LLM_EXTRACTION_TIMEOUT", "120"))
except ValueError:
    _EXTRACTION_TIMEOUT = 120


def _azure_openai_chat(
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    json_mode: bool,
    timeout: int,
) -> str:
    """One Azure OpenAI v1 chat.completions call. Returns text or ''."""
    url = f"{_GPT5_ENDPOINT}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "api-key": _GPT5_API_KEY,
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_completion_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    if response.status_code == 200:
        data = response.json()
        choices = data.get("choices", [])
        if not choices:
            print(f"     [LLM Client] {model}: unexpected body {str(data)[:300]}")
            return ""
        message = choices[0].get("message", {}) or {}
        text = (message.get("content") or "").strip()
        finish = choices[0].get("finish_reason")
        if text:
            print(f"     [LLM Client] {model} responded ({len(text)} chars).")
            return text
        print(
            f"     [LLM Client] WARNING: {model} returned empty content "
            f"(finish_reason={finish})."
        )
        return ""

    if response.status_code == 400 and json_mode:
        print(f"     [LLM Client] {model} rejected JSON mode; retrying without it.")
        return _azure_openai_chat(
            model, system_prompt, user_prompt, max_tokens, False, timeout
        )

    if response.status_code == 429:
        raise RuntimeError("429")
    if response.status_code in (500, 503):
        raise RuntimeError(str(response.status_code))

    print(f"     [LLM Client] {model} Error {response.status_code}: {response.text[:400]}")
    return ""


def call_luna(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 8192,
    temperature: float = 0.3,
    json_mode: bool = False,
) -> str:
    """GPT-5.6 Luna — extraction (json_mode=True) and narrative (json_mode=False)."""
    del temperature  # GPT-5.x Azure deployments use the default temperature.
    if not _GPT5_API_KEY or not _GPT5_ENDPOINT:
        print("     [LLM Client] ERROR: Azure GPT-5.6 Luna is not configured.")
        return ""

    model = _GPT5_DEPLOYMENT
    timeout = _EXTRACTION_TIMEOUT
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            print(
                f"     [LLM Client] GPT-5.6 Luna ({'JSON' if json_mode else 'chat'}) "
                f"[Attempt {attempt}/{_MAX_ATTEMPTS}]..."
            )
            text = _azure_openai_chat(
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                json_mode=json_mode,
                timeout=timeout,
            )
            if text:
                return text
        except RuntimeError as exc:
            delay = 5 * attempt
            print(f"     [LLM Client] {model} {exc}. Waiting {delay}s...")
            time.sleep(delay)
            continue
        except Exception as exc:
            print(f"     [LLM Client] {model} request failed: {exc}")
        if attempt < _MAX_ATTEMPTS:
            time.sleep(2)
    print("     [LLM Client] GPT-5.6 Luna exhausted.")
    return ""


_CHART_VISION_PROMPT = """You are transcribing one slide from a company financial PDF.
Extract EVERY visible number, axis label, series name, legend, footnote and data label.

Rules:
- If this is a chart or graph, return a GitHub markdown table of the labelled values.
- Copy only numbers that are printed on the slide.
- Do NOT guess a value from bar height, line position, or pie size if no number is written.
- If the slide has no numeric labels, return the single word EMPTY.
- Return markdown only. No preamble.
"""


def call_luna_vision(
    image_bytes: bytes,
    prompt: str = "",
    mime: str = "image/png",
    max_tokens: int = 2500,
) -> str:
    """GPT-5.6 Luna vision — transcribe printed labels from a chart/figure page."""
    if not _GPT5_API_KEY or not _GPT5_ENDPOINT:
        print("     [LLM Client] ERROR: Azure GPT-5.6 Luna is not configured.")
        return ""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    url = f"{_GPT5_ENDPOINT}/chat/completions"
    headers = {"Content-Type": "application/json", "api-key": _GPT5_API_KEY}
    payload = {
        "model": _GPT5_DEPLOYMENT,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt or _CHART_VISION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                ],
            }
        ],
        "max_completion_tokens": max_tokens,
    }
    try:
        print("     [LLM Client] GPT-5.6 Luna vision (chart labels)...")
        response = requests.post(url, headers=headers, json=payload, timeout=_EXTRACTION_TIMEOUT)
    except Exception as exc:
        print(f"     [LLM Client] Luna vision request failed: {exc}")
        return ""
    if response.status_code != 200:
        print(f"     [LLM Client] Luna vision Error {response.status_code}: {response.text[:300]}")
        return ""
    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        return ""
    text = ((choices[0].get("message") or {}).get("content") or "").strip()
    if text.upper() == "EMPTY":
        return ""
    if text:
        print(f"     [LLM Client] Luna vision responded ({len(text)} chars).")
    return text


def _empty_value(value) -> bool:
    return value is None or value == "" or value == {} or value == []


def _parse_json_object(raw: str) -> dict:
    if not raw:
        return {}
    text = re.sub(
        r"<think(?:ing)?>.*?</think(?:ing)?>", "", raw, flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(r"```(?:json)?\s*|\s*```", "", text, flags=re.IGNORECASE).strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except (json.JSONDecodeError, TypeError, ValueError):
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return {}
        try:
            obj = json.loads(match.group(0))
            return obj if isinstance(obj, dict) else {}
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}


def _merge_extraction_dicts(luna: dict, deepseek: dict) -> tuple:
    """Luna wins conflicts; DeepSeek fills nulls/missing keys. Returns (merged, filled)."""
    filled = 0

    def merge(left, right):
        nonlocal filled
        if isinstance(left, dict) or isinstance(right, dict):
            left = left if isinstance(left, dict) else {}
            right = right if isinstance(right, dict) else {}
            out = dict(left)
            for key, rvalue in right.items():
                if key not in out or _empty_value(out[key]):
                    if not _empty_value(rvalue):
                        out[key] = rvalue
                        filled += 1
                else:
                    out[key] = merge(out[key], rvalue)
            return out
        if _empty_value(left) and not _empty_value(right):
            filled += 1
            return right
        return left

    return merge(luna or {}, deepseek or {}), filled


_NARRATIVE_MARKERS = (
    "BUSINESS_DESCRIPTION",
    "KEY_HIGHLIGHTS",
    "REPORT_SUBTITLE",
    "OUTLOOK_VALUATION",
)


def _strip_model_noise(text: str) -> str:
    text = re.sub(
        r"<think(?:ing)?>.*?</think(?:ing)?>", "", text or "", flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(r"\[VERIFIED\]", "", text)
    text = re.sub(r"\[N/A\]", "", text)
    return text.strip()


def _split_labelled_narrative(text: str) -> dict:
    result = {key.lower(): "" for key in _NARRATIVE_MARKERS}
    result["key_highlights"] = []
    if not text:
        return result
    marker_re = re.compile(
        r"\n?\s*\**\s*(BUSINESS_DESCRIPTION|KEY_HIGHLIGHTS|REPORT_SUBTITLE|OUTLOOK_VALUATION)\s*\**\s*\n"
    )
    parts = marker_re.split(text)
    current = None
    for part in parts:
        stripped = part.strip().strip("*").strip()
        if stripped in _NARRATIVE_MARKERS:
            current = stripped.lower()
            continue
        if not current or not stripped:
            continue
        if current == "key_highlights":
            bullets = []
            for line in stripped.splitlines():
                line = line.strip()
                if line.startswith(("•", "-", "*")):
                    bullet = re.sub(r"^[•\-\*]\s*", "", line).strip()
                    if bullet:
                        bullets.append(bullet)
            result["key_highlights"] = bullets
        else:
            result[current] = stripped
        current = None
    return result


def _better_prose(left: str, right: str) -> str:
    left = (left or "").strip()
    right = (right or "").strip()
    if left and not right:
        return left
    if right and not left:
        return right
    if len(right) >= len(left) + 40:
        return right
    if len(left) >= len(right) + 40:
        return left
    return right if len(right) >= len(left) else left


def _merge_narratives(luna_text: str, deepseek_text: str) -> str:
    """Keep the richer version of each labelled section; DeepSeek preferred when close."""
    luna_text = _strip_model_noise(luna_text)
    deepseek_text = _strip_model_noise(deepseek_text)
    luna_sec = _split_labelled_narrative(luna_text)
    ds_sec = _split_labelled_narrative(deepseek_text)
    labelled = any(
        luna_sec[k] or ds_sec[k]
        for k in ("business_description", "report_subtitle", "outlook_valuation")
    ) or luna_sec["key_highlights"] or ds_sec["key_highlights"]
    if not labelled:
        return _better_prose(luna_text, deepseek_text)

    bullets = []
    seen = set()
    for bullet in (ds_sec["key_highlights"] or []) + (luna_sec["key_highlights"] or []):
        key = re.sub(r"\s+", " ", bullet.lower())
        if key in seen or len(bullet) < 8:
            continue
        seen.add(key)
        bullets.append(bullet)
        if len(bullets) >= 8:
            break

    business = _better_prose(luna_sec["business_description"], ds_sec["business_description"])
    subtitle = _better_prose(luna_sec["report_subtitle"], ds_sec["report_subtitle"])
    outlook = _better_prose(luna_sec["outlook_valuation"], ds_sec["outlook_valuation"])
    highlight_block = "\n".join(f"• {b}" for b in bullets)
    return (
        f"BUSINESS_DESCRIPTION\n{business}\n\n"
        f"KEY_HIGHLIGHTS\n{highlight_block}\n\n"
        f"REPORT_SUBTITLE\n{subtitle}\n\n"
        f"OUTLOOK_VALUATION\n{outlook}"
    ).strip()


def _run_parallel(luna_fn, deepseek_fn) -> tuple:
    with ThreadPoolExecutor(max_workers=2) as pool:
        luna_fut = pool.submit(luna_fn)
        ds_fut = pool.submit(deepseek_fn)
        luna_text = luna_fut.result() or ""
        ds_text = ds_fut.result() or ""
    return luna_text, ds_text


def _fallback_deepseek(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    temperature: float,
) -> str:
    """Call DeepSeek V4 Pro after Luna fails. Returns '' if fallback is off."""
    if not _USE_DEEPSEEK:
        return ""
    print("     [LLM Client] Falling back to DeepSeek V4 Pro...")
    return _call_azure_deepseek_v4(
        system_prompt, user_prompt, max_tokens=max_tokens, temperature=temperature
    )


def call_azure_deepseek(system_prompt: str, user_prompt: str,
                        max_tokens: int = 8192, temperature: float = 0.3) -> str:
    """Narrative / chat: parallel Luna + DeepSeek, then keep the stronger sections."""
    if _USE_MULTIMODEL and _USE_DEEPSEEK and _AZURE_API_KEY:
        print("     [LLM Client] Multimodel narrative: GPT-5.6 Luna ∥ DeepSeek V4 Pro")
        luna_text, ds_text = _run_parallel(
            lambda: call_luna(
                system_prompt, user_prompt, max_tokens=max_tokens, json_mode=False
            ),
            lambda: _call_azure_deepseek_v4(
                system_prompt, user_prompt, max_tokens=max_tokens, temperature=temperature
            ),
        )
        merged = _merge_narratives(luna_text, ds_text)
        if merged:
            print(
                f"     [LLM Client] Narrative merge: Luna {len(luna_text)} chars, "
                f"DeepSeek {len(ds_text)} chars → {len(merged)} chars."
            )
            return merged
        return luna_text or ds_text

    text = call_luna(
        system_prompt, user_prompt, max_tokens=max_tokens, json_mode=False
    )
    if text:
        return text
    return _fallback_deepseek(
        system_prompt, user_prompt, max_tokens=max_tokens, temperature=temperature
    )


call_bedrock_deepseek_primary = call_azure_deepseek


def _call_azure_deepseek_v4(system_prompt: str, user_prompt: str,
                            max_tokens: int = 8192, temperature: float = 0.3) -> str:
    """DeepSeek V4 Pro only — used as Luna fallback. Does not call Luna."""
    if not _AZURE_API_KEY:
        print("     [LLM Client] Azure DeepSeek key missing. No fallback.")
        return ""

    url = (f"{_AZURE_ENDPOINT}/openai/deployments/{_AZURE_DEPLOYMENT}"
           f"/chat/completions?api-version={_AZURE_API_VER}")
    headers = {"Content-Type": "application/json", "api-key": _AZURE_API_KEY}
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "max_tokens":  max_tokens,
        "temperature": temperature,
    }
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            print(f"     [LLM Client] DeepSeek V4 Pro [Attempt {attempt}/{_MAX_ATTEMPTS}]...")
            response = requests.post(url, headers=headers, json=payload, timeout=_REQUEST_TIMEOUT)
            if response.status_code == 200:
                choices = response.json().get("choices", [])
                text = (choices[0].get("message", {}) or {}).get("content", "") if choices else ""
                if text:
                    print(f"     [LLM Client] DeepSeek V4 Pro responded ({len(text)} chars).")
                    return text
            elif response.status_code == 429:
                time.sleep(5 * attempt)
                continue
            else:
                print(f"     [LLM Client] DeepSeek Error {response.status_code}: {response.text[:400]}")
        except Exception as exc:
            print(f"     [LLM Client] DeepSeek request failed: {exc}")
        if attempt < _MAX_ATTEMPTS:
            time.sleep(3)
    print("     [LLM Client] DeepSeek V4 Pro exhausted.")
    return ""


def call_bedrock_deepseek(system_prompt: str, user_prompt: str) -> str:
    """Claim verifier / rewrite: Luna first, DeepSeek V4 Pro fallback."""
    text = call_luna(system_prompt, user_prompt)
    if text:
        return text
    return _fallback_deepseek(system_prompt, user_prompt, max_tokens=8192, temperature=0.3)


def call_extraction_llm(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 16384,
    temperature: float = 0.1,
    json_mode: bool = True,
) -> str:
    """Stage 08 extractor: parallel Luna + DeepSeek JSON, merge (Luna wins conflicts)."""
    del temperature
    if _USE_MULTIMODEL and _USE_DEEPSEEK and _AZURE_API_KEY:
        print("     [LLM Client] Multimodel extraction: GPT-5.6 Luna ∥ DeepSeek V4 Pro")
        luna_text, ds_text = _run_parallel(
            lambda: call_luna(
                system_prompt, user_prompt, max_tokens=max_tokens, json_mode=json_mode
            ),
            lambda: _call_azure_deepseek_v4(
                system_prompt, user_prompt, max_tokens=max_tokens, temperature=0.1
            ),
        )
        luna_obj = _parse_json_object(luna_text)
        ds_obj = _parse_json_object(ds_text)
        if luna_obj or ds_obj:
            merged, filled = _merge_extraction_dicts(luna_obj, ds_obj)
            print(
                f"     [LLM Client] Extraction merge: Luna {len(luna_obj)} keys, "
                f"DeepSeek {len(ds_obj)} keys, filled {filled} missing values, "
                f"{len(merged)} keys out."
            )
            return json.dumps(merged, ensure_ascii=False)
        return luna_text or ds_text

    text = call_luna(
        system_prompt, user_prompt, max_tokens=max_tokens, json_mode=json_mode
    )
    if text:
        return text
    return _fallback_deepseek(
        system_prompt, user_prompt, max_tokens=max_tokens, temperature=0.1
    )


def call_bedrock_mistral_large(system_prompt: str, user_prompt: str) -> str:
    """Stage 08 entry point — JSON extraction via Luna."""
    return call_extraction_llm(system_prompt, user_prompt)


def call_mistral_extraction(system_prompt: str, user_prompt: str) -> str:
    """Alias — Stage 08 JSON extraction."""
    return call_extraction_llm(system_prompt, user_prompt)


def call_mistral_direct(system_prompt: str, user_prompt: str) -> str:
    """Backward-compatible alias — multimodel narrative chat."""
    return call_azure_deepseek(system_prompt, user_prompt)
