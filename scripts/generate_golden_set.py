"""Generate data/golden_set.jsonl — 150 synthetic grievances.

Distribution (§9.1):
  * ~11 clean single-department items per department (10 departments = 110)
  * 10 labelled OTHER (education, health, water supply, roads, revenue, pensions)
  * 12 covering traps T1–T12 exactly
  * 10 romanised gu-latn / code-mixed
  * 8 multi-department (primary + secondary both labelled)

Deterministic (seed 42). A 40% dev / 60% test split is assigned per
department so centroids get coverage; metrics are reported on the test split
only. Run:  python scripts/generate_golden_set.py
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "golden_set.jsonl"
SEED = 42

DISTRICTS = [
    "Ahmedabad", "Amreli", "Anand", "Banaskantha", "Bharuch", "Bhavnagar",
    "Dahod", "Gandhinagar", "Gir Somnath", "Jamnagar", "Junagadh", "Kutch",
    "Kheda", "Mehsana", "Morbi", "Narmada", "Navsari", "Panchmahal", "Patan",
    "Rajkot", "Sabarkantha", "Surat", "Surendranagar", "Tapi", "Vadodara", "Valsad",
]
TALUKAS = ["Deesa", "Kalol", "Bardoli", "Olpad", "Mandvi", "Sihor", "Vadgam",
           "Dhrol", "Kadi", "Lunawada", "Chotila", "Gondal", "Prantij", "Vansda"]

# Department -> list of Gujarati "issue" fragments built from real keywords.
DEPT_FRAGMENTS: dict[str, list[str]] = {
    "ENERGY": [
        "છેલ્લા પાંચ દિવસથી વીજળી નથી અને ટ્રાન્સફોર્મર બળી ગયું છે",
        "વીજપોલ તૂટી ગયો છે અને લો-વોલ્ટેજ ની ગંભીર સમસ્યા છે",
        "પીજીવીસીએલ અંધારપટ નો ઉકેલ લાવતું નથી વારંવાર ફરિયાદ કરી",
        "લાઈટો વારંવાર જાય છે અને વીજ કંપની કોઈ જવાબ આપતી નથી",
    ],
    "AGRICULTURE": [
        "ખેડૂતોને યુરિયા ખાતર મળતું નથી અને ખાતરની અછત છે",
        "એપીએમસી માર્કેટયાર્ડમાં ટેકાના ભાવે ખરીદી હજુ શરૂ થઈ નથી",
        "બિયારણ અને પીએમ કિસાન યોજના નો લાભ ખેડૂતની ને મળ્યો નથી",
        "પાકોની નુકસાની નું વળતર બાકી છે અને પશુદવાખાનુ બંધ છે",
    ],
    "FOOD_CIVIL": [
        "રાશન કાર્ડ પર છેલ્લા બે મહિનાથી અનાજ મળ્યું નથી પ્રાઈસ શોપ બંધ",
        "પુરવઠા વિભાગ કહે છે પુરવઠો આવ્યો નથી અને રેશનીંગનો જથ્થો ઓછો",
        "અનાજ ગોડાઉન માં ભ્રષ્ટાચાર ફૂડ સેફટી ની તપાસ કરો",
        "રાશનના અનાજની ગુણવત્તા ખરાબ છે રેશનીંગ માં ગેરરીતિ",
    ],
    "HOME": [
        "મુખ્ય રસ્તા પર ટ્રાફિક સિગ્નલ બંધ છે અને રોજ ટ્રાફિક જામ થાય છે",
        "પોલીસ ને ફરિયાદ કરી પણ ક્રાઇમ પર કોઈ કાર્યવાહી થતી નથી",
        "ઓવરલોડિંગ વાહન રોડ પર દોડે છે અને હોમગાર્ડ તૈનાત નથી",
        "ચાર્જશીટ અને રિમાન્ડ માં વિલંબ થાય છે પોલીસને જાણ કરી",
    ],
    "INDUSTRY": [
        "જીઆઇડીસી વિસ્તારમાં ઔદ્યોગિક એકમો ને પ્લોટ ફાળવણી માં વિલંબ",
        "ટેક્સટાઈલ ઈન્ડસ્ટ્રી અને કારખાના બંધ થવાથી રોજગારી ગઈ",
        "ઔદ્યોગિક વસાહત માં પાણી અને રસ્તા ની સુવિધા ઉદ્યોગ ને નથી",
        "ઈન્ડસ્ટ્રીયલ એકમ ની ચીમની નિયમ મુજબ નથી ઉદ્યોગો",
    ],
    "MINES": [
        "નદીમાં ગેરકાયદે રેતી ખનન ચાલે છે અને ખાણ માફિયા સક્રિય છે",
        "ખનીજ ચોરી અને કોલસા ની ગેરકાયદે હેરાફેરી થાય છે",
        "ખાણ પટ્ટા ની મંજૂરી માં વિલંબ થાય છે મિનરલ ખનન",
        "રેતી ખનન થી નદી નું ધોવાણ અને ખનીજ સંપત્તિ નું નુકસાન",
    ],
    "COTTAGE": [
        "કુટિર ઉદ્યોગ માટે માનવ કલ્યાણ યોજના હેઠળ ટુલકીટ મળી નથી",
        "પ્રધાનમંત્રી વિશ્વકર્મા યોજના નો લાભ કારીગરો ને મળ્યો નથી",
        "કિટ નું વિતરણ બાકી છે અને ગ્રામહાટ માં જગ્યા મળતી નથી",
        "કીટનું વિતરણ ધીમું છે કુટિર ઉદ્યોગ ના કારીગર પરેશાન",
    ],
    "FINANCE": [
        "ગામની બેંક નું એટીએમ છેલ્લા એક મહિનાથી બંધ છે",
        "નાણા વિભાગ ને રજૂઆત કરી પણ ટ્રેઝરી ચુકવણી બાકી છે",
        "નાણાપંચ ની ગ્રાન્ટ મળી નથી અને બજેટ ફાળવણી અટકી",
        "બેંકની સેવા ખરાબ છે અને એ.ટી.એમ કામ કરતું નથી",
    ],
    "ENVIRONMENT": [
        "કેમિકલ કંપની અભયારણ પાસે રસાયણિક કચરો ઠાલવે છે",
        "પર્યાવરણ ને નુકસાન થાય છે કારણ કે ધૂમાડો અને કેમિકલ્સ છોડાય છે",
        "વેધર સ્ટેશનનો ડેટા ખોટો છે અને પર્યાવરણ મંજૂરી વગર બાંધકામ",
        "રસાયણિક પ્રદૂષણ થી અભયારણમાં પ્રાણીઓ ને નુકસાન",
    ],
    "FISHERIES": [
        "માછીમારોને બોક્સ ફિશિંગ ની પરવાનગી મળતી નથી",
        "ઝીંગાના તળાવ માટે સહાય બાકી છે અને ફિશરિઝ વિભાગ ધ્યાન નથી આપતું",
        "માછીમારી નો ડીઝલ ક્વોટા મળતો નથી માછીમાર પરેશાન",
        "મત્સ્યોદ્યોગ વિભાગ માં અરજી છ મહિનાથી પેન્ડિંગ છે માછીમારીનો પ્રશ્ન",
    ],
}

OTHER_ITEMS = [
    "ગામની પ્રાથમિક શાળામાં છેલ્લા એક વર્ષથી શિક્ષક નથી",
    "પ્રાથમિક આરોગ્ય કેન્દ્રમાં ડોક્ટર અને દવા ઉપલબ્ધ નથી",
    "ગામમાં પીવાના પાણી ની લાઇન બંધ છે નળ માં પાણી આવતું નથી",
    "મુખ્ય રસ્તા પર મોટા ખાડા પડ્યા છે માર્ગ મકાન વિભાગ ધ્યાન નથી આપતું",
    "જમીન ના ૭/૧૨ ના ઉતારા અને મહેસૂલ રેકોર્ડ માં ભૂલ છે",
    "વૃદ્ધ પેન્શન છેલ્લા ત્રણ મહિનાથી બેંક ખાતામાં જમા થયું નથી",
    "આંગણવાડી માં બાળકો ને પોષણ આહાર મળતો નથી",
    "સરકારી શાળા નું મકાન જર્જરિત છે વર્ગખંડ ની અછત",
    "ગટર અને ડ્રેનેજ ની સમસ્યા થી ગંદકી ફેલાય છે",
    "સિવિલ હોસ્પિટલ માં બેડ અને સારવાર સમયસર મળતી નથી",
]

# Traps T1–T12 (exact).
TRAP_ITEMS = [
    ("કુટિર ઉદ્યોગ માટે માનવ કલ્યાણ યોજના હેઠળ ટુલકીટ હજુ મળી નથી", "COTTAGE", [], "gu", "T1"),
    ("મત્સ્યોદ્યોગ વિભાગમાં મારી અરજી છ મહિનાથી પેન્ડિંગ છે", "FISHERIES", [], "gu", "T2"),
    ("ગેસ એજન્સી બે મહિનાથી સિલિન્ડર આપતી નથી", "FOOD_CIVIL", [], "gu", "T3"),
    ("ગામમાં લાઈટો બંધ છે અને લાઇટ નથી આવતી", "ENERGY", [], "gu", "T4"),
    ("નાણા પંચ અને નાણાપંચ ની ભલામણ મુજબ ગ્રાન્ટ મળી નથી", "FINANCE", [], "gu", "T5"),
    ("ગામમાં હાઈ- ટેન્શન લાઇન નીચેથી પસાર થાય છે જોખમ છે", "ENERGY", [], "gu", "T6"),
    ("ટેકાના ભાવ થી ખરીદી શરૂ થઈ નથી અને પ્રાઈસ શોપ પર અનાજ નથી", "AGRICULTURE", ["FOOD_CIVIL"], "gu", "T7"),
    ("કારખાનાની ચીમનીમાંથી કાળો ધૂમાડો નીકળે છે પર્યાવરણ ને નુકસાન", "INDUSTRY", ["ENVIRONMENT"], "gu", "T8"),
    ("ઓવરલોડિંગ સાથે રેતી ખનન ની ટ્રક રાત્રે દોડે છે", "HOME", ["MINES"], "gu", "T9"),
    ("Primary school has no teacher in the village since last year", "OTHER", [], "en", "T10"),
    ("Amara gaam ma light nathi aavti, transformer bali gayu chhe, PGVCL ne kai vaar kahyu", "ENERGY", [], "gu-latn", "T11"),
    ("ગામમાં પાવર સપ્લાય ની સમસ્યા છે વીજળી વારંવાર જાય છે", "ENERGY", [], "gu", "T12"),
]

# Romanised / code-mixed (gu-latn).
ROMANISED_ITEMS = [
    ("Amara gaam ma vij nathi, transformer bali gayu, andharpat che", "ENERGY"),
    ("Khedut ne urea khatar nathi maltu, apmc marketyard band che", "AGRICULTURE"),
    ("Ration card par anaj nathi maltu, price shop wala kahe purvatha nathi", "FOOD_CIVIL"),
    ("Traffic signal band che ane roj traffic jaam thay che police ne kahyu", "HOME"),
    ("Bank nu atm ek mahina thi band che finance vibhag ne arji kari", "FINANCE"),
    ("Machimar ne fishing ni pargangi nathi malti jhinga talav sahay baki", "FISHERIES"),
    ("Gidc ma factory band thai, udyog ne plot falavni ma vilamb", "INDUSTRY"),
    ("Nadi ma gerkaydesar reti khanan chale che khaan mafia active", "MINES"),
    ("Kutir udyog mate toolkit nathi malyu manav kalyan yojana", "COTTAGE"),
    ("Chemical company paryavaran ne nuksan kare che dhumado nikle", "ENVIRONMENT"),
]

# Multi-department (primary + secondary).
MULTI_ITEMS = [
    ("કારખાનાની ચીમની માંથી ધૂમાડો અને કેમિકલ્સ થી પર્યાવરણ ને નુકસાન ઉદ્યોગ", "INDUSTRY", ["ENVIRONMENT"]),
    ("ટેકાના ભાવે ખરીદી નથી અને પ્રાઈસ શોપ પર અનાજ પુરવઠો નથી ખેડૂત", "AGRICULTURE", ["FOOD_CIVIL"]),
    ("ઓવરલોડિંગ વાહન અને રેતી ખનન ની ટ્રક પોલીસ ધ્યાન નથી આપતી ખાણ", "HOME", ["MINES"]),
    ("વીજ કંપની નું ટ્રાન્સફોર્મર બળી અને કેમિકલ કંપની ધૂમાડો પર્યાવરણ", "ENERGY", ["ENVIRONMENT"]),
    ("કુટિર ઉદ્યોગ ટુલકીટ અને જીઆઇડીસી ઔદ્યોગિક પ્લોટ બંને પ્રશ્ન", "COTTAGE", ["INDUSTRY"]),
    ("ગેસ એજન્સી સિલિન્ડર નથી અને વીજળી પણ નથી પાવર કાપ", "FOOD_CIVIL", ["ENERGY"]),
    ("માછીમારી નો ડીઝલ અને ઝીંગા તળાવ પર્યાવરણ મંજૂરી માછીમાર", "FISHERIES", ["ENVIRONMENT"]),
    ("બેંક એટીએમ બંધ અને પીએમ કિસાન યોજના ના નાણા ખેડૂત ને નથી મળ્યા", "FINANCE", ["AGRICULTURE"]),
]


def build_items() -> list[dict]:
    rng = random.Random(SEED)
    items: list[dict] = []

    # Clean single-department items (~11 per department).
    for dept, fragments in DEPT_FRAGMENTS.items():
        for i in range(11):
            frag = fragments[i % len(fragments)]
            district = DISTRICTS[(i + hash(dept)) % len(DISTRICTS)]
            taluka = TALUKAS[(i * 2 + hash(dept)) % len(TALUKAS)]
            if i % 3 == 0:
                text = frag
            elif i % 3 == 1:
                text = f"{district} જિલ્લાના {taluka} ગામમાં {frag}."
            else:
                text = (
                    f"માનનીય સાહેબ, {district} જિલ્લાના {taluka} તાલુકામાં {frag}. "
                    f"અમે અનેક વાર રજૂઆત કરી છે પણ કોઈ કાર્યવાહી થઈ નથી, કૃપા કરી તાત્કાલિક ધ્યાન આપો."
                )
            items.append({
                "text": text, "expected_department_code": dept, "expected_secondary": [],
                "language": "gu", "tags": ["clean", dept], "notes": "",
            })

    for text in OTHER_ITEMS:
        lang = "en" if all(ord(c) < 128 for c in text.replace(" ", "")) else "gu"
        items.append({"text": text, "expected_department_code": "OTHER", "expected_secondary": [],
                      "language": lang, "tags": ["other"], "notes": "not in seeded departments"})

    for text, dept, sec, lang, trap in TRAP_ITEMS:
        items.append({"text": text, "expected_department_code": dept, "expected_secondary": sec,
                      "language": lang, "tags": ["trap", trap], "notes": f"trap {trap}"})

    for text, dept in ROMANISED_ITEMS:
        items.append({"text": text, "expected_department_code": dept, "expected_secondary": [],
                      "language": "gu-latn", "tags": ["romanised"], "notes": "romanised gujlish"})

    for text, dept, sec in MULTI_ITEMS:
        items.append({"text": text, "expected_department_code": dept, "expected_secondary": sec,
                      "language": "gu", "tags": ["multi", *sec], "notes": "multi-department"})

    # Assign a 40% dev / 60% test split, stratified by primary department.
    by_dept: dict[str, list[int]] = {}
    for idx, item in enumerate(items):
        by_dept.setdefault(item["expected_department_code"], []).append(idx)
    for _dept, indices in by_dept.items():
        shuffled = indices[:]
        rng.shuffle(shuffled)
        n_dev = max(1, math.floor(0.4 * len(shuffled)))
        dev_set = set(shuffled[:n_dev])
        for idx in indices:
            items[idx]["split"] = "dev" if idx in dev_set else "test"
    return items


def main() -> None:
    items = build_items()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    dev = sum(1 for i in items if i["split"] == "dev")
    test = len(items) - dev
    print(f"Wrote {len(items)} golden samples to {OUT} ({dev} dev / {test} test)")


if __name__ == "__main__":
    main()
