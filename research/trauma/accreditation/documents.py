"""Extract verifiable text from preserved public documents."""

import re
from datetime import datetime


def compact(text):
    """Normalize extraction whitespace while retaining the source wording."""
    return " ".join(text.split())


def document_pages(path, kind):
    if kind in {"certificate", "institution_pdf"}:
        from pypdf import PdfReader

        return [page.extract_text(extraction_mode="layout") for page in PdfReader(path).pages]
    if kind == "institution":
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(path.read_bytes(), "html.parser")
        for node in soup.select("script, style, template, noscript, [hidden], [aria-hidden=true]"):
            node.decompose()
        return [soup.get_text(" ", strip=True)]
    raise ValueError(f"Unsupported document kind {kind}")


CERT_ID = re.compile(r"Certificate\s+No\.?\s*:?\s*([A-Z]+-\d{4}-\d+)", re.I)
DATE_LABELS = {
    "first_certification_date": r"Date of First (?:Accreditation|Certification)",
    "effective_date": r"Valid\s+from",
    "valid_until": r"Valid\s+(?:thru|through|until|to|upto|up to)",
}
DATE_TEXT = r"([A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4}|\d{4}-\d{2}-\d{2})"


def parse_certificate(page_text):
    text = compact(page_text)
    if not re.search(r"scope of accreditation|accredited scope", text, re.I):
        return None
    numbers = {match.upper() for match in CERT_ID.findall(text)}
    if len(numbers) != 1:
        raise ValueError("Certificate scope page requires exactly one labelled certificate number")
    result = {"certificate_number": numbers.pop()}
    for field, label in DATE_LABELS.items():
        matches = re.findall(rf"{label}\s*:?\s*{DATE_TEXT}", text, re.I)
        dates = {_parse_date(match) for match in matches}
        if len(dates) > 1:
            raise ValueError(f"Conflicting certificate dates for {field}")
        result[field] = next(iter(dates), None)
    if result["effective_date"] and result["valid_until"]:
        if result["valid_until"] < result["effective_date"]:
            raise ValueError("Certificate expiry precedes its start date")
    return result


def _parse_date(text):
    formats = ("%B %d %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y", "%Y-%m-%d")
    for date_format in formats:
        try:
            return datetime.strptime(text.replace(",", ""), date_format).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized certificate date: {text}")


TRAUMA = re.compile(r"\b(?:polytrauma|trauma\s+(?:cent(?:re|er)s?|care|units?|services?|surger\w*|team|patients?|management|resuscitation)|(?:manag\w*|treat\w*)\s+\w*\s*trauma)\b", re.I)
REFERRAL = re.compile(r"\b(?:refer(?:s|red|ral|rals|ring)?\s+(?:all\s+|patients\s+|trauma\s+|cases\s+)*(?:out|to)|transfer(?:s|red)?\s+(?:patients\s+|cases\s+)?to|off[- ]?site|referral[- ]only)\b", re.I)
PLANNED = re.compile(r"\b(?:planned|proposed|sanctioned|upcoming|will (?:open|offer|establish)|under construction|yet to (?:open|start))\b", re.I)
NEGATED = re.compile(r"\b(?:not|no|neither|never|without|exclud\w*|unavailable|suspended|closed|doesn['’]t|isn['’]t)\b", re.I)
LIMITED = re.compile(r"\b(?:outpatient|training|workshops?|simulation|research|ambulance|first aid|dental|psychological)\b|\bOPD\b", re.I)


def scope_type(excerpt):
    text = compact(excerpt)
    if not TRAUMA.search(text):
        return "general_emergency" if re.search(r"\bemergency\b", text, re.I) else "unresolved_interpretation"
    if NEGATED.search(text):
        return "negated"
    if PLANNED.search(text):
        return "planned"
    if REFERRAL.search(text):
        return "referral"
    if LIMITED.search(text):
        return "unresolved_interpretation"
    return "explicit_trauma"
