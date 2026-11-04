#!/usr/bin/env python3
"""Test lab report explainer (Part 7b) — flag_rows function.

Tests code-based status comparison without Bedrock.
"""
import json
import sys
from pathlib import Path

# Add agent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.report import flag_rows, TestRow


def test_flag_rows():
    """Test flag_rows() against expected results."""
    
    # Load expected results
    expected_file = Path(__file__).parent.parent / "samples" / "expected_results.json"
    
    if not expected_file.exists():
        print(f"[warning] {expected_file} not found. Creating test data...")
        # Create test data
        test_rows = [
            {"test": "Hemoglobin", "value": 11.5, "unit": "g/dL", "range_text": "12.0 - 15.5"},
            {"test": "Blood Glucose", "value": 180, "unit": "mg/dL", "range_text": "70 - 100"},
            {"test": "Cholesterol", "value": 150, "unit": "mg/dL", "range_text": "< 200"},
            {"test": "Potassium", "value": 4.2, "unit": "mmol/L", "range_text": "3.5 - 5.0"},
            {"test": "Unknown Test", "value": 42, "unit": "units", "range_text": ""},
        ]
        expected_statuses = ["LOW", "HIGH", "NORMAL", "NORMAL", "UNKNOWN - ask doctor"]
    else:
        with open(expected_file) as f:
            expected_data = json.load(f)
        test_rows = expected_data.get("rows", [])
        expected_statuses = [row.get("expect_status") for row in expected_data.get("rows", [])]
    
    # Run flag_rows
    flagged = flag_rows(test_rows)
    
    # Compare
    print("=" * 100)
    print("TEST: flag_rows() — Code-based status comparison")
    print("=" * 100)
    print()
    
    print(f"{'Test':<20} {'Value':<10} {'Range':<20} {'Code Status':<25} {'Expected':<25} {'Match':<5}")
    print("-" * 100)
    
    all_pass = True
    for i, (row, flagged_row) in enumerate(zip(test_rows, flagged)):
        test_name = row.get("test", "")
        value = row.get("value", "")
        range_text = row.get("range_text", "")
        code_status = flagged_row.get("status", "UNKNOWN")
        expected_status = expected_statuses[i] if i < len(expected_statuses) else "?"
        
        match = "PASS" if code_status == expected_status else "FAIL"
        if code_status != expected_status:
            all_pass = False
        
        # Truncate for display
        range_display = range_text[:18] if len(range_text) <= 18 else range_text[:15] + "..."
        
        print(f"{test_name:<20} {str(value):<10} {range_display:<20} {code_status:<25} {expected_status:<25} {match:<5}")
    
    print()
    print("=" * 100)
    
    if all_pass:
        print("ALL TESTS PASSED")
        return 0
    else:
        print("SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(test_flag_rows())
