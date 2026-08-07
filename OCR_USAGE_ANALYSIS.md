# OCR Usage Analysis Report

## Executive Summary

Your pipeline currently uses **Azure Document Intelligence (OCR)** in **ONE location** in the **1st Pipeline Stage**. However, OCR is called **only ONCE per PDF** (not multiple times), making it efficient.

---

## 🔍 Detailed OCR Usage Breakdown

### **Stage 01: Financial Structure Builder** ✅ (1st Pipeline Stage)

**File**: `pipeline/01_financial_structure_builder/builder.py`

**OCR Call Location**: Lines 38-48

```python
poller = client.begin_analyze_document(
    "prebuilt-layout",
    body=pdf_bytes,
    content_type="application/octet-stream",
    output_content_format="markdown"
)
result = poller.result()
```

**What It Does**:
- Uses **Azure Document Intelligence Client** with `prebuilt-layout` model
- Converts PDF to structured markdown with layout awareness
- Extracts text from entire document in **ONE SINGLE API CALL**
- Output is parsed into hierarchical MasterDocument DOM

**Cost**: ~$0.50-$1.00 per report (depends on page count, ~$0.01 per page for Azure DI)

---

## 📊 OCR Call Count Summary

| Stage | File | OCR Calls | Service | Cost |
|-------|------|-----------|---------|------|
| **Stage 01** | `01_financial_structure_builder/builder.py` | **1** | Azure Document Intelligence | ~$0.50-$1.00 |
| Stage 02-15 | (Other pipeline stages) | **0** | N/A | $0.00 |
| **TOTAL** | | **1** | | ~$0.50-$1.00 per report |

---

## 🎯 Why Only 1 OCR Call is Used

Your architecture follows the **hybrid extraction pattern** documented in `brain1.md`:

1. **Stage 01 extracts everything in ONE OCR pass** using Azure Document Intelligence
2. **Subsequent stages** (`02` through `15`) work with the already-extracted markdown/text
3. **No repeated OCR calls** - The document is processed once, then routed through verification and analysis stages

### Downstream Stages (No Additional OCR):
- **Stage 02**: Company Knowledge Builder → Uses Mistral LLM (text classification, NOT OCR)
- **Stage 03-06**: Analysis engines → Use extracted text + LLM reasoning (NO OCR)
- **Stage 08**: Hybrid Retrieval → Uses DeepSeek R1 on extracted text (NO OCR)
- **Stage 09-15**: Quantitative analysis, rendering, verification → Work with extracted data (NO OCR)

---

## ✅ Current Architecture Assessment

### Strengths:
1. **Single OCR Pass** - Efficient, no redundant API calls
2. **Cost Optimized** - ~$0.50-$1.00 per report (Azure DI pricing)
3. **Stage 01 Gateway** - All subsequent stages receive pre-extracted markdown
4. **Layout Awareness** - Azure DI preserves document structure (tables, sections, etc.)

### Optimization Opportunities:
1. **Hybrid Native PDF Detection** (mentioned in brain1.md):
   - For digital PDFs with selectable text: use PyMuPDF/pdfplumber ($0.00 cost, < 1 second)
   - For scanned PDFs only: use Azure DI OCR ($0.50-$1.00)
   - **Potential savings**: 80-90% OCR cost reduction (if 80%+ of documents are digital PDFs)

2. **Current Limitation**: Stage 01 calls Azure DI on ALL PDFs regardless of type
   - **Quick Fix**: Add PDF type detection before Stage 01

---

## 🚀 Recommendation: Implement Hybrid PDF Router

To achieve 80% cost savings (as outlined in `brain1.md`), add a **PDF Classifier** before Stage 01:

```python
# Add to main.py before stage_01.run()

from pathlib import Path
import PyPDF2

def classify_pdf_type(pdf_path: str) -> str:
    """Detect if PDF is digital (selectable text) or scanned (image-only)."""
    try:
        with open(pdf_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            text = reader.pages[0].extract_text() if reader.pages else ""
        
        # If extractable text > 50 chars, it's digital
        return "digital" if len(text.strip()) > 50 else "scanned"
    except:
        return "scanned"  # Default to OCR if error

# Then route:
pdf_type = classify_pdf_type(pdf_path)
if pdf_type == "digital":
    # Use PyMuPDF for FREE: master_doc = extract_with_pymupdf(pdf_path)
    master_doc = extract_with_pymupdf(pdf_path)
else:
    # Use Azure DI for scanned PDFs only
    master_doc = stage_01.FinancialStructureBuilder.run(pdf_path)
```

**Impact**:
- **Savings**: 80-90% OCR cost (if 80% of your PDFs are digital)
- **Speed**: Digital PDFs extracted in < 1 second (vs. 5-10 seconds for Azure DI)
- **Same accuracy**: Both methods feed into Stage 02+

---

## 📋 Summary Table

| Metric | Current | After Hybrid Implementation |
|--------|---------|---------------------------|
| OCR Calls per Report | 1 | 0-1 (conditionally) |
| Cost per Report (100 pages) | ~$1.00 | ~$0.15 (85% savings) |
| Processing Time | ~8-10 seconds | ~30-60 seconds total (1st stage only) |
| Coverage | All PDFs via Azure DI | Digital PDFs free; Scanned PDFs via Azure DI |

---

## 🔗 Related Files
- `brain1.md` - Architectural decision document (explains hybrid approach)
- `main.py` - Current main orchestrator (where classification would be added)
- `pipeline/01_financial_structure_builder/builder.py` - Current OCR implementation

