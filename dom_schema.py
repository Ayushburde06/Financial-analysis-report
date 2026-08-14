"""
dom_schema.py — Pydantic models for the Layout-Aware Document Object Model
Provides hierarchical structuring for Section-Aware RAG.
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Union, Dict, Any
from datetime import datetime

class ConfidenceNode(BaseModel):
    confidence: float = 1.0
    verified: bool = False
    validator: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class DOMNode(ConfidenceNode):
    id: str
    page_num: int
    bounding_box: Optional[List[float]] = None # [x0, y0, x1, y1]

class ParagraphNode(DOMNode):
    type: str = "paragraph"
    text: str
    role: Optional[str] = None # e.g., "title", "sectionHeading", "pageHeader"

class TableNode(DOMNode):
    type: str = "table"
    row_count: int
    column_count: int
    csv_string: str
    dataframe_json: Optional[str] = None

class ChartNode(DOMNode):
    type: str = "chart"
    chart_type: str = "unknown"
    caption: str = ""
    x_axis: str = ""
    y_axis: str = ""
    legend: List[str] = Field(default_factory=list)
    detected_values: Dict[str, Any] = Field(default_factory=dict)
    related_table: Optional[str] = None # ID of a related TableNode
    base64_image: Optional[str] = None

# Using Union so Pydantic knows how to discriminate
DOMNodeType = Union[ParagraphNode, TableNode, ChartNode]

class SubsectionNode(BaseModel):
    """A semantically split topic within a larger Section."""
    topic: str
    nodes: List[DOMNodeType] = Field(default_factory=list)

class SectionNode(BaseModel):
    """A logical section bounded by a heading (e.g., 'MD&A')"""
    heading: str
    level: int = 1 # Heading level (h1, h2, etc)
    nodes: List[DOMNodeType] = Field(default_factory=list)
    subsections: List[SubsectionNode] = Field(default_factory=list)

class MasterDocument(BaseModel):
    """The root container for the parsed layout tree."""
    source_file: str
    # Stable intermediate representation shared by OCR, extraction, and
    # rendering stages. Keys are source page numbers as strings so the object
    # remains JSON-friendly when cached or logged.
    source_format: str = "unknown"
    page_markdown: Dict[str, str] = Field(default_factory=dict)
    source_metadata: Dict[str, Any] = Field(default_factory=dict)
    sections: List[SectionNode] = Field(default_factory=list)
    
    def get_full_text(self) -> str:
        """Helper to get a flat string representation if needed for basic extraction."""
        text = ""
        for sec in self.sections:
            text += f"\n\n# {sec.heading}\n"
            for node in sec.nodes:
                if isinstance(node, ParagraphNode):
                    text += f"{node.text}\n"
                elif isinstance(node, TableNode):
                    text += f"[Table on Page {node.page_num}]\n{node.csv_string}\n"
                elif isinstance(node, ChartNode):
                    text += f"[Chart: {node.chart_type} - {node.caption}]\n"
        return text.strip()

class EvidenceNode(ConfidenceNode):
    """Wrapper for extracted metrics with full lineage traceability."""
    metric: str
    value: Any
    page: int
    section: str
    source: str # e.g. "table_3", "p_12"
    status: str = "ok" # e.g., "ok", "needs_review"
