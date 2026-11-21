import re

EVIDENCE_FIELDS = ("procedures", "capabilities", "equipment", "description")

# Earlier patterns win within the same strength. Field priority breaks ties.
SERVICE_TERMS = {
    "dialysis": (
        (r"\b(?:(?:ha?emo|peritoneal[\s-]+)dialysis)\b", r"\bdialysis\b"),
        (r"\bnephrolog(?:y|ist(?:s)?)\b", r"\brenal[\s-]+(?:clinic|care|medicine)\b"),
    ),
    "mri": (
        (r"\bmagnetic[\s-]+resonance[\s-]+imaging\b", r"\bm\.?r\.?i\b"),
        (r"\bradiolog(?:y|ist(?:s)?)\b", r"\bdiagnostic[\s-]+imaging\b"),
    ),
    "trauma_care": (
        (r"\btrauma[\s-]+(?:care|cent(?:re|er)s?|units?|surger(?:y|ies)|services?|teams?)\b",),
        (r"\bemergency[\s-]+(?:departments?|rooms?|medicine|units?|care|services?)\b",
         r"\b(?:casualty[\s-]+department|a\s*&\s*e)\b", r"\b(?-i:ER)\b"),
    ),
}

MATCHERS = {
    service: tuple(tuple(re.compile(term, re.IGNORECASE) for term in terms) for terms in groups)
    for service, groups in SERVICE_TERMS.items()
}

SENTENCES = re.compile(r"(?<=[!?;])[^\S\n]*|(?<!\b[A-Za-z]\.)(?<=\.)\s+|\n\s*\n|\n(?=\s*[-*•]\s+)")
CONTRAST = re.compile(r"\s*(?:,\s*)?\b(?:but|however|whereas|while|although)\b[:,]?\s+", re.I)
CONJUNCTION = re.compile(r"\s*,\s*(?:and\s+)?|\s+and\s+", re.I)
PREDICATE = re.compile(
    r"\b(?:offer(?:s|ed|ing)?|provid(?:es?|ed|ing)|perform(?:s|ed|ing)?|operat(?:es?|ed|ing)|"
    r"has|have|available|unavailable|planned|proposed|"
    r"refer(?:s|red|ring)?|no|not)\b", re.I,
)
INDEPENDENT_VERB = re.compile(
    r"(?:(?:we|it|they|the hospital|the clinic)\s+)?(?:offers?|provides?|performs?|operates?|"
    r"refer(?:s|red|ring)?|no)\b", re.I,
)
EXCLUDED = re.compile(
    r"\b(?:unavailable|not\s+(?!(?:only|required|needed)\b)|no\s+(?!(?:appointment|referral|charge|fee)\b)|"
    r"without|lack(?:s|ing)?|discontinued|suspended|closed|retired|paused|on\s+hold|"
    r"off[\s-]?site\s+only|only\s+(?:available\s+)?off[\s-]?site|"
    r"non[\s-]+operational|out\s+of\s+service|"
    r"out\s+of\s+order|broken|(?:does|do|did|is|are|was|were|can|has|have)n['’]t|cannot|"
    r"planned|planning|plans|propos(?:ed|ing|al)|future|upcoming|coming\s+soon|"
    r"under\s+(?:construction|installation|repair|maintenance)|pending\s+installation|"
    r"expected\s+(?:next|to\s+be)|"
    r"to\s+be\s+(?:installed|opened|commissioned)|scheduled\s+for\s+installation|"
    r"will\s+(?:begin|start)\s+(?:offering|providing|performing)|"
    r"will\s+(?:offer|provide|open|install|be\s+(?:available|offered|provided|installed)))\b",
    re.I,
)
REFERRAL_OUT = re.compile(
    r"\b(?:refers?|referring|referred|referrals?\s+(?:to|for|only)|refer[\s-]+out|"
    r"(?:sent|transferred)\s+(?:elsewhere|to\s+(?:another|an?\s+outside)))\b", re.I,
)
INBOUND_REFERRAL = re.compile(
    r"\b(?:accepts?|receives?)\s+(?:incoming\s+)?referrals?\b|\breferred\s+(?:here|to\s+(?:us|our|this)\b)", re.I,
)
OUTBOUND_DESTINATION = re.compile(r"\b(?:elsewhere|off[\s-]?site|outside|another)\b", re.I)


def _clauses(text):
    for sentence in SENTENCES.split(text):
        for clause in CONTRAST.split(sentence):
            # Split independent statements without breaking lists of services sharing a predicate.
            start = 0
            for separator in CONJUNCTION.finditer(clause):
                left = clause[start:separator.start()]
                right = clause[separator.end():]
                next_separator = CONJUNCTION.search(right)
                next_phrase = right[:next_separator.start()] if next_separator else right
                if INDEPENDENT_VERB.match(right) or (PREDICATE.search(left) and PREDICATE.search(next_phrase)):
                    yield left.strip()
                    start = separator.end()
            yield clause[start:].strip()


def best_evidence(facility, service):
    """Return the strongest surviving evidence as (strength, excerpt, field)."""
    strongest = None
    best_priority = (2, 0, 0)
    for field_priority, field in enumerate(EVIDENCE_FIELDS):
        value = facility.get(field)
        entries = value if isinstance(value, (list, tuple)) else (value,)
        for entry in entries:
            if not isinstance(entry, str):
                continue
            for clause in _clauses(entry):
                if not clause or EXCLUDED.search(clause):
                    continue
                if REFERRAL_OUT.search(clause) and (
                    not INBOUND_REFERRAL.search(clause) or OUTBOUND_DESTINATION.search(clause)
                ):
                    continue
                for strength, matchers in enumerate(MATCHERS[service]):
                    for term_priority, matcher in enumerate(matchers):
                        priority = (strength, term_priority, field_priority)
                        if priority < best_priority and matcher.search(clause):
                            best_priority = priority
                            strongest = (("direct", "indirect")[strength], clause, field)
    return strongest
