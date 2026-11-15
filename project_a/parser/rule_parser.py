"""Rule-based extractor: regular expressions + keyword tables for English and Hinglish.

Strategy: normalise the text, split it into clauses, find money amounts (with units like lakh / k / crore /
LPA and periods like per month / mahina), and attach each amount to the field whose keyword is nearest in
the same clause. Anything uncertain is reported as an issue so that validate() asks instead of guessing.
"""
from __future__ import annotations

import re

from project_a.parser.validate import Extraction, ParseResult, validate

METROS = r"\b(delhi|new delhi|mumbai|bombay|kolkata|calcutta|chennai|madras)\b"
NON_METROS = (r"\b(bengaluru|bangalore|hyderabad|pune|noida|gurgaon|gurugram|ghaziabad|faridabad|ahmedabad|"
              r"jaipur|lucknow|kochi|coimbatore|indore|chandigarh|nagpur|thane|navi mumbai|bhopal|surat|"
              r"vadodara|mysore|mysuru|trivandrum|patna|bhubaneswar|vizag|visakhapatnam)\b")
PARENT = r"(parent|\bmom\b|\bmum\b|\bdad\b|(?<!grand)mother|(?<!grand)father|mummy|papa|\bmaa\b|\bmata\b|\bpita\b)"
SPOUSE = r"(wife|husband|spouse|patni|pati\b)"
MONTHLY = r"(per\s*month|/\s*month|/\s*mo\b|a\s*month|monthly|\bpm\b|p\.m\.|mahina|mahine|mahiney|month)"
ANNUAL = r"(per\s*annum|p\.a\.|\bpa\b|a\s*year|per\s*year|yearly|annual|annually|/\s*yr|/\s*year|saal\s*k[ie]|lpa)"
OUT_OF_SCOPE = (r"capital gain|selling shares|sold shares|from shares|stocks?\b|crypto|freelanc|business income|"
                r"consult(ing|ancy) income|rental income|rented out|let out|given on rent|fd interest|"
                r"interest income|dividend|side income|youtube income")

WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
         "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
         "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
         "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}

# (field, keyword regex) — checked in this order; the nearest keyword before an amount wins.
FIELD_KEYWORDS = [
    ("sec80ccd1b", r"\bnps\b|80ccd"),
    ("sec80d", r"health\s*insurance|mediclaim|medical\s*insurance|medical\s*expense|medical|80d\b|"
               r"health\s*cover"),
    ("sec80c", r"80c\b|\bppf\b|\belss\b|\bepf\b|\bpf\b|provident|\blic\b|life\s*insurance|tuition|principal|"
               r"sukanya|\bnsc\b|tax\s*saver"),
    ("home_loan_interest", r"home\s*loan|housing\s*loan|interest"),
    ("hra_received", r"\bhra\b|house\s*rent\s*allowance"),
    ("rent_paid", r"\brent\b|kiraya|kiraaya|rented"),
    ("basic_da", r"\bbasic\b"),
    ("bonus", r"\bbonus\b|incentive"),
    ("gross_salary", r"salary|salry|salaried|\bctc\b|package|\bgross\b|\bincome\b|\bearn|\bmake\b|"
                     r"tankhwah|tankha|pagaar|\blpa\b|\bbase\b|\bcomp\b"),
]

AMOUNT = re.compile(r"(?<![\w.])(-?\d+(?:\.\d+)?)\s*(crores?|cr\b|lakhs?|lacs?|lac\b|lpa\b|l\b|k\b|thousand|"
                    r"hazaa?r|hajar)?")


def _words_to_numbers(t: str) -> str:
    def repl(m):
        a = WORDS[m.group(1)]
        b = WORDS.get(m.group(2) or "", 0) if m.group(2) else 0
        return str(a + b)
    keys = "|".join(sorted(WORDS, key=len, reverse=True))
    return re.sub(rf"\b({keys})(?:[\s-]({keys}))?\b", repl, t)


def normalise(text: str) -> str:
    t = text.lower()
    t = t.replace("₹", " ").replace("/-", " ").replace("inr", " ")
    t = re.sub(r"\brs\.?\s*", " ", t)
    t = re.sub(r"(?<=\d),(?=\d)", "", t)          # 18,50,000 -> 1850000
    t = _words_to_numbers(t)
    return re.sub(r"\s+", " ", t)


def _money(num: str, unit: str | None) -> tuple[int, bool]:
    """Returns (rupees, unit_given)."""
    n = float(num)
    u = (unit or "").strip()
    if u.startswith("cr"):
        return int(round(n * 1e7)), True
    if u.startswith(("lakh", "lac", "lpa")) or u == "l":
        return int(round(n * 1e5)), True
    if u in ("k", "thousand") or u.startswith(("haza", "hajar")):
        return int(round(n * 1e3)), True
    return int(round(n)), False


def _ages(t: str) -> list[int]:
    found = []
    pats = [r"(?:\bage[d]?|\bumar|\bumr)\s*(?:is|:|-|of)?\s*(\d{1,3})\b",
            r"\b(\d{1,3})\s*(?:-?\s*years?\s*-?\s*old|yrs?\s*old|yo\b|y/o|-year-old|year-old)",
            r"\b(\d{1,3})\s*(?:years|yrs|y)\b(?!\s*(?:of|experience|exp))",
            r"(?:\bi am|\bi'm|\bim|\bmain)\s+(?:a\s+|an\s+)?(\d{1,3})\b(?!\s*(?:lakh|k\b|lpa|%|,000))",
            r"\b(\d{1,3})\s*saal\s*(?:ka|ki|ke)\b",
            r"\b(\d{2})\s*[mf]\b",
            r"\bi am\s+(?:a\s+)?(\d{1,3})[\s,.]",
            r"\bi am an? nri,?\s*(\d{1,3})\b"]
    for p in pats:
        for m in re.finditer(p, t):
            before = t[max(0, m.start() - 25):m.start()]
            if re.search(SPOUSE + r"|" + PARENT, before):
                continue
            after = t[m.end():m.end() + 12]
            if re.match(r"\s*(lakh|lac|lpa|crore|cr\b|k\b|thousand|hazaa?r|per\s*month)", after):
                continue
            found.append(int(m.group(1)))
    # "umar 41 saal" / "age 44" already covered; "dono 70 ke upar" is parents.
    return found


def extract(text: str) -> Extraction:
    t = normalise(text)
    ex = Extraction(fields={}, mentioned=set(), issues=[], source="rules")
    f = ex.fields

    # financial year
    m = re.search(r"\bfy\s*(20\d\d)\s*[-/]\s*(\d\d)", t)
    a = re.search(r"\bay\s*(20\d\d)\s*[-/]\s*(\d\d)", t)
    if m:
        f["fy"] = f"{m.group(1)}-{m.group(2)}"
    elif a:
        y = int(a.group(1)) - 1
        f["fy"] = f"{y}-{str(y + 1)[-2:]}"

    # residency, city
    if re.search(r"\bnri\b|non[-\s]?resident", t):
        f["resident"] = False
    metro_hits, non_metro_hits = re.findall(METROS, t), re.findall(NON_METROS, t)
    if metro_hits and non_metro_hits:
        if re.search(r"\bor\b|between|shift|both", t):
            ex.issues.append({"field": "metro", "kind": "ambiguous", "detail": "two cities mentioned"})
        else:
            f["metro"] = False  # e.g. "Noida (Delhi NCR)": the specific non-metro city wins
    elif metro_hits:
        f["metro"] = True
    elif non_metro_hits:
        f["metro"] = False

    # age
    ages = _ages(t)
    am = re.search(r"\bage[d]?\s*(?:is|:)?\s*(\d{1,3})\b", t)
    if am and re.search(r"wait|actually|sorry|correction|as per|\bor\b|\(", t[am.end():am.end() + 40]):
        # "age 61 (wait, 58 as per pan ...)" -> a second, correcting age close by
        for m2 in re.finditer(r"\b(\d{2})\b(?!\s*(?:lakh|lac|lpa|k\b|%|crore|thousand|,000))", t):
            if am.end() <= m2.start() <= am.end() + 40:
                ages.append(int(m2.group(1)))
    ages = sorted(set(ages))
    if len(ages) == 1:
        f["age"] = ages[0]
    elif len(ages) > 1:
        ex.issues.append({"field": "age", "kind": "conflict", "detail": f"ages {ages}"})

    # spouse / parents seniority
    sm = re.search(SPOUSE + r"\D{0,15}(\d{2})\b", t)
    if sm and int(sm.group(2)) >= 60:
        f["spouse_senior"] = True
    if re.search(PARENT, t):
        if re.search(PARENT + r".{0,60}(senior|above\s*6\d|over\s*6\d|\b[6-9]\d\b|ke\s*upar)", t) or \
                re.search(r"senior\s*(citizen\s*)?parents", t):
            f["parents_senior"] = True
        elif re.search(PARENT + r".{0,60}(below\s*60|under\s*60|not\s*senior|\b[3-5]\d\b)", t):
            f["parents_senior"] = False

    if re.search(OUT_OF_SCOPE, t):
        ex.issues.append({"field": "out_of_scope", "kind": "out_of_scope", "detail": "non-salary income"})
    if re.search(r"\bctc\b|cost to company", t):
        ex.issues.append({"field": "gross_salary", "kind": "ctc",
                          "detail": "CTC includes employer PF/gratuity, which is not taxable salary"})
    if re.search(r"(don'?t|do not|no)\s+(pay\s+)?(any\s+)?rent", t) and re.search(r"\brent\b.{0,20}\d", t):
        ex.issues.append({"field": "rent_paid", "kind": "conflict", "detail": "says no rent and gives a rent"})
    if re.search(r"(doesn'?t|does not|don'?t|no)\s+(give\s+|get\s+|pay\s+)?(any\s+)?hra", t):
        f["hra_received"] = 0
    if re.search(r"\bno (salary|income)\b|unemployed", t):
        f["gross_salary"] = 0
    if re.search(r"80c\s*(is\s*)?(maxed|full|pura|poora|exhausted)|(maxed|full)\s*(out\s*)?80c", t):
        f["sec80c"] = 150000
    for kw, fld in (("home loan|housing loan", "home_loan"), (r"health\s*insurance|mediclaim", "health_insurance"),
                    (r"\bhra\b", "hra"), (r"\brent\b|kiraya", "rent")):
        if re.search(kw, t):
            ex.mentioned.add(fld)

    # amounts -> fields
    salary_vals, bonus_vals = [], []
    sums = {"sec80c": 0, "sec80d_self": 0, "sec80d_parents": 0}
    seen80c = False
    prev_topic = None
    for clause in re.split(r"(?<!\d)\.|\.(?!\d)|[;\n]|,(?!\d)|\band\b|\baur\b|\bplus\b", t):
        topic_in_clause = None
        for m in AMOUNT.finditer(clause):
            num, unit = m.group(1), m.group(2)
            after = clause[m.end():m.end() + 30]
            before = clause[max(0, m.start() - 6):m.start()]
            if re.match(r"\s*(-?\s*years?|yrs?|yo\b|y\b|saal\s*k[ae]|ke\s*upar|%|year-old|\))", after) or \
                    re.search(r"(age|umar|aged)\s*$", clause[:m.start()].strip()[-8:]):
                continue
            if re.search(r"\b(fy|ay|section|sec)\s*$", before) or re.match(r"\s*-\s*\d\d", after):
                continue
            if not unit and float(num) < 1000 and not re.match(r"\s*(per|/|a\s*month|monthly)", after):
                continue  # small bare numbers (ages, 80C, 1990) are not money
            if re.match(r"\d{4}$", num) and 1900 <= int(num) <= 2100 and not unit:
                continue  # a year
            val, unit_given = _money(num, unit)
            window_before = clause[:m.start()]
            window_after = clause[m.end():]
            period = None
            if re.search(r"^\s*\S*\s*" + MONTHLY, window_after[:25]) or re.search(MONTHLY + r"\s*$", window_before[-25:]) \
                    or re.search(r"\bmonthly\b", window_before):
                period = "month"
            elif (unit or "").startswith("lpa") or re.search(ANNUAL, window_after[:25]) or \
                    re.search(r"(annual|yearly|per annum)", window_before):
                period = "year"
            # nearest keyword before the amount, else after it
            best = None
            for fld, kw in FIELD_KEYWORDS:
                for km in re.finditer(kw, window_before):
                    dist = len(window_before) - km.end()
                    if best is None or dist < best[1]:
                        best = (fld, dist)
            if best is None:
                for fld, kw in FIELD_KEYWORDS:
                    km = re.search(kw, window_after)
                    if km and (best is None or km.start() < best[1]):
                        best = (fld, km.start())
            if (unit or "").startswith("lpa"):
                best = ("gross_salary", 0)
            fld = best[0] if best else (topic_in_clause or prev_topic)
            if fld is None and len(t) < 30 and not salary_vals:
                fld = "gross_salary"  # bare "15l, 30y" style input
            if fld is None:
                continue
            topic_in_clause = fld
            if period == "month":
                val *= 12
            if fld == "gross_salary":
                if period is None and not unit_given and val < 500000:
                    ex.issues.append({"field": "gross_salary", "kind": "ambiguous_period",
                                      "detail": f"{val} without per month / per year"})
                if period is None and unit in ("k", "thousand") and val < 500000:
                    ex.issues.append({"field": "gross_salary", "kind": "ambiguous_period",
                                      "detail": f"{val} without per month / per year"})
                salary_vals.append(val)
            elif fld == "bonus":
                bonus_vals.append(val)
            elif fld == "sec80c":
                sums["sec80c"] += val
                seen80c = True
            elif fld == "sec80d":
                if re.search(PARENT, clause):
                    sums["sec80d_parents"] += val
                else:
                    sums["sec80d_self"] += val
            elif fld == "rent_paid":
                if period is None and val < 100000:
                    ex.issues.append({"field": "rent_paid", "kind": "ambiguous_period",
                                      "detail": f"rent {val} without per month / per year"})
                f["rent_paid"] = val
            elif fld == "home_loan_interest":
                if re.search(r"principal", window_before[-20:]):
                    sums["sec80c"] += val
                    seen80c = True
                else:
                    f["home_loan_interest"] = val
            else:
                f[fld] = val
        if topic_in_clause:
            prev_topic = topic_in_clause if topic_in_clause in ("sec80d", "sec80c") else None
        else:  # a keyword-only clause ("medical insurance for me") sets the topic for the next clause
            for fld_kw, kw in FIELD_KEYWORDS:
                if fld_kw in ("sec80d", "sec80c") and re.search(kw, clause):
                    prev_topic = fld_kw
                    break

    if salary_vals:
        distinct = sorted(set(salary_vals))
        if len(distinct) > 1:
            ex.issues.append({"field": "gross_salary", "kind": "conflict", "detail": f"salaries {distinct}"})
        else:
            f["gross_salary"] = distinct[0] + sum(bonus_vals)
        if any(v < 0 for v in distinct):
            f["gross_salary"] = min(distinct)
    if seen80c and "sec80c" not in f:
        f["sec80c"] = sums["sec80c"]
    if sums["sec80d_self"]:
        f["sec80d_self_family"] = sums["sec80d_self"]
    if sums["sec80d_parents"]:
        f["sec80d_parents"] = sums["sec80d_parents"]
    if "hra_received" in f and f["hra_received"] and "hra" not in ex.mentioned:
        ex.mentioned.add("hra")
    return ex


def parse(text: str, default_fy: str = "2024-25") -> ParseResult:
    return validate(extract(text), default_fy=default_fy, text=text)
