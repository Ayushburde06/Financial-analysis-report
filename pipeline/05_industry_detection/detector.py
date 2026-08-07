"""
Stage 05: Industry Detection Engine

Detects the sector from OCR text + knowledge graph using keyword scoring.
Uses weighted keywords — company-name matches score 5x, domain terms score 1x.
Falls back to Mistral Large 3 if no keywords match (handles new/unknown companies).

Covers 13 sectors:
  Banking, NBFC, IT Services, Pharma, Energy, Infrastructure, FMCG,
  Auto, Metals, Cement, Telecom, Internet & Retail, Other (generic fallback)
"""
from typing import Dict, Any, List, Tuple

# ─── Sector keyword definitions ───────────────────────────────────────────────
# Format: { sector: [(keyword, weight), ...] }
# Weight 5 = company name / very strong signal
# Weight 3 = strong domain-specific term
# Weight 1 = general term (may appear in multiple sectors)

SECTOR_KEYWORDS: Dict[str, List[Tuple[str, int]]] = {

    "Banking": [
        # Company names
        ("icici bank", 5), ("icici", 4), ("hdfc bank", 5), ("hdfc", 4), ("state bank of india", 5), ("sbi", 5),
        ("axis bank", 5), ("axis", 4), ("kotak mahindra bank", 5), ("kotak bank", 5),
        ("indusind bank", 5), ("yes bank", 5), ("bank of baroda", 5),
        ("canara bank", 5), ("union bank", 5), ("punjab national bank", 5),
        ("federal bank", 5), ("bandhan bank", 5), ("dcb bank", 5),
        ("rbl bank", 5), ("city union bank", 5), ("karur vysya", 5),
        ("south indian bank", 5), ("bank of india", 5), ("central bank", 5),
        # Strong domain terms
        ("net interest income", 3), ("net interest margin", 3),
        ("gross npa", 3), ("net npa", 3), ("gnpa", 3), ("nnpa", 3),
        ("provision coverage ratio", 3), ("pcr", 3),
        ("casa ratio", 3), ("casa", 3), ("credit deposit ratio", 3),
        ("capital adequacy ratio", 3), ("crar", 3), ("tier 1", 3),
        ("slippage ratio", 3), ("credit cost", 3), ("restructured assets", 3),
        ("advances", 3), ("deposits", 3), ("nii", 3), ("banking", 3),
        # General terms
        ("bank", 2), ("loan book", 1), ("retail loans", 1), ("corporate loans", 1),
        ("microfinance", 1), ("priority sector", 1), ("basel", 1),
    ],

    "NBFC": [
        ("bajaj finance", 5), ("muthoot finance", 5), ("cholamandalam", 5),
        ("shriram finance", 5), ("mahindra finance", 5), ("l&t finance", 5),
        ("pnb housing", 5), ("can fin homes", 5), ("aavas financiers", 5),
        ("home first finance", 5), ("five star business finance", 5),
        ("credit access grameen", 5), ("spandana sphoorty", 5),
        ("assets under management", 3), ("aum", 3),
        ("disbursements", 3), ("yield on advances", 3), ("cost of funds", 3),
        ("gold loan", 3), ("vehicle finance", 3), ("housing finance", 3),
        ("nbfc", 3), ("non-banking financial", 3),
        ("microfinance institution", 3), ("mfi", 3),
    ],

    "IT Services": [
        ("infosys", 5), ("wipro", 5), ("tata consultancy", 5), ("tcs", 5),
        ("hcl technologies", 5), ("hcl tech", 5), ("tech mahindra", 5),
        ("l&t technology", 5), ("ltts", 5), ("mphasis", 5), ("hexaware", 5),
        ("persistent systems", 5), ("coforge", 5), ("zensar", 5),
        ("kpit technologies", 5), ("mastek", 5), ("cyient", 5),
        ("attrition rate", 3), ("deal wins", 3), ("total contract value", 3),
        ("tcv", 3), ("utilization rate", 3), ("offshore revenue", 3),
        ("headcount", 3), ("digital transformation", 3),
        ("revenue from operations", 1), ("software services", 1),
        ("bpo", 1), ("it services", 1), ("ites", 1),
    ],

    "Pharma": [
        ("sun pharma", 5), ("cipla", 5), ("dr reddy", 5), ("divi's laboratories", 5),
        ("biocon", 5), ("aurobindo pharma", 5), ("lupin", 5), ("torrent pharma", 5),
        ("alkem laboratories", 5), ("ipca laboratories", 5), ("glenmark", 5),
        ("natco pharma", 5), ("laurus labs", 5), ("granules india", 5),
        ("anda filing", 3), ("usfda", 3), ("abbreviated new drug application", 3),
        ("active pharmaceutical ingredient", 3), ("api", 3),
        ("r&d expense", 3), ("clinical trial", 3), ("formulation", 3),
        ("domestic formulation", 3), ("nda", 3), ("biosimilar", 3),
        ("pharma", 1), ("pharmaceutical", 1), ("drug", 1),
    ],

    "Energy": [
        ("jsw energy", 5), ("adani green", 5), ("ntpc", 5), ("power grid", 5),
        ("tata power", 5), ("torrent power", 5), ("cesc", 5),
        ("renew power", 5), ("greenko", 5), ("sterling wilson", 5),
        ("installed capacity", 3), ("plant load factor", 3), ("plf", 3),
        ("megawatt", 3), ("gigawatt", 3), ("mw capacity", 3), ("gw capacity", 3),
        ("power generation", 3), ("renewable energy", 3), ("solar capacity", 3),
        ("wind capacity", 3), ("transmission line", 3),
        ("units generated", 1), ("electricity", 1), ("power sector", 1),
    ],

    "Infrastructure": [
        ("larsen & toubro", 5), ("l&t", 5), ("ircon", 5), ("knr constructions", 5),
        ("capacite infraprojects", 5), ("rites", 5), ("engineers india", 5),
        ("dilip buildcon", 5), ("pnc infratech", 5), ("hg infra", 5),
        ("order book", 3), ("order inflow", 3), ("order backlog", 3),
        ("epc contract", 3), ("engineering procurement construction", 3),
        ("project execution", 3), ("roads and highways", 3),
        ("metro rail", 3), ("irrigation project", 3),
        ("construction revenue", 1), ("infrastructure", 1),
    ],

    "FMCG": [
        ("hindustan unilever", 5), ("hul", 5), ("itc limited", 5),
        ("nestle india", 5), ("britannia", 5), ("dabur india", 5),
        ("marico", 5), ("godrej consumer", 5), ("emami", 5),
        ("colgate palmolive", 5), ("procter & gamble", 5),
        ("volume growth", 3), ("value growth", 3), ("rural demand", 3),
        ("urban demand", 3), ("category growth", 3),
        ("advertising and promotion", 3), ("a&p spend", 3),
        ("gross margin", 3), ("distribution channel", 3),
        ("consumer goods", 1), ("fmcg", 1), ("personal care", 1),
        ("food products", 1), ("beverages", 1),
    ],

    "Auto": [
        ("maruti suzuki", 5), ("tata motors", 5), ("mahindra & mahindra", 5),
        ("bajaj auto", 5), ("hero motocorp", 5), ("eicher motors", 5),
        ("tvs motor", 5), ("ashok leyland", 5), ("force motors", 5),
        ("motherson sumi", 5), ("minda industries", 5), ("bosch india", 5),
        ("vehicle volumes", 3), ("wholesale dispatches", 3), ("retail offtake", 3),
        ("passenger vehicle", 3), ("commercial vehicle", 3), ("two-wheeler", 3),
        ("three-wheeler", 3), ("electric vehicle", 3), ("ev penetration", 3),
        ("average selling price", 3), ("asp per unit", 3),
        ("auto", 1), ("automobile", 1), ("automotive", 1),
    ],

    "Metals": [
        ("tata steel", 5), ("jsw steel", 5), ("steel authority of india", 5),
        ("sail", 5), ("hindalco", 5), ("vedanta", 5), ("nalco", 5),
        ("coal india", 5), ("nmdc", 5), ("hindustan zinc", 5),
        ("production volume", 3), ("sales volume", 3), ("realization per tonne", 3),
        ("ebitda per tonne", 3), ("iron ore", 3), ("coking coal", 3),
        ("sponge iron", 3), ("hot rolled coil", 3), ("hrc", 3),
        ("lme prices", 3), ("metal prices", 3),
        ("steel", 1), ("aluminium", 1), ("copper", 1), ("zinc", 1), ("metals", 1),
    ],

    "Cement": [
        ("ultratech cement", 5), ("ambuja cement", 5), ("acc limited", 5),
        ("shree cement", 5), ("dalmia bharat", 5), ("jk cement", 5),
        ("ramco cement", 5), ("india cements", 5), ("birla corporation", 5),
        ("cement volume", 3), ("realization per tonne", 3),
        ("ebitda per tonne", 3), ("capacity utilisation", 3),
        ("clinker production", 3), ("blended cement", 3),
        ("grey cement", 3), ("white cement", 3),
        ("cement", 1), ("mtpa", 1), ("million tonnes", 1),
    ],

    "Telecom": [
        ("airtel", 5), ("bharti airtel", 5), ("reliance jio", 5),
        ("vodafone idea", 5), ("vi", 5), ("bsnl", 5), ("mtnl", 5),
        ("indus towers", 5), ("abb infrastructure", 5),
        ("average revenue per user", 3), ("arpu", 3),
        ("subscriber base", 3), ("active subscribers", 3),
        ("spectrum", 3), ("4g coverage", 3), ("5g rollout", 3),
        ("data consumption", 3), ("data traffic", 3), ("exabytes", 3),
        ("telecom", 1), ("mobile services", 1), ("broadband", 1),
    ],

    "Internet & Retail": [
        # Company names — strong signals
        ("zomato", 5), ("eternal limited", 5), ("eternal ltd", 5),
        ("swiggy", 5), ("nykaa", 5), ("fsn e-commerce", 5),
        ("meesho", 5), ("flipkart", 5), ("amazon india", 5),
        ("paytm", 5), ("one97 communications", 5),
        ("policybazaar", 5), ("pb fintech", 5),
        ("dmart", 5), ("avenue supermarts", 5),
        ("blinkit", 5), ("zepto", 5), ("instamart", 5),
        # Strong domain terms
        ("gross order value", 3), ("net order value", 3),
        ("gov", 3), ("nov", 3), ("gmv", 3),
        ("quick commerce", 3), ("food delivery", 3),
        ("dark stores", 3), ("hyperpure", 3),
        ("take rate", 3), ("contribution margin", 3),
        ("monthly transacting users", 3), ("mtu", 3),
        ("average order value", 3), ("aov", 3),
        ("platform fee", 3), ("delivery fee", 3),
        # General terms
        ("e-commerce", 1), ("online platform", 1), ("marketplace", 1),
        ("internet retail", 1), ("catalogue retail", 1),
        ("digital platform", 1), ("b2c platform", 1),
    ],
}


class IndustryDetectionEngine:

    @staticmethod
    def run(knowledge_graph: Dict[str, Any], source_text: str = "") -> str:
        print("     [Industry Detector] Running keyword heuristics...")
        text_lower = (source_text or str(knowledge_graph)).lower()

        # Score each sector
        scores: Dict[str, int] = {}
        for sector, kw_list in SECTOR_KEYWORDS.items():
            score = sum(weight for kw, weight in kw_list if kw in text_lower)
            if score > 0:
                scores[sector] = score

        if scores:
            # Sort by score descending; on tie prefer more-specific sector
            best = max(scores, key=lambda s: scores[s])
            top_scores = {s: v for s, v in scores.items() if v == scores[best]}

            # Tiebreak: prefer sector with highest-weight individual match
            if len(top_scores) > 1:
                def max_single_hit(sector: str) -> int:
                    return max(
                        (w for kw, w in SECTOR_KEYWORDS[sector] if kw in text_lower),
                        default=0
                    )
                best = max(top_scores, key=max_single_hit)

            print(f"     [Industry Detector] Detected sector: {best} "
                  f"(score={scores[best]}, all scores: "
                  f"{dict(sorted(scores.items(), key=lambda x: -x[1])[:5])})")
            return best

        # No keyword match — fall back to Mistral Large 3
        print("     [Industry Detector] No keyword match — falling back to Mistral Large 3...")
        import sys, os
        sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
        from pipeline.utils.llm_client import call_bedrock_mistral_large

        allowed = [
            "Banking", "NBFC", "IT Services", "Pharma", "Energy",
            "Infrastructure", "FMCG", "Auto", "Metals", "Cement",
            "Telecom", "Internet & Retail", "Other"
        ]
        prompt = (
            f"Classify this company into exactly one sector from this list:\n"
            f"{', '.join(allowed)}\n\n"
            f"Reply with ONLY the sector name — nothing else.\n\n"
            f"Document excerpt:\n{source_text[:6000]}"
        )
        response = call_bedrock_mistral_large(
            "You are a financial sector classifier. Reply with only the sector name.",
            prompt,
        ).strip().strip('"').strip("'")

        # Clean up JSON wrapper if model returned it
        import re, json
        try:
            parsed = json.loads(response)
            if isinstance(parsed, dict):
                response = next(iter(parsed.values()), response)
        except Exception:
            pass

        # Match to allowed list (case-insensitive)
        response_lower = response.lower()
        detected = "Other"
        for sector in allowed:
            if sector.lower() in response_lower or response_lower in sector.lower():
                detected = sector
                break

        print(f"     [Industry Detector] Mistral detected sector: {detected} (raw: '{response}')")
        return detected
