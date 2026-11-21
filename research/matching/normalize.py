"""Text normalisation used only to *retrieve* candidates.

Normalised values are never written back over original text. Every list below
is a documented retrieval heuristic, not a statement about identity.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# Spelling variants folded before comparison. One-way, lower-case, whole tokens.
ABBREVIATIONS = {
    "govt": "government", "gov": "government", "govermment": "government",
    "hosp": "hospital", "hsptl": "hospital", "hospitals": "hospital",
    "center": "centre", "centres": "centre", "centers": "centre", "ctr": "centre",
    "med": "medical", "coll": "college", "clg": "college",
    "dist": "district", "distt": "district",
    "pvt": "private", "ltd": "limited",
    "inst": "institute", "instt": "institute", "univ": "university",
    "dr": "doctor", "multispecialty": "multispeciality", "superspecialty": "superspeciality",
    "speciality": "speciality", "specialty": "speciality",
    "clinics": "clinic", "labs": "laboratory", "lab": "laboratory",
}

# Words that describe a kind of facility or organisation rather than name one.
GENERIC = frozenset("""
hospital clinic centre health medical nursing home care the and of for at in private limited
government district general multispeciality superspeciality speciality super multi doctor shri
sri smt new research institute college community primary sub trust charitable society memorial
maternity dispensary polyclinic healthcare services service unit dept department sciences
science civil referral public rural urban area sadar
""".split())

# Facility types that are not hospitals. Used only to stratify review.
NON_HOSPITAL_TYPES = frozenset({
    "pharmacy", "dentist", "alternative", "laboratory", "optometrist", "physiotherapist",
    "blood_bank", "veterinary", "doctor", "doctors", "nursing_home", "social_facility",
})

STATE_VARIANTS = {
    "orissa": "odisha", "pondicherry": "puducherry", "uttaranchal": "uttarakhand",
    "nct of delhi": "delhi", "new delhi": "delhi", "national capital territory of delhi": "delhi",
    "jammu kashmir": "jammu and kashmir", "andaman nicobar islands": "andaman and nicobar islands",
    # One union territory since 2020; sources use the old and the merged names.
    "dadra nagar haveli": "dadra and nagar haveli and daman and diu",
    "daman diu": "dadra and nagar haveli and daman and diu",
    "dadra nagar haveli daman diu": "dadra and nagar haveli and daman and diu",
    "the dadra nagar haveli daman diu": "dadra and nagar haveli and daman and diu",
}

ADDRESS_GENERIC = frozenset("""
road rd street st lane marg nagar near opp opposite behind beside the and of at in no number
colony sector block plot floor main cross circle chowk bazar bazaar market post po ps tehsil
taluk taluka mandal dist district city town village vill state india pin pincode
""".split())

_SPACE = re.compile(r"\s+")


def _strip_punctuation(value):
    """Keep letters, combining marks and digits of any script; everything else becomes a space."""
    return "".join(ch if unicodedata.category(ch)[0] in "LMN" else " " for ch in value)


def _strip_latin_marks(value):
    """Drop accents on Latin letters ('Rājasthān' -> 'Rajasthan'). Marks on other
    scripts stay: in Indic scripts they carry vowels and are part of the word."""
    out, latin = [], False
    for ch in unicodedata.normalize("NFD", value):
        if unicodedata.combining(ch):
            if latin:
                continue
        else:
            latin = "a" <= ch <= "z" or "A" <= ch <= "Z"
        out.append(ch)
    return unicodedata.normalize("NFC", "".join(out))


def fold(text):
    """NFKC, casefold, Latin accents removed, '&' to 'and', punctuation to
    spaces, collapsed whitespace."""
    if not isinstance(text, str):
        return None
    value = _strip_latin_marks(unicodedata.normalize("NFKC", text)).casefold().replace("&", " and ")
    value = _SPACE.sub(" ", _strip_punctuation(value)).strip()
    return value or None


def tokens(text):
    """Folded tokens with abbreviations expanded and dotted initials rejoined.

    'J.L.N. Govt. Hosp.' -> ['jln', 'government', 'hospital'].
    """
    value = fold(text)
    if value is None:
        return []
    out, letters = [], []
    for token in value.split(" "):
        if len(token) == 1 and token.isalpha():
            letters.append(token)
            continue
        if letters:
            out.append("".join(letters))
            letters = []
        out.append(ABBREVIATIONS.get(token, token))
    if letters:
        out.append("".join(letters))
    return out


def core(token_list):
    """Tokens that can discriminate one institution from another."""
    return [t for t in token_list if t not in GENERIC]


def initials(token_list):
    return "".join(t[0] for t in token_list if t and t[0].isalpha())


def state_key(text):
    value = fold(text)
    if value is None:
        return None
    value = " ".join(t for t in value.split(" ") if t != "and")
    return STATE_VARIANTS.get(value, STATE_VARIANTS.get(value.replace(" and ", " "), value))


def place_key(text):
    return fold(text)


def pin_key(value):
    """Six-digit text or None. Integers are accepted only when they are six digits."""
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip() if isinstance(value, (str, int)) else None
    if text is None or re.fullmatch(r"[0-9]{6}", text) is None:
        return None
    return text


def phone_keys(value):
    """National significant numbers (last ten digits) from text or a list of texts."""
    if value is None:
        return frozenset()
    items = value if isinstance(value, (list, tuple)) else re.split(r"[,;/|]", str(value))
    keys = set()
    for item in items:
        digits = re.sub(r"\D", "", str(item))
        if len(digits) >= 10:
            keys.add(digits[-10:])
    return frozenset(keys)


def address_tokens(text):
    return frozenset(t for t in tokens(text) if t not in ADDRESS_GENERIC and t not in GENERIC)


def acronym_hit(short_tokens, long_tokens):
    """True when a 2-6 letter token of one name spells the initials of a run of
    tokens in the other. Acronyms collide often, so this is weak evidence only."""
    for token in short_tokens:
        if not (2 <= len(token) <= 6 and token.isalpha()) or token in GENERIC:
            continue
        if token in long_tokens:
            continue
        n = len(token)
        for start in range(0, len(long_tokens) - n + 1):
            window = long_tokens[start:start + n]
            if all(len(w) > 1 for w in window) and initials(window) == token:
                return True
    return False


def name_evidence(a_tokens, b_tokens):
    """Categorical name evidence for a pair: (level, detail).

    Levels are 'strong', 'moderate', 'weak', 'none'. A name made only of generic
    words ('District Hospital') can never be more than 'weak': it does not name
    a campus. These levels order candidates for review; they are not probabilities.
    """
    if not a_tokens or not b_tokens:
        return "none", "name_missing"
    a_core, b_core = core(a_tokens), core(b_tokens)
    if not a_core or not b_core:
        if a_tokens == b_tokens:
            return "weak", "generic_name_equal"
        return "none", "generic_name"
    a_set, b_set = set(a_core), set(b_core)
    shared = a_set & b_set
    if a_tokens == b_tokens:
        return "strong", "name_equal"
    if a_set == b_set:
        return "strong", "core_tokens_equal"
    if "".join(a_core) == "".join(b_core):
        return "strong", "core_equal_ignoring_spaces"
    jaccard = len(shared) / len(a_set | b_set)
    contained = len(shared) == min(len(a_set), len(b_set))
    ratio = SequenceMatcher(None, " ".join(a_core), " ".join(b_core), autojunk=False).ratio()
    if (contained and len(shared) >= 2) or jaccard >= 0.6 or ratio >= 0.88:
        return "moderate", "core_tokens_mostly_shared"
    if shared and (jaccard >= 0.34 or ratio >= 0.75):
        return "weak", "core_tokens_partly_shared"
    if ratio >= 0.8:
        return "weak", "spelling_similar"
    if acronym_hit(a_tokens, b_tokens) or acronym_hit(b_tokens, a_tokens):
        return "weak", "acronym_only"
    return "none", "no_name_evidence"
