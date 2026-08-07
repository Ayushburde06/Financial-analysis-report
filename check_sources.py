"""Check source PDFs for missing financial keywords."""
import fitz

sources = {
    'ICICI': 'PDF/ICICI Q2FY26.pdf',
    'LTTS': 'PDF/LTTS Q2FY26.pdf',
    'POCL': 'PDF/POCL Q2FY26.pdf',
    'JSW Energy': 'PDF/JSW Energy Q2FY26.pdf',
}

keywords = [
    'face value', 'par value',
    'shareholding', 'promoter', 'FII', 'DII', 'mutual fund',
    'total assets', 'total equity', 'net worth', 'shareholders fund',
    'total debt', 'borrowings', 'total liabilities',
    'CASA', 'capital adequacy', 'CAR',
    'book value', 'book per share',
    'free float',
    'enterprise value',
    'outstanding shares', 'paid-up',
]

for name, path in sources.items():
    doc = fitz.open(path)
    full_text = '\n'.join(doc[i].get_text() for i in range(doc.page_count))
    doc.close()
    text_lower = full_text.lower()
    print(f'\n===== {name} ({len(full_text)} chars) =====')
    for kw in keywords:
        found = kw.lower() in text_lower
        if found:
            idx = text_lower.find(kw.lower())
            ctx = full_text[max(0, idx-20):idx+60].replace('\n', ' ')
            print(f'  [FOUND] {kw}: ...{ctx.strip()}...')
        else:
            print(f'  [MISS]  {kw}')
