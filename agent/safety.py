"""Nalam AI safety checks: plain Python, no model. Runs BEFORE any model call.

classify(text) -> {"kind": "distress" | "emergency" | "refuse" | None, "hits": [...]}

- distress  : suicide / self-harm words  -> Tele-MANAS 14416 + call family
- emergency : danger signs (chest pain, can't breathe, stroke signs...) -> gentle "go to hospital" warning + call buttons
- refuse    : asks for a diagnosis or a dose change -> fixed refusal, ask doctor/pharmacist
- support   : stress, loneliness, low mood -> caring fixed text + Tele-MANAS 14416 + call family

Phone numbers: 108 = Tamil Nadu emergency ambulance, 112 = India emergency number,
14416 = Tele-MANAS national mental health helpline (free, 24x7).
Every miss found while measuring must be added here, in every language.
"""
from __future__ import annotations

import re

DISTRESS = [
    "suicide", "kill myself", "want to die", "end my life", "no reason to live", "better off dead", "self harm",
    "தற்கொலை", "சாக வேண்டும்", "சாகணும்", "சாகப் போகிறேன்", "வாழ விருப்பம் இல்லை", "உயிரை மாய்த்து",
    "sethuralam", "saaganum", "saaga poren", "thatkolai", "vaazha pidikkala",
]

EMERGENCY = [
    "chest pain", "chest is paining", "heart attack", "can't breathe", "cannot breathe", "not able to breathe",
    "breathing difficulty", "difficulty breathing", "unconscious", "not responding", "fainted", "collapsed",
    "seizure", "fits", "stroke", "face drooping", "slurred speech", "one side weak", "cannot move one side",
    "snake bite", "snakebite", "heavy bleeding", "bleeding won't stop", "bleeding not stopping", "vomiting blood",
    "bleeding heavily", "bleeding a lot", "lot of blood", "drank poison", "swallowed poison", "poisoning", "overdose",
    "நெஞ்சு வலி", "நெஞ்சு வலிக்குது", "மூச்சு விட முடியவில்லை", "மூச்சு விட முடியல", "மூச்சுத் திணறல்",
    "மயங்கி விழுந்தார்", "மயங்கி விழுந்தாள்", "சுயநினைவு இல்லை", "வலிப்பு", "வாய் கோணல்", "வாய் கோண", "முகம் கோண", "கை தூக்க முடிய", "கால் தூக்க முடிய", "பேச்சு குழற", "ரத்தம் நிக்கல", "நிறைய ரத்தம்", "பக்கவாதம்",
    "பாம்பு கடி", "ரத்தம் நிற்கவில்லை", "இரத்தம் நிற்கவில்லை", "ரத்த வாந்தி", "விஷம் குடித்",
    "nenju vali", "nenjuvali", "moochu vida mudiyala", "moochu thinaral", "mayangi vizhundhutaanga",
    "mayangi vizhunthutanga", "valippu", "paambu kadi", "ratham nikkala", "visham kudichitaanga", "pakkavatham", "vaai konala", "kai thooka mudiyala", "pechu kozharuthu",
]

REFUSE = [
    # diagnosis
    "do i have", "does she have", "does he have", "does paati have", "does thatha have", "am i diabetic",
    "is it diabetes", "is it cancer", "is this cancer", "which disease", "what disease do",
    "நோய் இருக்கா", "நோய் இருக்கிறதா", "சர்க்கரை நோய் இருக்கா", "noi irukka", "sugar irukka", "cancer ah",
    # dose / medicine changes
    "can i take", "can she take", "can he take", "should i take", "should she take", "can i stop", "should i stop",
    "can she stop", "stop taking", "stop my tablet", "stop her tablet", "stop his tablet", "double the dose",
    "double dose", "extra dose", "extra tablet", "two tablets", "2 tablets", "increase the dose", "reduce the dose",
    "increase my dose", "double my dose", "double her dose", "double his dose", "skip my dose", "skip the dose", "more tablets", "take more tablet", "should i double", "reduce my dose", "change my dose", "change the dose", "how many tablets",
    "which tablet should", "which medicine should", "what medicine should",
    "நிறுத்தலாமா", "எத்தனை மாத்திரை", "இரண்டு மாத்திரை", "அளவை மாற்ற", "அளவைக் கூட்ட", "அளவைக் குறைக்க",
    "niruthalama", "nirutha lama", "rendu mathirai", "ethana mathirai", "dose koottalama", "dose korakkalama",
]

# Warning signs that come up in a normal chat (talking about a report or medicine).
# Not an emergency on their own: the app keeps answering, but first says
# "see a doctor today / go to hospital, tell your family; if severe call 108".
WARN = [
    "vomiting", "vomited", "keep vomiting", "loose motion", "diarrhoea", "diarrhea", "high fever", "fever since",
    "fever for", "dizzy", "dizziness", "giddy", "giddiness", "very weak", "too weak", "blurred vision",
    "blurry vision", "severe headache", "bad headache", "swelling", "swollen", "yellow eyes", "eyes are yellow",
    "black stool", "blood in urine", "blood in stool", "very thirsty", "confused", "confusion", "fell down",
    "வாந்தி", "வயிற்றுப்போக்கு", "பேதி", "அதிக காய்ச்சல்", "காய்ச்சல் விடல", "தலைசுற்ற", "தலை சுற்ற", "மயக்கமா",
    "ரொம்ப சோர்வா", "கண் மங்க", "கடுமையான தலைவலி", "வீக்கம்", "வீங்கி", "கண் மஞ்சள", "சிறுநீரில் ரத்தம்", "கீழே விழுந்",
    "vaanthi", "vandhi", "bedhi", "kaichal vidala", "romba kaichal", "thala suthuthu", "thalai suthal", "mayakkama",
    "romba sorva", "kan mangala", "veekkam", "veengi", "keezha vizhundh",
]

SUPPORT = [
    "depressed", "depression", "feeling low", "feel low", "very sad", "lonely", "alone all the time", "stressed",
    "stress", "anxiety", "anxious", "panic", "tension", "can't sleep", "cannot sleep", "no sleep", "worthless",
    "hopeless", "crying", "nobody cares", "no one cares",
    "மன அழுத்தம்", "மனச்சோர்வு", "தனிமை", "கவலையாக", "பதட்டம்", "தூக்கம் வரவில்லை", "யாரும் கவலைப்படவில்லை", "அழுகை", "டென்ஷன்", "தூக்கமே வரல", "தூக்கம் வரல", "தூக்கம் வரலை", "தனியா இருக்க",
    "mana azhutham", "kavalaya irukku", "kavala", "thanimai", "thookam varala", "padhattam", "tension ah irukku",
]

TEXT = {
    "emergency": {
        "en": "This sounds serious. Please go to the hospital now or call your family. If it is severe, like trouble breathing, fainting or chest pain, call 108 ambulance.",
        "ta": "இது தீவிரமாகத் தெரிகிறது. உடனே மருத்துவமனைக்குச் செல்லுங்கள் அல்லது குடும்பத்தினரை அழையுங்கள். மூச்சுத் திணறல், மயக்கம், நெஞ்சு வலி போல் கடுமையாக இருந்தால் 108 ஆம்புலன்ஸை அழையுங்கள்.",
    },
    "warn": {
        "en": "What you mentioned needs a doctor's check. Please don't wait: see a doctor today or go to the hospital, and tell your family. If it becomes severe, like trouble breathing or fainting, call 108.",
        "ta": "நீங்கள் சொன்னதை மருத்துவர் பார்க்க வேண்டும். காத்திருக்க வேண்டாம்: இன்றே மருத்துவரைப் பாருங்கள் அல்லது மருத்துவமனைக்குச் செல்லுங்கள், குடும்பத்தினரிடமும் சொல்லுங்கள். மூச்சுத் திணறல், மயக்கம் போல் கடுமையானால் 108-ஐ அழையுங்கள்.",
    },
    "distress": {
        "en": "I'm really glad you told me. You are not alone, and nobody will judge you. Please talk to someone right now: call Tele-MANAS 14416 (free, any time, in Tamil) or someone in your family.",
        "ta": "நீங்கள் என்னிடம் சொன்னது நல்லது. நீங்கள் தனியாக இல்லை, யாரும் உங்களைத் தவறாக நினைக்க மாட்டார்கள். இப்போதே யாரிடமாவது பேசுங்கள்: டெலி-மனஸ் 14416 (இலவசம், எப்போதும், தமிழில் பேசலாம்) அல்லது உங்கள் குடும்பத்தினரை அழையுங்கள்.",
    },
    "support": {
        "en": "I'm sorry you're feeling this way. It's okay to feel like this, and you don't have to carry it alone. A few things can help right now: breathe slowly (in for 4, out for 6), drink some water, step outside for a short walk, and talk to someone you trust. If it still feels heavy, you can call Tele-MANAS 14416. It is free, any time, in Tamil, and nobody will judge you.",
        "ta": "நீங்கள் இப்படி உணர்வது வருத்தமாக உள்ளது. இப்படி உணர்வது தவறில்லை, இதை நீங்கள் தனியாகச் சுமக்க வேண்டியதில்லை. இப்போது சில விஷயங்கள் உதவும்: மெதுவாக மூச்சு விடுங்கள் (4 எண்ணும் வரை உள்ளே, 6 எண்ணும் வரை வெளியே), கொஞ்சம் தண்ணீர் குடியுங்கள், சிறிது நேரம் வெளியே நடங்கள், நம்பிக்கையான ஒருவரிடம் பேசுங்கள். இன்னும் மனம் கனமாக இருந்தால் டெலி-மனஸ் 14416-ஐ அழைக்கலாம். இது இலவசம், எப்போது வேண்டுமானாலும், தமிழில் பேசலாம், யாரும் உங்களைத் தவறாக நினைக்க மாட்டார்கள்.",
    },
    "refuse": {
        "en": "I can't diagnose illness or change medicine doses. Please ask your doctor or pharmacist.",
        "ta": "நோயைக் கண்டறியவோ, மருந்தின் அளவை மாற்றவோ என்னால் முடியாது. உங்கள் மருத்துவர் அல்லது மருந்தாளரிடம் கேளுங்கள்.",
    },
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().replace("’", "'")).strip()


def _hits(text: str, phrases: list[str]) -> list[str]:
    found = []
    for p in phrases:
        p_low = p.lower()
        if p_low.isascii():
            if re.search(r"(?<![a-z])" + re.escape(p_low) + r"(?![a-z])", text):
                found.append(p)
        elif p_low in text:
            found.append(p)
    return found


# Extra first-aid line for specific emergencies (source: MedlinePlus Bleeding first aid,
# https://medlineplus.gov/ency/article/000045.htm). Shown after the emergency message.
BLEEDING = ["bleeding", "heavy bleeding", "lot of blood", "ரத்தம் நிற்கவில்லை", "இரத்தம் நிற்கவில்லை", "ரத்தம் நிக்கல", "நிறைய ரத்தம்", "ratham nikkala"]
FIRST_AID = {
    "bleeding": {
        "en": "While you wait: press firmly on the wound with a clean cloth and keep pressing. If blood soaks through, put another cloth on top; do not remove the first one.",
        "ta": "காத்திருக்கும்போது: சுத்தமான துணியால் காயத்தின் மீது அழுத்தமாக அழுத்திக்கொண்டே இருங்கள். ரத்தம் துணியை நனைத்தால், அதை எடுக்காமல் மேலே இன்னொரு துணியை வைத்து அழுத்துங்கள்.",
    },
}


def classify(text: str) -> dict:
    t = _norm(text)
    for kind, phrases in (("distress", DISTRESS), ("emergency", EMERGENCY), ("refuse", REFUSE), ("warn", WARN), ("support", SUPPORT)):
        h = _hits(t, phrases)
        if h:
            en, ta = TEXT[kind]["en"], TEXT[kind]["ta"]
            if kind == "emergency" and _hits(t, BLEEDING):
                en, ta = en + " " + FIRST_AID["bleeding"]["en"], ta + " " + FIRST_AID["bleeding"]["ta"]
            return {"kind": kind, "hits": h, "en": en, "ta": ta}
    return {"kind": None, "hits": []}
