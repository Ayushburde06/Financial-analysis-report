# API Keys Setup Guide

## Required API Keys for Optimized Pipeline

### 1. Mistral AI API Key (Stage 08 - Financial Extraction)

**Where to get it:**
1. Go to: https://console.mistral.ai/
2. Sign up or log in
3. Navigate to: API Keys section
4. Create new API key
5. Copy the key (starts with something like `sk-...` or similar)

**Cost**: ~$0.05 per report (97% cheaper than DeepSeek R1)

---

### 2. Azure OpenAI Credentials (Stage 11 - Unified Analyst)

**Where to get it:**

**Option A: If you already have Azure OpenAI:**
1. Go to: https://portal.azure.com
2. Navigate to your Azure OpenAI resource
3. Click on "Keys and Endpoint"
4. Copy:
   - Endpoint URL (e.g., `https://your-resource.openai.azure.com/`)
   - Key 1 or Key 2
   - Deployment name (e.g., `gpt-4o`, `gpt-4o-mini`)

**Option B: If you need to create Azure OpenAI:**
1. Go to: https://portal.azure.com
2. Create resource → Azure OpenAI
3. Deploy a model (choose `gpt-4o-mini` for cost efficiency)
4. Get endpoint, key, and deployment name as above

**Cost**: ~$0.10 per report (96% cheaper than 4-agent swarm)

---

## How to Add Keys to .env File

Open your `.env` file and replace the placeholder values:

```env
# ─── Mistral AI (Stage 08 - Financial Extraction) ────────────────────────────
MISTRAL_API_KEY=your_actual_mistral_key_here

# ─── Azure OpenAI (Stage 11 - Unified Analyst) ───────────────────────────────
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_KEY=your_actual_azure_key_here
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o-mini
```

---

## After Adding Keys

Run the test:
```bash
python test_optimized_pipeline.py
```

Or process all PDFs:
```bash
python batch_process.py
```

---

## Cost Breakdown (With Proper Keys)

| Stage | Service | Cost |
|-------|---------|------|
| 01 | Azure Doc Intelligence | $1.50 |
| 02-07 | Various (Bedrock) | $0.40 |
| **08** | **Mistral AI** ✅ | **$0.05** |
| 09-10 | Python (free) | $0.00 |
| **11** | **Azure OpenAI** ✅ | **$0.10** |
| 12-15 | Rendering | $0.20 |
| **TOTAL** | | **$2.25** |

**Previous cost**: $6.90  
**Savings**: $4.65 (67%)
