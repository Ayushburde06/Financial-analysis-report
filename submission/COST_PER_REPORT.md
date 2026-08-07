# Cost Per Report Breakdown

## Pricing (as of 2025-2026)

| Service | Model | Input | Output |
|---------|-------|-------|--------|
| Azure Document Intelligence (OCR) | Layout model | $0.01 / page | — |
| AWS Bedrock (extraction + self-heal) | Mistral Large 3 675B | $4.00 / 1M tokens | $12.00 / 1M tokens |
| Azure AI (narrative + projections) | DeepSeek V4 Pro | ~$0.50 / 1M tokens | ~$2.00 / 1M tokens |

> Token estimates: ~4 chars = 1 token. Input prompt sizes estimated from evidence
> packet + system prompt. Output sizes measured from API response logs.

## Per-Report Cost

| Company | OCR Pages | OCR Cost | Mistral Cost | DeepSeek Cost | **Total** |
|---------|-----------|----------|-------------|---------------|-----------|
| ICICI Bank | 59 | $0.590 | $0.046 | $0.003 | **$0.64** |
| JSW Energy | 49 | $0.490 | $0.027 | $0.003 | **$0.52** |
| POCL | 41 | $0.410 | $0.038 | $0.003 | **$0.45** |
| LTTS | 17 | $0.170 | $0.028 | $0.003 | **$0.20** |
| **Average** | **42** | **$0.42** | **$0.035** | **$0.003** | **$0.45** |

## Key Insight

**OCR (Azure Document Intelligence) is ~92% of the cost.** The LLM calls
(Mistral + DeepSeek combined) are only ~8% — less than $0.04 per report.

The cost scales almost linearly with input document page count, not with
company complexity or report length.

## Cost Breakdown by Component

```
┌─────────────────────────────────────────────────┐
│  OCR (Azure DI)           92%  ████████████████  │
│  Extraction (Mistral L3)    6%  █               │
│  Self-heal (Mistral L3)     1%  ▏               │
│  Narrative (DeepSeek V4P)   1%  ▏               │
│  Projections (DeepSeek+M)   1%  ▏               │
└─────────────────────────────────────────────────┘
```

## How to Reduce Cost

1. **Use a cheaper OCR** — Tesseract (free, open-source) instead of Azure DI
   would drop cost to ~$0.04/report (LLM only). Trade-off: lower OCR accuracy.
2. **Cache Screener.in + yfinance data** — avoid re-fetching market data on every run.
3. **Batch API calls** — Bedrock/Azure offer batch discounts (50% off).
4. **Use DeepSeek API directly** (not via Azure) — $0.27/1M input vs ~$0.50/1M.
