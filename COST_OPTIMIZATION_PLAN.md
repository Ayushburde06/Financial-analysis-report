# Cost Optimization Plan - Phased Approach

## Current Cost Breakdown (150-page PDF)

| Stage | Service | Current Cost | Notes |
|-------|---------|--------------|-------|
| **Stage 01** | Azure Document Intelligence (OCR) | **$1.50** | ✅ **KEEP AS IS** |
| Stage 02 | Mistral LLM (classification) | $0.20 | ⚠️ To optimize |
| Stage 03-06 | Various LLMs | $0.50 | ⚠️ To optimize |
| **Stage 08** | DeepSeek R1 (extraction) | **$1.50** | 🔴 **EXPENSIVE - Replace** |
| Stage 09-10 | LLM + calculations | $0.50 | 🔴 **Move to Python** |
| **Stage 11-12** | Multi-agent swarm (4 agents) | **$2.50** | 🔴 **EXPENSIVE - Simplify** |
| Stage 14-15 | Report generation + rendering | $0.20 | ✅ Already cheap |
| **TOTAL** | | **$6.90** | |

---

## Phase 1: Keep Stage 01 OCR (Current Phase) ✅

**No changes to Stage 01**
- Continue using Azure Document Intelligence
- Cost: $1.50 per 150-page PDF
- Reason: OCR quality is good, extraction works

---

## Phase 2: Optimize Post-OCR Stages (Next Phase) 🎯

### Target: Reduce $5.40 → $0.50 (90% savings on post-OCR stages)

### Changes After Stage 01:

#### 1. Stage 08: Replace DeepSeek R1 with Ministral 14B
**Current:**
```python
# Stage 08: Using expensive DeepSeek R1 for extraction
response = call_bedrock_deepseek(system_prompt, prompt)  # $1.50
```

**Optimized:**
```python
# Stage 08: Use Ministral 14B (designed for financial extraction)
response = call_ministral_extraction(system_prompt, prompt)  # $0.05 ✅ 97% savings
```

**Savings**: $1.45 per report

---

#### 2. Stage 09-10: Move ALL Calculations to Python
**Current:**
```python
# LLM calculates growth rates, margins, ratios (WRONG!)
fa_evidence = stage_10.EvidenceBuilder.build_financial_evidence(raw_financials)
# Contains LLM-calculated metrics
```

**Optimized:**
```python
# Python calculates ALL financial metrics
def calculate_metrics(raw_financials: dict) -> dict:
    """Pure Python calculations - zero LLM cost."""
    return {
        "revenue_growth_yoy": (fy24 - fy23) / fy23 * 100,  # Python math
        "ebitda_margin": ebitda / revenue * 100,           # Python math
        "roe": pat / equity * 100,                         # Python math
        "cagr_3y": ((fy24/fy22)**(1/3) - 1) * 100,        # Python math
    }

fa_evidence = {
    "raw_financials": raw_financials,      # From Stage 08
    "calculated_metrics": calculate_metrics(raw_financials),  # Python only
}
```

**Savings**: $0.50 per report

---

#### 3. Stage 11: Replace Multi-Agent Swarm with Single Analyst
**Current (EXPENSIVE):**
```python
# Stage 11: Multi-Agent Swarm (4 separate LLM calls)
fa_agent = FinancialAnalyst()        # $0.60
growth_agent = GrowthAnalyst()       # $0.60
risk_agent = RiskAnalyst()           # $0.65
valuation_agent = ValuationAnalyst() # $0.65

fa_narrative = fa_agent.generate(fa_evidence)
# Total: $2.50 in LLM calls
```

**Optimized (CHEAP):**
```python
# Stage 11: Single Unified Analyst with GPT-4o mini
def generate_complete_narrative(evidence: dict) -> str:
    """Single LLM call generates all sections."""
    prompt = f"""
    Based on the following VERIFIED financial data, write:
    1. Financial Analysis
    2. Growth Analysis  
    3. Risk Analysis
    4. Valuation Summary
    
    Verified Data (Python-calculated):
    {json.dumps(evidence, indent=2)}
    """
    return call_gpt4o_mini(prompt)  # $0.10 ✅ Single call

fa_narrative = generate_complete_narrative(fa_evidence)
# Total: $0.10 (95% savings)
```

**Savings**: $2.40 per report

---

## Summary: Cost Impact

### After Phase 2 Optimization:

| Component | Before | After | Savings |
|-----------|--------|-------|---------|
| Stage 01 (OCR) | $1.50 | **$1.50** | $0 (kept as is) |
| Stage 08 (Extraction) | $1.50 | **$0.05** | $1.45 |
| Stage 09-10 (Calculations) | $0.50 | **$0.00** | $0.50 |
| Stage 11 (Narrative) | $2.50 | **$0.10** | $2.40 |
| Other stages | $0.90 | **$0.35** | $0.55 |
| | | | |
| **TOTAL** | **$6.90** | **$2.00** | **$4.90 (71%)** |

### Per 150-Page Report:
- **Before optimization**: $6.90
- **After optimization**: $2.00
- **Savings**: $4.90 (71% reduction)

### Monthly Impact (30 reports):
- **Before**: $207
- **After**: $60
- **Annual savings**: $1,764

---

## Implementation Order

### ✅ Phase 1: Done (Keep Stage 01)
- No changes to OCR
- Continue using Azure Document Intelligence

### 🎯 Phase 2: Next (Optimize Stages 08, 09-10, 11)
1. **Week 1**: Replace DeepSeek R1 with Ministral 14B (Stage 08)
2. **Week 2**: Move calculations to Python (Stage 09-10)
3. **Week 3**: Simplify to single analyst agent (Stage 11)
4. **Week 4**: Test & validate accuracy

---

## Key Principles (From .agents/AGENTS.md)

✅ **Rule #5**: Python exclusively computes all financial calculations
✅ **Rule #6**: LLMs may NEVER determine recommendations  
✅ **Rule #15**: LLMs never receive raw OCR without Python validation
✅ **Rule #7**: Never OCR charts - regenerate from data

These rules are currently **violated** in Stages 08-11, causing the high costs.

---

## Next Steps

**Ready to proceed?**
1. Keep Stage 01 OCR as is ($1.50) ✅
2. Optimize Stages 08-11 ($4.90 savings) 🎯
3. Test on your 4 PDFs
4. Deploy to production

**Say "yes" to start Phase 2 optimization!**
