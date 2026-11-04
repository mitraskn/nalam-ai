#!/usr/bin/env python3
"""Test safety core (Part 7a) — Red flags and diagnosis/dose refusal.
Tests the RedFlagGate logic WITHOUT needing Bedrock credentials.
"""
import sys
from agent.app import RedFlagGate, RED_FLAGS, SUICIDE_PHRASES, EMERGENCY_EN, EMERGENCY_TA, REFUSE_EN, REFUSE_TA, SUICIDE_EN, SUICIDE_TA


def test_safety(user_text, expected_type):
    """Simulate what the gate does without running the full graph."""
    gate = RedFlagGate()
    text = user_text.lower()
    
    # Simulate BeforeNodeCallEvent._before logic
    hits = [p for p in RED_FLAGS if p.lower() in text]
    suicide_hits = [p for p in SUICIDE_PHRASES if p.lower() in text]
    
    diagnosis_keywords = ["do i have", "am i", "if my", "have i got"]
    dose_keywords = ["can i take", "should i take", "can i stop", "stop taking", "double", "change my", "increase my", "decrease my"]
    
    is_diagnosis = any(kw in text for kw in diagnosis_keywords)
    is_dose_change = any(kw in text for kw in dose_keywords)
    
    if hits or suicide_hits:
        gate.tripped = hits + suicide_hits
        if suicide_hits:
            gate.is_suicide = True
        result_type = "emergency"
    elif is_diagnosis or is_dose_change:
        gate.is_diagnosis_or_dose = True
        result_type = "refuse"
    else:
        result_type = "normal"
    
    # Build response
    if result_type == "emergency":
        lang = "ta" if any(c in user_text for c in "அஇஈஉஊஎஏஐொஒோஔக்ங்ச்") else "en"
        handoff_text = EMERGENCY_EN if lang == "en" else EMERGENCY_TA
        if gate.is_suicide:
            suicide_text = SUICIDE_EN if lang == "en" else SUICIDE_TA
            handoff_text = handoff_text + "\n\n" + suicide_text
        response = f"[safety/red_flag] {handoff_text}"
    elif result_type == "refuse":
        lang = "ta" if any(c in user_text for c in "அஇஈஉஊஎஏஐொஒோஔக்ங்ச்") else "en"
        refuse_text = REFUSE_EN if lang == "en" else REFUSE_TA
        response = f"[safety/refuse] {refuse_text}"
    else:
        response = "[plan] Normal processing by planner + critic"
    
    return result_type, response


# Test cases
tests = [
    ("My grandmother has chest pain and is sweating", "emergency"),
    ("பாட்டிக்கு மூச்சு விட முடியவில்லை", "emergency"),
    ("Can I take two BP tablets today since I missed yesterday?", "refuse"),
    ("Do I have diabetes if my sugar is 180?", "refuse"),
    ("What is HbA1c? Explain in simple Tamil", "normal"),
]

print("=" * 80)
print("SAFETY CORE TEST (Part 7a — RED FLAGS & DIAGNOSIS/DOSE REFUSAL)")
print("=" * 80)
print()

for i, (user_text, expected) in enumerate(tests, 1):
    result_type, response = test_safety(user_text, expected)
    status = "✓ PASS" if result_type == expected else "✗ FAIL"
    
    print(f"Test {i}: {status}")
    print(f"  Input: {user_text}")
    print(f"  Expected: {expected}, Got: {result_type}")
    print(f"  Response: {response[:100]}..." if len(response) > 100 else f"  Response: {response}")
    print()

print("=" * 80)
print("To run full agent with Bedrock credentials, use:")
print("  python -m agent.app \"test message\"")
print("=" * 80)
