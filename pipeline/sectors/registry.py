"""
registry.py — Auto-discovery registry for SectorConfig subclasses.

To add a new sector:
  1. Create pipeline/sectors/your_sector.py with a class inheriting SectorConfig
  2. Import it here and add an instance to _REGISTRY (before GenericConfig)
  3. That's it — retriever, evidence builder, ROM builder all pick it up automatically.
"""
from .base import SectorConfig

# ── Import all sector configs ──────────────────────────────────────────────────
from .banking         import BankingConfig
from .nbfc            import NBFCConfig
from .it_services     import ITServicesConfig
from .energy          import EnergyConfig
from .pharma          import PharmaConfig
from .infrastructure  import InfrastructureConfig
from .fmcg            import FMCGConfig
from .auto            import AutoConfig
from .metals          import MetalsConfig
from .cement          import CementConfig
from .telecom         import TelecomConfig
from .internet_retail import InternetRetailConfig
from .generic         import GenericConfig   # MUST be last

# ── Registry — order matters: more-specific sectors first ─────────────────────
# Sectors with overlapping keywords are ordered most-specific → least-specific.
# Banking before NBFC (NBFCs also have NII), Pharma before Generic, etc.
_REGISTRY: list = [
    BankingConfig(),
    NBFCConfig(),
    ITServicesConfig(),
    EnergyConfig(),
    PharmaConfig(),
    InfrastructureConfig(),
    FMCGConfig(),
    AutoConfig(),
    MetalsConfig(),
    CementConfig(),
    TelecomConfig(),
    InternetRetailConfig(),
    GenericConfig(),     # catches everything else — always last
]


def get_sector_config(detected_sector: str) -> SectorConfig:
    """
    Return the first matching SectorConfig for the detected sector string.
    Falls back to GenericConfig if nothing matches.
    """
    for cfg in _REGISTRY:
        if cfg.is_match(detected_sector):
            return cfg
    return GenericConfig()


def list_sectors() -> list:
    return [cfg.sector_name for cfg in _REGISTRY]
