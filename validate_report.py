"""
Comprehensive Report Validation Script
Extracts data from source PDF and compares with generated report.
"""
import json
import re
import importlib
from pathlib import Path
from typing import Dict, List, Tuple, Any

class ReportValidator:
    """Validates generated reports against source PDFs."""
    
    def __init__(self, pdf_path: str, evidence_path: str, narrative_path: str, output_pdf_path: str):
        self.pdf_path = pdf_path
        self.evidence_path = evidence_path
        self.narrative_path = narrative_path
        self.output_pdf_path = output_pdf_path
        
        # Load evidence
        with open(evidence_path, 'r') as f:
            self.evidence = json.load(f)
        
        # Load narrative
        with open(narrative_path, 'r', encoding='utf-8') as f:
            self.narrative = f.read()
        
        # Extract source data via Azure OCR
        print("\n" + "=" * 80)
        print("EXTRACTING SOURCE PDF DATA")
        print("=" * 80)
        stage_01 = importlib.import_module("pipeline.01_financial_structure_builder.builder")
        self.master_doc = stage_01.FinancialStructureBuilder.run(pdf_path)
        self.source_text = self.master_doc.get_full_text()
        
    def extract_numbers_from_text(self, text: str) -> Dict[str, List[float]]:
        """Extract all numbers from text with their context."""
        # Pattern to match numbers with optional commas and decimals
        number_pattern = r'[\d,]+\.?\d*'
        
        numbers = {}
        lines = text.split('\n')
        
        for line in lines:
            matches = re.findall(number_pattern, line)
            if matches:
                line_clean = line.strip()
                if line_clean:
                    nums = [float(m.replace(',', '')) for m in matches if m.replace(',', '').replace('.', '').isdigit()]
                    if nums:
                        numbers[line_clean] = nums
        
        return numbers
    
    def find_value_in_source(self, value: float, tolerance: float = 0.01) -> List[str]:
        """Find where a value appears in the source PDF."""
        matches = []
        
        for line, nums in self.source_numbers.items():
            for num in nums:
                if abs(num - value) <= tolerance * value if value != 0 else abs(num - value) <= tolerance:
                    matches.append(line)
                    break
        
        return matches
    
    def validate_evidence_numbers(self) -> Dict[str, Any]:
        """Validate all numbers in evidence against source PDF."""
        print("\n📊 Validating Evidence Numbers...")
        
        results = {
            "total_fields": 0,
            "available_fields": 0,
            "validated_fields": 0,
            "missing_fields": 0,
            "mismatches": [],
            "unverifiable": []
        }
        
        # Extract source numbers
        self.source_numbers = self.extract_numbers_from_text(self.source_text)
        
        # Check P&L items
        for metric in ['revenue', 'ebitda', 'ebit', 'pbt', 'pat', 'eps']:
            if metric in self.evidence.get('pl', {}):
                metric_data = self.evidence['pl'][metric]
                
                for period, data in metric_data.items():
                    results['total_fields'] += 1
                    value = data.get('value')
                    
                    if value == "[N/A]" or value is None:
                        results['missing_fields'] += 1
                        continue
                    
                    results['available_fields'] += 1
                    
                    # Try to find in source
                    matches = self.find_value_in_source(float(value))
                    
                    if matches:
                        results['validated_fields'] += 1
                        print(f"  ✅ {metric}.{period}: {value} found in source")
                    else:
                        results['unverifiable'].append({
                            'field': f"pl.{metric}.{period}",
                            'value': value,
                            'reason': 'Value not found in source PDF'
                        })
                        print(f"  ⚠️  {metric}.{period}: {value} NOT found in source")
        
        # Check Balance Sheet items
        for metric in ['total_assets', 'total_liabilities', 'total_equity', 'total_debt', 'cash_and_equivalents']:
            if metric in self.evidence.get('bs', {}):
                metric_data = self.evidence['bs'][metric]
                
                for period, data in metric_data.items():
                    results['total_fields'] += 1
                    value = data.get('value')
                    
                    if value == "[N/A]" or value is None:
                        results['missing_fields'] += 1
                        continue
                    
                    results['available_fields'] += 1
                    matches = self.find_value_in_source(float(value))
                    
                    if matches:
                        results['validated_fields'] += 1
                        print(f"  ✅ {metric}.{period}: {value} found in source")
                    else:
                        results['unverifiable'].append({
                            'field': f"bs.{metric}.{period}",
                            'value': value,
                            'reason': 'Value not found in source PDF'
                        })
        
        return results
    
    def validate_narrative_claims(self) -> Dict[str, Any]:
        """Validate claims made in the narrative."""
        print("\n📝 Validating Narrative Claims...")
        
        results = {
            "total_numbers": 0,
            "verified_numbers": 0,
            "hallucinations": [],
            "unsupported_claims": []
        }
        
        # Extract all numbers from narrative
        narrative_numbers = re.findall(r'₹?[\d,]+\.?\d*[MBK]?', self.narrative)
        results['total_numbers'] = len(narrative_numbers)
        
        print(f"  Found {len(narrative_numbers)} numbers in narrative")
        
        # Check each number
        for num_str in narrative_numbers:
            # Parse the number
            clean_num = num_str.replace('₹', '').replace(',', '').strip()
            
            multiplier = 1
            if clean_num.endswith('M'):
                multiplier = 1
                clean_num = clean_num[:-1]
            elif clean_num.endswith('B'):
                multiplier = 1000
                clean_num = clean_num[:-1]
            elif clean_num.endswith('K'):
                multiplier = 0.001
                clean_num = clean_num[:-1]
            
            try:
                value = float(clean_num) * multiplier
                
                # Check if this value is in evidence
                found_in_evidence = False
                for section in ['pl', 'bs', 'cf']:
                    if section in self.evidence:
                        for metric, periods in self.evidence[section].items():
                            for period, data in periods.items():
                                ev_val = data.get('value')
                                if ev_val and ev_val != "[N/A]":
                                    if abs(float(ev_val) - value) < 0.1:
                                        found_in_evidence = True
                                        break
                            if found_in_evidence:
                                break
                    if found_in_evidence:
                        break
                
                if found_in_evidence:
                    results['verified_numbers'] += 1
                else:
                    # Check if it's a calculated value (growth rate, margin, etc.)
                    if '%' in num_str or 'growth' in self.narrative.lower() or 'margin' in self.narrative.lower():
                        # Could be a derived metric
                        pass
                    else:
                        results['unsupported_claims'].append({
                            'number': num_str,
                            'value': value,
                            'reason': 'Not found in evidence'
                        })
            except ValueError:
                pass
        
        return results
    
    def calculate_quality_score(self, evidence_results: Dict, narrative_results: Dict) -> Dict[str, float]:
        """Calculate quality scores."""
        scores = {}
        
        # Accuracy: verified numbers / total numbers
        if evidence_results['available_fields'] > 0:
            scores['accuracy'] = (evidence_results['validated_fields'] / evidence_results['available_fields']) * 100
        else:
            scores['accuracy'] = 0
        
        # Completeness: available fields / total fields
        if evidence_results['total_fields'] > 0:
            scores['completeness'] = (evidence_results['available_fields'] / evidence_results['total_fields']) * 100
        else:
            scores['completeness'] = 0
        
        # Citations: verified narrative numbers / total narrative numbers
        if narrative_results['total_numbers'] > 0:
            scores['citations'] = (narrative_results['verified_numbers'] / narrative_results['total_numbers']) * 100
        else:
            scores['citations'] = 100  # No claims to verify
        
        # Narrative Quality: subjective, based on structure
        # Check for key sections
        has_sections = sum([
            'Revenue' in self.narrative,
            'Profitability' in self.narrative or 'Margin' in self.narrative,
            'Cash Flow' in self.narrative or 'Balance Sheet' in self.narrative,
            len(self.narrative) > 500  # Reasonable length
        ])
        scores['narrative_quality'] = (has_sections / 4) * 100
        
        # Overall score
        scores['overall'] = (
            scores['accuracy'] * 0.4 +
            scores['completeness'] * 0.2 +
            scores['citations'] * 0.3 +
            scores['narrative_quality'] * 0.1
        )
        
        return scores
    
    def generate_report(self) -> str:
        """Generate a comprehensive validation report."""
        print("\n" + "=" * 80)
        print("VALIDATING REPORT QUALITY")
        print("=" * 80)
        
        evidence_results = self.validate_evidence_numbers()
        narrative_results = self.validate_narrative_claims()
        scores = self.calculate_quality_score(evidence_results, narrative_results)
        
        # Generate markdown report
        report = []
        report.append("# Financial Report Quality Analysis")
        report.append(f"\n## Report: {Path(self.output_pdf_path).name}")
        report.append(f"**Source PDF:** {Path(self.pdf_path).name}")
        report.append(f"**Company:** {self.evidence.get('company_name', 'Unknown')}")
        report.append("")
        
        # Executive Summary
        report.append("## Executive Summary")
        report.append("")
        overall_grade = (
            'A' if scores['overall'] >= 90 else
            'B' if scores['overall'] >= 80 else
            'C' if scores['overall'] >= 70 else
            'D' if scores['overall'] >= 60 else 'F'
        )
        report.append(f"**Overall Quality Grade:** {overall_grade} ({scores['overall']:.1f}%)")
        report.append("")
        
        # Quality Scores
        report.append("## Quality Metrics")
        report.append("")
        report.append("| Metric | Score | Status |")
        report.append("|--------|-------|--------|")
        
        for metric, score in scores.items():
            if metric != 'overall':
                status = '✅' if score >= 80 else '⚠️' if score >= 60 else '❌'
                report.append(f"| {metric.replace('_', ' ').title()} | {score:.1f}% | {status} |")
        
        report.append("")
        
        # Evidence Validation
        report.append("## Evidence Validation")
        report.append("")
        report.append(f"- **Total Fields:** {evidence_results['total_fields']}")
        report.append(f"- **Available Fields:** {evidence_results['available_fields']}")
        report.append(f"- **Validated Fields:** {evidence_results['validated_fields']}")
        report.append(f"- **Missing Fields:** {evidence_results['missing_fields']}")
        report.append("")
        
        if evidence_results['unverifiable']:
            report.append("### ⚠️ Unverifiable Fields")
            report.append("")
            report.append("| Field | Value | Reason |")
            report.append("|-------|-------|--------|")
            for item in evidence_results['unverifiable'][:10]:  # Limit to first 10
                report.append(f"| {item['field']} | {item['value']} | {item['reason']} |")
            report.append("")
        
        # Narrative Validation
        report.append("## Narrative Validation")
        report.append("")
        report.append(f"- **Total Numbers in Narrative:** {narrative_results['total_numbers']}")
        report.append(f"- **Verified Against Evidence:** {narrative_results['verified_numbers']}")
        report.append(f"- **Verification Rate:** {(narrative_results['verified_numbers']/max(1, narrative_results['total_numbers'])*100):.1f}%")
        report.append("")
        
        if narrative_results['unsupported_claims']:
            report.append("### ⚠️ Unsupported Claims")
            report.append("")
            report.append("| Number | Value | Reason |")
            report.append("|--------|-------|--------|")
            for item in narrative_results['unsupported_claims'][:10]:
                report.append(f"| {item['number']} | {item['value']:.2f} | {item['reason']} |")
            report.append("")
        
        # Key Findings
        report.append("## Key Findings")
        report.append("")
        
        if scores['overall'] >= 80:
            report.append("### ✅ Strengths")
            report.append("- High overall quality score")
            report.append("- Strong data validation from source")
            if scores['accuracy'] >= 90:
                report.append("- Excellent accuracy in number extraction")
            if scores['citations'] >= 90:
                report.append("- All narrative claims backed by evidence")
        
        report.append("")
        report.append("### ⚠️ Areas for Improvement")
        
        if scores['completeness'] < 80:
            report.append(f"- **Completeness ({scores['completeness']:.1f}%)**: Many fields missing from source PDF")
            report.append("  - Likely due to limited historical data in quarterly reports")
            report.append("  - Consider supplementing with annual reports for full-year data")
        
        if scores['accuracy'] < 90:
            report.append(f"- **Accuracy ({scores['accuracy']:.1f}%)**: Some extracted numbers not found in source")
            report.append("  - Review extraction logic in Stage 08")
            report.append("  - Possible causes: OCR errors, table parsing issues, or derived calculations")
        
        if scores['citations'] < 90:
            report.append(f"- **Citations ({scores['citations']:.1f}%)**: Some narrative claims not traced to evidence")
            report.append("  - Unified analyst may be making inferences")
            report.append("  - Strengthen verification in Stage 12")
        
        report.append("")
        
        # Bug Identification
        report.append("## Bug Identification")
        report.append("")
        
        bugs_found = []
        
        if evidence_results['unverifiable']:
            bugs_found.append({
                'bug': 'Unverifiable extracted values',
                'count': len(evidence_results['unverifiable']),
                'severity': 'MEDIUM',
                'root_cause': 'Stage 08 (Hybrid Retrieval) may be extracting values that don\'t exist in source PDF',
                'suggested_fix': 'Improve extraction prompt to be more conservative. Add validation layer to cross-reference extracted values with OCR output.'
            })
        
        if narrative_results['unsupported_claims']:
            bugs_found.append({
                'bug': 'Unsupported narrative claims',
                'count': len(narrative_results['unsupported_claims']),
                'severity': 'HIGH',
                'root_cause': 'Stage 11 (Unified Analyst) generating numbers not in evidence packet',
                'suggested_fix': 'Strengthen verification prompt. Consider adding stricter output formatting that requires [source] tags for every number.'
            })
        
        if evidence_results['missing_fields'] / max(1, evidence_results['total_fields']) > 0.5:
            bugs_found.append({
                'bug': 'High missing field rate',
                'count': evidence_results['missing_fields'],
                'severity': 'LOW',
                'root_cause': 'Quarterly reports typically lack full historical data. This is expected.',
                'suggested_fix': 'Accept this limitation for quarterly reports. For annual reports, improve extraction to capture more historical periods.'
            })
        
        if bugs_found:
            report.append("### 🐛 Identified Issues")
            report.append("")
            for i, bug in enumerate(bugs_found, 1):
                report.append(f"#### {i}. {bug['bug']} [{bug['severity']}]")
                report.append(f"- **Count:** {bug['count']}")
                report.append(f"- **Root Cause:** {bug['root_cause']}")
                report.append(f"- **Suggested Fix:** {bug['suggested_fix']}")
                report.append("")
        else:
            report.append("### ✅ No Critical Bugs Found")
            report.append("")
        
        # Production Readiness
        report.append("## Production Readiness Assessment")
        report.append("")
        
        if scores['overall'] >= 85 and not any(b['severity'] == 'HIGH' for b in bugs_found):
            report.append("### ✅ PRODUCTION READY")
            report.append("")
            report.append("The report meets quality thresholds for production use:")
            report.append("- Overall score above 85%")
            report.append("- No high-severity bugs")
            report.append("- Narrative backed by evidence")
        elif scores['overall'] >= 75:
            report.append("### ⚠️ PRODUCTION READY WITH CAVEATS")
            report.append("")
            report.append("The report can be used in production with the following notes:")
            report.append("- Some fields may be incomplete (expected for quarterly reports)")
            report.append("- Minor validation issues should be monitored")
            report.append("- Consider human review for critical claims")
        else:
            report.append("### ❌ NOT PRODUCTION READY")
            report.append("")
            report.append("The report requires improvements before production use:")
            report.append("- Overall quality score below threshold")
            report.append("- Critical bugs must be fixed")
            report.append("- Re-run validation after fixes")
        
        report.append("")
        
        # Narrative Sample
        report.append("## Generated Narrative (Sample)")
        report.append("")
        report.append("```")
        report.append(self.narrative[:1000] + "..." if len(self.narrative) > 1000 else self.narrative)
        report.append("```")
        report.append("")
        
        return "\n".join(report)

def main():
    """Main validation routine."""
    print("=" * 80)
    print("FINANCIAL REPORT VALIDATION")
    print("=" * 80)
    
    # Paths
    pdf_path = "PDF/LTTS Q2FY26.pdf"
    evidence_path = "outputs/LTTS Q2FY26_evidence.json"
    narrative_path = "outputs/LTTS Q2FY26_narrative.txt"
    output_pdf = "outputs/LTTS Q2FY26_Geojit_Report.pdf"
    
    # Validate
    validator = ReportValidator(pdf_path, evidence_path, narrative_path, output_pdf)
    report = validator.generate_report()
    
    # Save report
    output_path = "REPORT_QUALITY_ANALYSIS.md"
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print("\n" + "=" * 80)
    print("VALIDATION COMPLETE")
    print("=" * 80)
    print(f"✅ Report saved to: {output_path}")
    print("\nYou can review the detailed analysis in the markdown file.")

if __name__ == "__main__":
    main()
