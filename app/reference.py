"""Static reference data used across the UI."""
from __future__ import annotations

# The 33 districts of Gujarat (English value stored, Gujarati shown alongside).
GUJARAT_DISTRICTS: list[tuple[str, str]] = [
    ("Ahmedabad", "અમદાવાદ"), ("Amreli", "અમરેલી"), ("Anand", "આણંદ"),
    ("Aravalli", "અરવલ્લી"), ("Banaskantha", "બનાસકાંઠા"), ("Bharuch", "ભરૂચ"),
    ("Bhavnagar", "ભાવનગર"), ("Botad", "બોટાદ"), ("Chhota Udaipur", "છોટાઉદેપુર"),
    ("Dahod", "દાહોદ"), ("Dang", "ડાંગ"), ("Devbhoomi Dwarka", "દેવભૂમિ દ્વારકા"),
    ("Gandhinagar", "ગાંધીનગર"), ("Gir Somnath", "ગીર સોમનાથ"), ("Jamnagar", "જામનગર"),
    ("Junagadh", "જૂનાગઢ"), ("Kutch", "કચ્છ"), ("Kheda", "ખેડા"),
    ("Mahisagar", "મહીસાગર"), ("Mehsana", "મહેસાણા"), ("Morbi", "મોરબી"),
    ("Narmada", "નર્મદા"), ("Navsari", "નવસારી"), ("Panchmahal", "પંચમહાલ"),
    ("Patan", "પાટણ"), ("Porbandar", "પોરબંદર"), ("Rajkot", "રાજકોટ"),
    ("Sabarkantha", "સાબરકાંઠા"), ("Surat", "સુરત"), ("Surendranagar", "સુરેન્દ્રનગર"),
    ("Tapi", "તાપી"), ("Vadodara", "વડોદરા"), ("Valsad", "વલસાડ"),
]

DISTRICT_VALUES = {en for en, _gu in GUJARAT_DISTRICTS}
