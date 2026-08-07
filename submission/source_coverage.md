# Source Coverage Matrix

The Eternal/Geojit sample defines the report layout. The uploaded company source determines which fields can be populated. Unsupported fields are marked unavailable rather than copied from the sample or fabricated.

| Source | Company/sector | Quarterly results | Annual statements | Balance sheet | Cash flow | Charts | Market data | Recommendation history |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| ICICI Q2FY26.pdf | ICICI Bank / Banking | Available | FY25 plus model estimates | Available fields only | Available fields only | Revenue, PAT, margin and quarterly comparison | Live market enrichment | Not available |
| JSW Energy Q2FY26.pdf | JSW Energy / Energy | Available | Limited in source | Available fields only | Available fields only | Revenue, PAT and quarterly comparison | Live market enrichment | Not available |
| LTTS Q2FY26.pdf | L&T Technology Services / IT Services | Available | Limited in source | Available fields only | Available fields only | Revenue, PAT/EPS and quarterly comparison | Live market enrichment | Not available |
| POCL Q2FY26.pdf | POCL / Metals | Available | FY22-FY25 plus model estimates | Available fields only | Available fields only | Revenue, PAT, margin and quarterly comparison | Live market enrichment | One shareholding quarter only |

## Provenance rules

- **Source fact:** extracted from the uploaded document and verified against OCR evidence.
- **Calculated:** derived deterministically from verified source values.
- **AI narrative:** qualitative synthesis based on the verified evidence packet.
- **AI estimate (`E`):** forward projection, never presented as historical fact or company guidance.
- **Not available in source:** omitted, collapsed or explicitly labelled instead of invented.

## Quality gates

1. Page-level OCR preserves source-page boundaries.
2. Structured financial values are source fact-checked before report assembly.
3. Unit normalization is followed by a second source verification.
4. HTML is checked before Chromium for required sections, tables, charts and placeholders.
5. The final PDF is reopened and checked for page count, text, images, empty pages and invalid tokens.

## Latest validation results

| Report | Source values verified | Charts | HTML/PDF QA | Result |
|---|---:|---:|---|---|
| ICICI Q2FY26 | 56/56 (100%) | 4 | Passed | HOLD |
| JSW Energy Q2FY26 | 18/18 (100%) | 3 | Passed | NOT RATED |
| LTTS Q2FY26 | 35/35 (100%) | 3 | Passed | NOT RATED |
| POCL Q2FY26 | 37/37 (100%) | 4 | Passed | NOT RATED |
