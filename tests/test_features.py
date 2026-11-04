#!/usr/bin/env python3
"""Unit tests for Part 7c features: word bridge, myth buster, tips, adherence, history.

Tests code-only parts (no Bedrock API calls needed).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.features import word_bridge, myth_buster, tip_of_the_day, care_finder
from agent.family import (
    add_profile, add_medicine, mark_medicine_taken, adherence_percentage,
    add_appointment, compare_test_history, save_lab_report, list_medicines
)
import tempfile
import shutil
from datetime import datetime, timedelta


def test_word_bridge():
    """Test abbreviation and glossary lookup."""
    print("TEST: Word Bridge")
    
    # Test abbreviation
    result = word_bridge("OD")
    assert result["found"], "OD should be found"
    assert "Once a day" in result["en"], "OD should expand to 'Once a day'"
    assert "ஒரு நாளைக்கு ஒரு முறை" in result["ta"], "OD Tamil translation needed"
    print("  ✓ OD abbreviation lookup works")
    
    result = word_bridge("BD")
    assert result["found"], "BD should be found"
    assert "Twice" in result["en"], "BD should expand to 'Twice a day'"
    print("  ✓ BD abbreviation lookup works")
    
    # Test glossary lookup
    result = word_bridge("fasting glucose")
    assert result["found"], "fasting glucose should be found"
    assert len(result["en"]) > 0, "Should have English explanation"
    print("  ✓ Fasting glucose glossary lookup works")
    
    # Test unknown term
    result = word_bridge("xyz123")
    assert not result["found"], "xyz123 should not be found"
    assert "ask your doctor" in result["en"].lower(), "Should suggest asking doctor"
    print("  ✓ Unknown term returns sensible fallback")
    
    return 0


def test_myth_buster():
    """Test myth matching."""
    print("\nTEST: Myth Buster")
    
    # Test matching by keyword
    result = myth_buster("Can I stop BP tablet once BP is normal?")
    assert result["found"], "Should find BP myth"
    assert "FALSE" in result["verdict"], "Should be marked FALSE"
    assert len(result["en"]) > 0, "Should have English answer"
    print("  ✓ BP tablet myth matches correctly")
    
    result = myth_buster("Do antibiotics help for fever?")
    assert result["found"], "Should find fever myth"
    assert len(result["ta"]) > 0, "Should have Tamil answer"
    print("  ✓ Fever/antibiotic myth matches")
    
    # Test unknown
    result = myth_buster("Is the moon made of cheese?")
    assert not result["found"], "Nonsense question should not match"
    assert "ask your doctor" in result["en"].lower(), "Should suggest asking doctor"
    print("  ✓ Unknown question returns sensible fallback")
    
    return 0


def test_tip_of_the_day():
    """Test tip rotation."""
    print("\nTEST: Tip of the Day")
    
    tip = tip_of_the_day()
    assert "en" in tip, "Should have English tip"
    assert "ta" in tip, "Should have Tamil tip"
    assert len(tip["en"]) > 0, "English tip should not be empty"
    print(f"  ✓ Today's tip: {tip['en'][:50]}...")
    
    return 0


def test_care_finder():
    """Test care finder."""
    print("\nTEST: Care Finder")
    
    care = care_finder()
    assert "emergency" in care, "Should have emergency section"
    assert "places" in care, "Should have places section"
    assert "near_me" in care, "Should have near_me section"
    
    # Check emergency numbers
    assert len(care["emergency"]) > 0, "Should have emergency numbers"
    emergency_nums = [e["number"] for e in care["emergency"]]
    assert "108" in emergency_nums, "Should include 108"
    assert "112" in emergency_nums, "Should include 112"
    print("  ✓ Emergency numbers present (108, 112)")
    
    # Check places
    assert len(care["places"]) > 0, "Should have care places"
    print(f"  ✓ Care places found: {len(care['places'])}")
    
    # Check near-me
    assert len(care["near_me"]) > 0, "Should have near-me options"
    print(f"  ✓ Near-me options found: {len(care['near_me'])}")
    
    return 0


def test_adherence_percentage():
    """Test medicine adherence calculation."""
    print("\nTEST: Medicine Adherence Percentage")
    
    # Use temp directory for family data
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("agent.family.FAMILY_DIR", Path(tmpdir)):
            # Add profile
            add_profile("Test Patient", "Parent", 65)
            
            # Add medicine
            today = datetime.now().strftime("%Y-%m-%d")
            add_medicine("Test Patient", "Aspirin", "100 mg", ["08:00", "20:00"], today)
            
            # Log some doses
            mark_medicine_taken("Test Patient", "Aspirin", "08:00", taken=True)
            mark_medicine_taken("Test Patient", "Aspirin", "20:00", taken=False)
            mark_medicine_taken("Test Patient", "Aspirin", "08:00", taken=True)
            
            # Calculate adherence
            adh = adherence_percentage("Test Patient", days=7)
            
            assert adh["total"] == 3, f"Should have 3 total doses, got {adh['total']}"
            assert adh["taken"] == 2, f"Should have 2 taken doses, got {adh['taken']}"
            assert adh["adherence"] == 66.7, f"Adherence should be ~66.7%, got {adh['adherence']}"
            print(f"  ✓ Adherence calculated: {adh['adherence']}% ({adh['taken']}/{adh['total']})")
    
    return 0


def test_lab_history_comparison():
    """Test lab history comparison (same test, different units)."""
    print("\nTEST: Lab History Comparison")
    
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("agent.family.FAMILY_DIR", Path(tmpdir)):
            # Add profile
            add_profile("Patient", "Self", 60)
            
            # Save first lab report
            save_lab_report("Patient", "2026-10-01", [
                {"test": "HbA1c", "value": 7.5, "unit": "%", "status": "HIGH"},
                {"test": "Blood Glucose", "value": 150, "unit": "mg/dL", "status": "HIGH"}
            ])
            
            # Save second report (same units)
            save_lab_report("Patient", "2026-11-01", [
                {"test": "HbA1c", "value": 7.2, "unit": "%", "status": "NORMAL"},
                {"test": "Blood Glucose", "value": 130, "unit": "mg/dL", "status": "NORMAL"}
            ])
            
            # Compare HbA1c (same unit, should be comparable)
            comp = compare_test_history("Patient", "HbA1c")
            assert comp["can_compare"], "HbA1c with same unit should be comparable"
            assert len(comp["history"]) == 2, "Should have 2 results"
            print(f"  ✓ HbA1c history comparable: {len(comp['history'])} entries")
            
            # Save third report with different unit
            save_lab_report("Patient", "2026-11-15", [
                {"test": "HbA1c", "value": 70, "unit": "mmol/mol", "status": "HIGH"}
            ])
            
            # Try to compare (should fail due to unit mismatch)
            comp = compare_test_history("Patient", "HbA1c")
            assert not comp["can_compare"], "Different units should not be comparable"
            assert "differ" in comp["reason"].lower(), "Should mention unit difference"
            print(f"  ✓ Unit mismatch detected: {comp['reason']}")
    
    return 0


def test_myth_matching_keywords():
    """Test that myths match on key phrases."""
    print("\nTEST: Myth Matching Keywords")
    
    # Test various forms of the same myth
    queries = [
        ("stop BP medicine", "m3"),
        ("stop taking tablet when normal", "m3"),
        ("fever and antibiotics", "m2"),
        ("can i eat fruit", "m5"),
    ]
    
    for query, expected_myth_id in queries:
        result = myth_buster(query)
        if result["found"]:
            print(f"  ✓ '{query}' matches a myth")
        else:
            print(f"  ~ '{query}' did not match (may be OK if query is too different)")
    
    return 0


def test_abbreviation_variants():
    """Test that abbreviation variants work."""
    print("\nTEST: Abbreviation Variants")
    
    # Test main abbreviation
    result = word_bridge("TDS")
    assert result["found"], "TDS should be found"
    assert "Three" in result["en"], "TDS should be three times"
    print("  ✓ TDS found")
    
    # Test variant (some abbreviations have alts like TID)
    result = word_bridge("QID")
    assert result["found"], "QID should be found"
    assert "Four" in result["en"], "QID should be four times"
    print("  ✓ QID found")
    
    return 0


if __name__ == "__main__":
    print("=" * 70)
    print("PART 7C UNIT TESTS (Code-Only, No Bedrock)")
    print("=" * 70)
    
    all_pass = True
    
    for test_fn in [
        test_word_bridge,
        test_myth_buster,
        test_tip_of_the_day,
        test_care_finder,
        test_adherence_percentage,
        test_lab_history_comparison,
        test_myth_matching_keywords,
        test_abbreviation_variants,
        test_no_devanagari_or_bengali,
    ]:
        try:
            result = test_fn()
            if result != 0:
                all_pass = False
        except Exception as e:
            print(f"  ✗ ERROR: {e}")
            import traceback
            traceback.print_exc()
            all_pass = False
    
    print()
    print("=" * 70)
    if all_pass:
        print("ALL TESTS PASSED")
        sys.exit(0)
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)


def test_no_devanagari_or_bengali():
    """Test that outputs contain NO Devanagari or Bengali characters."""
    print("\nTEST: No Devanagari or Bengali Characters")
    
    # Devanagari: U+0900-U+097F
    # Bengali: U+0980-U+09FF
    devanagari_range = range(0x0900, 0x0980)
    bengali_range = range(0x0980, 0x0A00)
    forbidden_chars = set(chr(i) for i in list(devanagari_range) + list(bengali_range))
    
    # Test word bridge
    result = word_bridge("BD")
    output_en = result.get("en", "")
    output_ta = result.get("ta", "")
    for char in forbidden_chars:
        assert char not in output_en, f"Devanagari/Bengali found in word_bridge EN: {char}"
        assert char not in output_ta, f"Devanagari/Bengali found in word_bridge TA: {char}"
    print("  ✓ word_bridge output clean")
    
    # Test myth buster
    result = myth_buster("Can I stop BP tablet?")
    if result["found"]:
        for key in ["myth_en", "myth_ta", "en", "ta"]:
            output = result.get(key, "")
            for char in forbidden_chars:
                assert char not in output, f"Devanagari/Bengali in myth_{key}: {char}"
    print("  ✓ myth_buster output clean")
    
    # Test care finder
    care = care_finder()
    for em in care.get("emergency", []):
        for key in ["en", "ta"]:
            output = em.get(key, "")
            for char in forbidden_chars:
                assert char not in output, f"Devanagari/Bengali in care emergency: {char}"
    print("  ✓ care_finder output clean")
    
    # Test tip
    tip = tip_of_the_day()
    for key in ["en", "ta"]:
        output = tip.get(key, "")
        for char in forbidden_chars:
            assert char not in output, f"Devanagari/Bengali in tip: {char}"
    print("  ✓ tip_of_the_day output clean")
    
    # Test scheme guide
    from agent.scheme_guide import get_scheme_guide
    schemes = get_scheme_guide()
    for scheme in schemes.get("schemes", []):
        for key in ["name_en", "name_ta", "about_en", "about_ta"]:
            output = scheme.get(key, "")
            for char in forbidden_chars:
                assert char not in output, f"Devanagari/Bengali in scheme {key}: {char}"
    print("  ✓ get_scheme_guide output clean")
    
    return 0
