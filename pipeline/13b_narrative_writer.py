"""
13b_narrative_writer.py
Transforms the structured JSON intelligence from the Lead Analyst into professional English prose.
"""
import json
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
try:
    from pipeline.utils.llm_client import call_bedrock_deepseek
except ImportError:
    from utils.llm_client import call_bedrock_deepseek

def generate_narrative(structured_intelligence: dict) -> dict:
    """
    Takes the structured JSON output from Stage 13 and expands it into 
    cohesive, professional paragraphs.
    """
    prompt_json = json.dumps(structured_intelligence, indent=2)
    system_prompt = """You are a Senior Equity Research Editor at an institutional brokerage.
Your job is to take structured intelligence JSON and write professional, flowing English paragraphs for a research report.

CRITICAL INSTRUCTIONS FOR LENGTH AND DENSITY:
1. Do NOT write short 1-sentence summaries. 
2. You MUST write comprehensive, multi-paragraph analysis (150-250 words, 2-3 paragraphs per section).
3. Do not invent facts or metrics. Deeply analyze and interpret the provided structured data.
4. Ensure the text flows professionally and deeply explores the implications of the data.

Output a JSON dictionary with these exact string keys:
- "executive_summary"
- "financial_analysis"
- "business_analysis"
- "risk_analysis"
- "management_commentary"
- "investment_thesis"
- "conclusion"

Return ONLY a valid JSON dictionary. Do not include markdown formatting like ```json or any other text outside the JSON object.
"""

    user_prompt = f"Structured Intelligence:\n```json\n{prompt_json}\n```\nWrite the comprehensive narratives."
    
    raw_response = call_bedrock_deepseek(system_prompt, user_prompt)
    if raw_response:
        # Clean up any potential markdown formatting
        cleaned = raw_response.replace("```json", "").replace("```", "").strip()
        try:
            narratives = json.loads(cleaned)
            return narratives
        except json.JSONDecodeError as e:
            print(f"Failed to parse LLM narrative response: {e}")
            
    # Do not manufacture a report when the narrative model is unavailable.
    growth = structured_intelligence.get("growth") or {}
    profitability = structured_intelligence.get("profitability") or {}
    risks = structured_intelligence.get("risks") or []
    growth_evidence = ", ".join(str(item) for item in growth.get("evidence", []) if item)
    profitability_evidence = ", ".join(
        str(item) for item in profitability.get("evidence", []) if item
    )
    risk_text = "; ".join(str(item) for item in risks if item)
    return {
        "executive_summary": "",
        "financial_analysis": (
            f"Recorded profitability evidence: {profitability_evidence}."
            if profitability_evidence else ""
        ),
        "business_analysis": (
            f"Recorded growth evidence: {growth_evidence}."
            if growth_evidence else ""
        ),
        "risk_analysis": f"Recorded risks: {risk_text}." if risk_text else "",
        "management_commentary": "",
        "investment_thesis": "",
        "conclusion": "",
    }
