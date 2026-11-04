#!/usr/bin/env python3
"""Test lab report explainer CLI (Part 7b) — Simulate report processing.

Tests the report processing pipeline without needing Bedrock credentials.
Simulates Nova's extraction and verifies flag_rows results.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.report import flag_rows, TestRow, get_explanation_for_row, get_doctor_questions


def test_report_pipeline():
    """Test the complete report processing pipeline."""
    
    # Simulated reports with known extracted data
    reports = [
        {
            "name": "Sample Report 1: Normal Tests",
            "filename": "sample_report_1_normal.png",
            "extracted_rows": [
                {"test": "Hemoglobin", "value": 13.2, "unit": "g/dL", "range_text": "12.0 - 15.5"},
                {"test": "Blood Glucose (Fasting)", "value": 95, "unit": "mg/dL", "range_text": "70 - 100"},
                {"test": "Total Cholesterol", "value": 180, "unit": "mg/dL", "range_text": "< 200"},
                {"test": "TSH", "value": 2.2, "unit": "mIU/L", "range_text": "0.4 - 4.0"},
                {"test": "Creatinine", "value": 0.9, "unit": "mg/dL", "range_text": "0.6 - 1.2"},
            ],
            "expected_statuses": {
                "Hemoglobin": "NORMAL",
                "Blood Glucose (Fasting)": "NORMAL",
                "Total Cholesterol": "NORMAL",
                "TSH": "NORMAL",
                "Creatinine": "NORMAL",
            }
        },
        {
            "name": "Sample Report 2: Abnormal Values",
            "filename": "sample_report_2_abnormal.png",
            "extracted_rows": [
                {"test": "Hemoglobin", "value": 11.2, "unit": "g/dL", "range_text": "12.0 - 15.5"},
                {"test": "Blood Glucose (Fasting)", "value": 168, "unit": "mg/dL", "range_text": "70 - 100"},
                {"test": "Total Cholesterol", "value": 240, "unit": "mg/dL", "range_text": "< 200"},
                {"test": "HDL Cholesterol", "value": 35, "unit": "mg/dL", "range_text": "> 40"},
                {"test": "TSH", "value": 5.2, "unit": "mIU/L", "range_text": "0.4 - 4.0"},
            ],
            "expected_statuses": {
                "Hemoglobin": "LOW",
                "Blood Glucose (Fasting)": "HIGH",
                "Total Cholesterol": "HIGH",
                "HDL Cholesterol": "LOW",
                "TSH": "HIGH",
            }
        },
        {
            "name": "Sample Report 3: Partial Ranges (Fallback)",
            "filename": "sample_report_3_partial_ranges.png",
            "extracted_rows": [
                {"test": "Hemoglobin", "value": 12.5, "unit": "g/dL", "range_text": "12.0 - 15.5"},
                {"test": "Blood Glucose (Random)", "value": 145, "unit": "mg/dL", "range_text": ""},
                {"test": "Vitamin B12", "value": 250, "unit": "pg/mL", "range_text": ""},
                {"test": "Vitamin D", "value": 45, "unit": "ng/mL", "range_text": "30 - 100"},
                {"test": "Iron", "value": 85, "unit": "mcg/dL", "range_text": ""},
            ],
            "expected_statuses": {
                "Hemoglobin": "NORMAL",
                "Blood Glucose (Random)": "HIGH",  # Uses fallback 70-140
                "Vitamin B12": "NORMAL",  # Uses fallback
                "Vitamin D": "NORMAL",
                "Iron": "UNKNOWN - ask doctor",  # Not in fallback
            }
        }
    ]
    
    print("=" * 120)
    print("TEST: Lab Report Explainer Pipeline")
    print("=" * 120)
    print()
    
    all_pass = True
    
    for report in reports:
        print(f"Report: {report['name']}")
        print(f"Filename: {report['filename']}")
        print()
        
        # Run flag_rows
        flagged = flag_rows(report["extracted_rows"])
        
        # Check results
        print(f"{'Test':<30} {'Value':<10} {'Status (Code)':<20} {'Expected':<20} {'Match':<5}")
        print("-" * 120)
        
        for flagged_row in flagged:
            test_name = flagged_row["test"]
            value = flagged_row["value"]
            code_status = flagged_row.get("status", "UNKNOWN")
            expected_status = report["expected_statuses"].get(test_name, "?")
            
            match = "PASS" if code_status == expected_status else "FAIL"
            if code_status != expected_status:
                all_pass = False
            
            range_source = flagged_row.get("range_source", "")
            range_note = f" ({range_source})" if range_source else ""
            
            print(f"{test_name:<30} {str(value):<10} {code_status + range_note:<20} {expected_status:<20} {match:<5}")
        
        print()
        print("EXPLANATIONS & DOCTOR QUESTIONS:")
        print()
        
        # Show first 2 tests (explanations)
        for flagged_row in flagged[:2]:
            test_name = flagged_row["test"]
            value = flagged_row["value"]
            status = flagged_row.get("status", "UNKNOWN")
            unit = flagged_row["unit"]
            
            explan = get_explanation_for_row(test_name, value, status, unit)
            
            print(f"{test_name}:")
            print(f"  {explan['en']}")
        
        print()
        print("Questions to ask doctor:")
        questions = get_doctor_questions(flagged)
        for i, q in enumerate(questions[:3], 1):
            if isinstance(q, dict):
                print(f"  {i}. {q.get('en', q.get('ta', ''))}")
            else:
                print(f"  {i}. {q}")
        
        print()
        print("Disclaimer:")
        print("  This is only an explanation, not a diagnosis. Please show this report to your doctor.")
        print()
        print("=" * 120)
        print()
    
    if all_pass:
        print("ALL REPORT TESTS PASSED")
        return 0
    else:
        print("SOME REPORT TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(test_report_pipeline())
