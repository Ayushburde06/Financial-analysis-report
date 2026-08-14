"""
config.py — Central configuration loader from .env
Loads and validates all API credentials and constants for the pipeline.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── Azure AI Document Intelligence ───────────────────────────────────────────
AZURE_DOC_INTEL_ENDPOINT: str = os.getenv("AZURE_DOC_INTEL_ENDPOINT", "")
AZURE_DOC_INTEL_KEY: str = os.getenv("AZURE_DOC_INTEL_KEY", "")

# ─── Azure OpenAI (GPT-5.6 Luna) ─────────────────────────────────────────────
AZURE_OPENAI_ENDPOINT: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_KEY: str = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_DEPLOYMENT: str = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o")
AZURE_OPENAI_API_VERSION: str = "2024-02-15-preview"

# ─── Mistral AI (Ministral 14B 3.0) ──────────────────────────────────────────
MISTRAL_API_KEY: str = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_VISION_MODEL: str = "mistral-small-latest"   # vision-capable, serverless

# ─── AWS Bedrock (Mistral Large 3 via Mantle Proxy) ──────────────────────────
AWS_BEARER_TOKEN: str = os.getenv("AWS_BEARER_TOKEN_BEDROCK", "")
AWS_BEDROCK_ENDPOINT: str = "https://bedrock-runtime.us-east-1.amazonaws.com"
AWS_MISTRAL_MODEL_ID: str = "mistral.mistral-large-2402-v1:0"

# ─── Pipeline Constants ────────────────────────────────────────────────────────
PDF_TEXT_MIN_CHARS: int = 100           # Min chars/page to classify as digital PDF
CONFIDENCE_THRESHOLD: float = 0.90     # Trigger LLM judge if below this
MAX_PAGES_SAMPLE: int = 80             # Hard cap on pages to process
CHUNK_SIZE: int = 800                   # Characters per embedding chunk
CHUNK_OVERLAP: int = 100               # Overlap between chunks


def validate_config() -> dict:
    """Check all required credentials are present and return status dict."""
    status = {
        "azure_doc_intel": bool(AZURE_DOC_INTEL_ENDPOINT and AZURE_DOC_INTEL_KEY),
        "azure_openai": bool(AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY),
        "mistral": bool(MISTRAL_API_KEY),
        "aws_bedrock": bool(AWS_BEARER_TOKEN),
    }
    return status


if __name__ == "__main__":
    s = validate_config()
    print("Configuration Status:")
    for k, v in s.items():
        print(f"  {k}: {'OK' if v else 'MISSING'}")
