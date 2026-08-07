"""Authoritative company-source registry for research provenance."""

OFFICIAL_SOURCE_REGISTRY = {
    "icici": {
        "company_match": ("icici",),
        "source_type": "Investor relations / quarterly results",
        "url": "https://www.icicibank.com/about-us/invest-relations",
        "period": "Q2 FY26",
    },
    "jsw_energy": {
        "company_match": ("jsw energy", "jswenergy"),
        "source_type": "Official Q2 FY26 results presentation",
        "url": "https://www.jswenergy.in/wp-content/uploads/2026/01/JSWEL_Results-Presentation_Q2FY26-compressed.pdf",
        "period": "Q2 FY26",
    },
    "ltts": {
        "company_match": ("ltts", "l&t technology", "l and t technology"),
        "source_type": "Official Q2 FY26 investor presentation",
        "url": "https://www.ltts.com/system/files/2025-10/LTTS-Q2FY26-Investor-Presentation.pdf",
        "period": "Q2 FY26",
    },
    "pocl": {
        "company_match": ("pocl", "pondy oxides"),
        "source_type": "Official investor presentation / financial reports",
        "url": "https://pocl.co.in/investor-presentation/",
        "period": "Q2 FY26",
    },
}


def official_sources_for(company_name: str):
    name = (company_name or "").lower()
    return [
        {
            "source_type": item["source_type"],
            "url": item["url"],
            "period": item["period"],
            "status": "official source registered; numeric cross-check pending retrieval",
        }
        for item in OFFICIAL_SOURCE_REGISTRY.values()
        if any(token in name for token in item["company_match"])
    ]
