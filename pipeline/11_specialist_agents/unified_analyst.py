"""
unified_analyst.py - Single Unified Analyst Agent (Cost-Optimized)

Replaces the 4-agent swarm (FinancialAnalyst, GrowthAnalyst, RiskAnalyst, ValuationAnalyst)
with a single GPT-4o mini call that generates all sections in one pass.

Cost comparison:
- Multi-agent: 4 calls × $0.60 = $2.40
- Unified: 1 call × $0.10 = $0.10
- Savings: $2.30 per report (96% reduction)
"""
import os
import json
import requests
from typing import Dict, Any
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()


class UnifiedAnalyst:
    """
    Single analyst that generates all narrative sections in one LLM call.
    Uses Azure OpenAI GPT-4o mini for cost efficiency.
    """
    
    def __init__(self):
        self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.api_key = os.getenv("AZURE_OPENAI_KEY")
        self.deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o")
        self.api_version = "2024-02-15-preview"
    
    def generate(self, evidence_packet: BaseModel) -> str:
        """
        Takes a typed evidence packet and returns complete narrative covering:
        1. Financial Analysis (Revenue, Margins, PAT)
        2. Growth Analysis (YoY, QoQ trends)
        3. Risk Analysis (Debt, Cash Flow, Operational risks)
        4. Valuation Summary (Multiples, DCF context)
        
        Args:
            evidence_packet: FinancialAnalystEvidence pydantic object with validated data
        
        Returns:
            Complete multi-section narrative string
        """
        # Rule 15: Enforce LLM Quarantine - must be Pydantic object
        if not isinstance(evidence_packet, BaseModel):
            raise TypeError(
                f"LLM Quarantine Violation: Unified Analyst received raw data of type {type(evidence_packet)}. "
                "Must be a verified Pydantic evidence packet."
            )
        
        # Convert evidence to JSON
        packet_json = evidence_packet.model_dump_json(indent=2)
        
        # Build comprehensive prompt
        system_prompt = self._build_system_prompt()
        user_prompt = f"""Evidence Packet (Python-Verified Financial Data):
```json
{packet_json}
```

Generate a comprehensive equity research narrative with these 4 sections:

## 1. FINANCIAL ANALYSIS
Analyze revenue trajectory, margin trends, and PAT movement. Explain WHY numbers changed and WHAT IT MEANS for the business. Include YoY and QoQ comparisons where available. Cite specific values from the evidence packet.

## 2. GROWTH ANALYSIS
Evaluate growth drivers, CAGR trends, and forward projections (FY26E, FY27E). Discuss sustainability of growth rates and key catalysts. Compare historical vs. forward estimates.

## 3. RISK ANALYSIS
Identify 3-5 key risks based on debt levels, cash flow patterns, margin pressure, and operational challenges. Each risk must be grounded in specific metrics from the evidence packet.

## 4. VALUATION SUMMARY
Provide valuation context using available multiples and forward projections. Discuss whether current metrics suggest premium/discount valuation. Do NOT make BUY/HOLD/SELL recommendations (handled by deterministic engine).

CRITICAL RULES:
- Every numerical claim MUST cite the source field from JSON (e.g., "Revenue grew 15% [pl.revenue.q_current]")
- Use professional institutional tone
- Never mention OCR, RAG, embeddings, or AI processes
- Never invent numbers not in the evidence packet
- Tag all estimates with [E] suffix
"""
        
        # Call Azure OpenAI (GPT-4o mini)
        response = self._call_azure_openai(system_prompt, user_prompt)
        
        return response
    
    def _build_system_prompt(self) -> str:
        """System prompt enforcing institutional research standards."""
        return """You are a Senior Equity Research Analyst writing institutional-grade financial analysis.

TONE & STYLE:
- Professional, Institutional, Objective, Technical
- Never conversational or AI-assistant language
- First present facts, then interpret, then explain implications, then mention risks

CITATION RULES (CRITICAL):
- Every number you write MUST include source citation: [field.path]
- Example: "Revenue reached ₹1,250 Cr [pl.revenue.fy24]"
- Example: "QoQ growth of 12% [pl.revenue.q_current vs q_prev_qtr]"
- Never output a sentence with numbers without explicit JSON field mapping

PROHIBITED:
- Never mention: OCR, RAG, embeddings, vector databases, retrieval systems, AI/ML
- Never use conversational phrases like "Based on the data provided..."
- Never make BUY/HOLD/SELL recommendations (handled by separate deterministic engine)

OUTPUT FORMAT:
- Use markdown headers (##) for each section
- Professional paragraph structure
- Quantify every claim with specific metrics
- Explain causality: WHY → WHAT → IMPACT
"""
    
    def _call_azure_openai(self, system_prompt: str, user_prompt: str) -> str:
        """Call Azure OpenAI GPT-4o mini API."""
        if not self.endpoint or not self.api_key:
            print("     [Unified Analyst] ERROR: Azure OpenAI credentials missing.")
            return ""
        
        # Construct Azure OpenAI endpoint
        url = f"{self.endpoint}/openai/deployments/{self.deployment}/chat/completions?api-version={self.api_version}"
        
        headers = {
            "Content-Type": "application/json",
            "api-key": self.api_key
        }
        
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 4096,
            "top_p": 0.95
        }
        
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                print(f"     [Unified Analyst] Calling Azure OpenAI (GPT-4o mini) [Attempt {attempt}/{max_attempts}]...")
                response = requests.post(url, headers=headers, json=payload, timeout=90)
                
                if response.status_code == 200:
                    data = response.json()
                    choices = data.get("choices", [])
                    if choices:
                        text = choices[0].get("message", {}).get("content", "")
                        if text:
                            print(f"     [Unified Analyst] Generated narrative ({len(text)} chars).")
                            return text
                        else:
                            print("     [Unified Analyst] WARNING: Empty response from Azure OpenAI.")
                
                elif response.status_code == 429:
                    import time
                    delay = 5 * attempt
                    print(f"     [Unified Analyst] Rate limit (429). Waiting {delay}s...")
                    time.sleep(delay)
                    continue
                else:
                    print(f"     [Unified Analyst] Azure OpenAI Error {response.status_code}: {response.text[:300]}")
            
            except Exception as e:
                print(f"     [Unified Analyst] Request Exception: {e}")
            
            if attempt < max_attempts:
                import time
                time.sleep(2)
        
        print("     [Unified Analyst] All retries failed. Returning empty string.")
        return ""
