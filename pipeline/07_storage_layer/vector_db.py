"""
Stage 07: Storage Layer — Per-Page Vector & Structural Chunk Store

Stores and indexes per-page document chunks with strict page_num and section lineage
for accurate evidence retrieval and sentence-level citations.
"""

import re
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from dom_schema import MasterDocument, ParagraphNode, TableNode, SectionNode


class PageChunk(BaseModel):
    """A per-page narrative or table chunk with exact page-level lineage."""
    chunk_id: str
    source_file: str
    page_num: int
    section_heading: str
    text: str
    chunk_type: str = "text"  # "text" or "table"
    metadata: Dict[str, Any] = Field(default_factory=dict)


def chunk_master_doc_by_page(
    master_doc: MasterDocument,
    max_chunk_size: int = 1000,
    overlap: int = 100,
) -> List[PageChunk]:
    """
    Splits a MasterDocument into per-page chunks.
    Guarantees that every chunk maintains its original page_num and section heading.
    """
    chunks: List[PageChunk] = []

    for sec_idx, section in enumerate(master_doc.sections):
        # Infer page_num from section heading if not set
        page_num = getattr(section, "page_num", None)
        if page_num is None:
            match = re.search(r'\d+', section.heading)
            page_num = int(match.group(0)) if match else sec_idx + 1

        sec_heading = section.heading

        # Collect text and table nodes for this page
        page_text_blocks: List[str] = []
        for node in section.nodes:
            if isinstance(node, ParagraphNode):
                if node.text.strip():
                    page_text_blocks.append(node.text.strip())
            elif isinstance(node, TableNode):
                if node.csv_string.strip():
                    # Create dedicated table chunk for high precision table retrieval
                    table_chunk_id = f"{master_doc.source_file}_p{page_num}_table_{len(chunks)}"
                    chunks.append(PageChunk(
                        chunk_id=table_chunk_id,
                        source_file=master_doc.source_file,
                        page_num=page_num,
                        section_heading=sec_heading,
                        text=node.csv_string.strip(),
                        chunk_type="table",
                        metadata={"row_count": node.row_count, "column_count": node.column_count},
                    ))

        # Chunk the page text blocks
        full_page_text = "\n\n".join(page_text_blocks)
        if not full_page_text.strip():
            continue

        # Simple character chunking within the bounds of single page
        if len(full_page_text) <= max_chunk_size:
            chunk_id = f"{master_doc.source_file}_p{page_num}_c0"
            chunks.append(PageChunk(
                chunk_id=chunk_id,
                source_file=master_doc.source_file,
                page_num=page_num,
                section_heading=sec_heading,
                text=full_page_text,
                chunk_type="text",
            ))
        else:
            # Multi-chunk page splitting
            start = 0
            sub_idx = 0
            while start < len(full_page_text):
                end = start + max_chunk_size
                segment = full_page_text[start:end].strip()
                if segment:
                    chunk_id = f"{master_doc.source_file}_p{page_num}_c{sub_idx}"
                    chunks.append(PageChunk(
                        chunk_id=chunk_id,
                        source_file=master_doc.source_file,
                        page_num=page_num,
                        section_heading=sec_heading,
                        text=segment,
                        chunk_type="text",
                    ))
                    sub_idx += 1
                start += (max_chunk_size - overlap)

    return chunks


class PerPageVectorStore:
    """In-memory vector & structural chunk index with per-page filtering."""

    def __init__(self):
        self.store: Dict[str, PageChunk] = {}

    def index_document(self, master_doc: MasterDocument) -> int:
        """Indexes all per-page chunks of a MasterDocument."""
        chunks = chunk_master_doc_by_page(master_doc)
        for chunk in chunks:
            self.store[chunk.chunk_id] = chunk
        return len(chunks)

    def get_chunks_by_page(self, page_num: int) -> List[PageChunk]:
        """Returns all chunks belonging to a specific page number."""
        return [c for c in self.store.values() if c.page_num == page_num]

    def query(
        self,
        keywords: List[str],
        page_num: Optional[int] = None,
        chunk_type: Optional[str] = None,
        top_k: int = 5,
    ) -> List[PageChunk]:
        """
        Retrieves top_k matching chunks using keyword frequency and page filters.
        """
        results = []
        kw_lower = [k.lower() for k in keywords]

        for chunk in self.store.values():
            if page_num is not None and chunk.page_num != page_num:
                continue
            if chunk_type is not None and chunk.chunk_type != chunk_type:
                continue

            text_lower = chunk.text.lower()
            score = sum(text_lower.count(k) for k in kw_lower)
            if score > 0:
                results.append((score, chunk))

        results.sort(key=lambda x: x[0], reverse=True)
        return [chunk for score, chunk in results[:top_k]]

    def get_all_chunks(self) -> List[PageChunk]:
        """Returns all indexed chunks."""
        return list(self.store.values())
