#!/usr/bin/env python3
"""Create sample lab report images for testing.

Uses PIL to create simple PNG images with lab test data.
This allows testing read_report_via_nova without needing real scanned reports.
"""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path


def create_sample_report_1():
    """Create sample report 1: Normal tests with ranges."""
    img = Image.new('RGB', (800, 600), color='white')
    draw = ImageDraw.Draw(img)
    
    # Try to use default font; fall back to basic if not available
    try:
        title_font = ImageFont.truetype("arial.ttf", 24)
        text_font = ImageFont.truetype("arial.ttf", 16)
    except:
        title_font = ImageFont.load_default()
        text_font = ImageFont.load_default()
    
    y = 20
    draw.text((20, y), "BLOOD TEST REPORT", fill='black', font=title_font)
    y += 40
    
    draw.text((20, y), "Date: 2026-11-04", fill='black')
    y += 30
    
    # Test results with ranges
    tests = [
        ("Hemoglobin", "13.2", "g/dL", "12.0 - 15.5"),
        ("Blood Glucose (Fasting)", "95", "mg/dL", "70 - 100"),
        ("Total Cholesterol", "180", "mg/dL", "< 200"),
        ("HDL Cholesterol", "50", "mg/dL", "> 40"),
        ("LDL Cholesterol", "110", "mg/dL", "< 130"),
        ("Triglycerides", "120", "mg/dL", "< 150"),
        ("TSH", "2.2", "mIU/L", "0.4 - 4.0"),
        ("Creatinine", "0.9", "mg/dL", "0.6 - 1.2"),
        ("Sodium", "138", "mmol/L", "135 - 145"),
        ("Potassium", "4.0", "mmol/L", "3.5 - 5.0"),
    ]
    
    draw.text((20, y), "Test Results:", fill='black', font=text_font)
    y += 25
    
    for test_name, value, unit, range_text in tests:
        line = f"{test_name:.<40} {value:>8} {unit:.<15} Range: {range_text}"
        draw.text((20, y), line, fill='black')
        y += 20
    
    y += 10
    draw.text((20, y), "Note: All values within normal range", fill='green')
    
    filepath = Path(__file__).parent / "sample_report_1_normal.png"
    img.save(filepath)
    print(f"Created {filepath}")


def create_sample_report_2():
    """Create sample report 2: Abnormal values (high glucose, low hemoglobin)."""
    img = Image.new('RGB', (800, 600), color='white')
    draw = ImageDraw.Draw(img)
    
    try:
        title_font = ImageFont.truetype("arial.ttf", 24)
        text_font = ImageFont.truetype("arial.ttf", 16)
    except:
        title_font = ImageFont.load_default()
        text_font = ImageFont.load_default()
    
    y = 20
    draw.text((20, y), "BLOOD TEST REPORT", fill='black', font=title_font)
    y += 40
    
    draw.text((20, y), "Date: 2026-11-04", fill='black')
    y += 30
    
    # Test results with abnormal values
    tests = [
        ("Hemoglobin", "11.2", "g/dL", "12.0 - 15.5", "LOW"),
        ("Blood Glucose (Fasting)", "168", "mg/dL", "70 - 100", "HIGH"),
        ("Total Cholesterol", "240", "mg/dL", "< 200", "HIGH"),
        ("HDL Cholesterol", "35", "mg/dL", "> 40", "LOW"),
        ("TSH", "5.2", "mIU/L", "0.4 - 4.0", "HIGH"),
        ("Creatinine", "1.4", "mg/dL", "0.6 - 1.2", "HIGH"),
    ]
    
    draw.text((20, y), "Test Results:", fill='black', font=text_font)
    y += 25
    
    for test_name, value, unit, range_text, flag in tests:
        flag_color = 'red' if flag in ['HIGH', 'LOW'] else 'black'
        line = f"{test_name:.<40} {value:>8} {unit:.<15} Range: {range_text} [{flag}]"
        draw.text((20, y), line, fill=flag_color)
        y += 20
    
    filepath = Path(__file__).parent / "sample_report_2_abnormal.png"
    img.save(filepath)
    print(f"Created {filepath}")


def create_sample_report_3():
    """Create sample report 3: Partial ranges (some missing)."""
    img = Image.new('RGB', (800, 600), color='white')
    draw = ImageDraw.Draw(img)
    
    try:
        title_font = ImageFont.truetype("arial.ttf", 24)
        text_font = ImageFont.truetype("arial.ttf", 16)
    except:
        title_font = ImageFont.load_default()
        text_font = ImageFont.load_default()
    
    y = 20
    draw.text((20, y), "BLOOD TEST REPORT", fill='black', font=title_font)
    y += 40
    
    draw.text((20, y), "Date: 2026-11-04", fill='black')
    y += 30
    
    # Test results with some ranges missing
    tests = [
        ("Hemoglobin", "12.5", "g/dL", "12.0 - 15.5"),
        ("Blood Glucose (Random)", "145", "mg/dL", ""),  # No range
        ("Vitamin B12", "250", "pg/mL", ""),  # No range
        ("Vitamin D", "45", "ng/mL", "30 - 100"),
        ("Iron", "85", "mcg/dL", ""),  # No range
    ]
    
    draw.text((20, y), "Test Results:", fill='black', font=text_font)
    y += 25
    
    for test_name, value, unit, range_text in tests:
        range_display = range_text if range_text else "[No range]"
        line = f"{test_name:.<35} {value:>8} {unit:.<15} {range_display}"
        draw.text((20, y), line, fill='black')
        y += 20
    
    y += 10
    draw.text((20, y), "Note: Some tests do not have printed reference ranges", fill='orange')
    
    filepath = Path(__file__).parent / "sample_report_3_partial_ranges.png"
    img.save(filepath)
    print(f"Created {filepath}")


if __name__ == "__main__":
    create_sample_report_1()
    create_sample_report_2()
    create_sample_report_3()
    print("\nSample reports created in samples/")
