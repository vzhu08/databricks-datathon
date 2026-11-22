"""Count specialists by type on archived doctor and department pages, without keeping names.

For each first-party domain, pick up to six archived pages whose path looks like a doctor,
team or department page (`/our-doctors`, `/specialists`, `/departments/nephrology`, ...).
On each page, a line that starts a "Dr. <Name>" entry is tied to a specialty when that line
or the next three lines (up to the next "Dr." line) mention it:

  nephrology        nephrologist, nephrology                  (supports dialysis)
  radiology         radiologist, radiology                    (supports MRI)
  orthopaedics      orthopaedic surgeon, joint replacement    (supports trauma care)
  neurosurgery      neurosurgeon, neuro surgery               (supports trauma care)
  emergency_trauma  emergency medicine/physician, trauma surgeon, MD/DNB emergency, casualty
                    medical officer                           (supports trauma care)

Privacy: names exist only in memory, as a key to count each doctor once per domain. The
output keeps counts per domain and specialty plus the page URL and capture date of the page
with the most matches. No names, qualifications, photos or contact details are stored, and
any context shown for a hand check has names masked as "Dr. ▇".

A count is evidence that the site listed such a doctor on the capture date. It is not a
service "yes" (a nephrologist can work without a dialysis unit) and not a staffing figure
(visiting consultants and old pages are counted the same way).
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from research.website_evidence.extract import ARTICLE_PATH, THIN_TEXT, visible_text

SPECIALTIES = {
    "nephrology": re.compile(r"\bnephrolog", re.I),
    "radiology": re.compile(r"\bradiolog", re.I),
    "orthopaedics": re.compile(r"\borthop(a)?edic|\borthop(a)?edist|\bjoint replacement surgeon", re.I),
    "neurosurgery": re.compile(r"\bneuro[\s-]?surg", re.I),
    "emergency_trauma": re.compile(
        r"\bemergency (medicine|physician)|\btrauma surg|\bcasualty medical officer|\b(M\.?D\.?|DNB)\s*\(?\s*emergency",
        re.I,
    ),
}
SUPPORTS = {"nephrology": "dialysis", "radiology": "mri", "orthopaedics": "trauma_care",
            "neurosurgery": "trauma_care", "emergency_trauma": "trauma_care"}

DOCTOR = re.compile(r"\bDr\.?\s+([A-Z][a-zA-Z]+(?:\s+[A-Z]\.?)*(?:\s+[A-Z][a-zA-Z]+)?)")
DOC_PATH = re.compile(
    r"(doctor|our-team|team|specialist|consultant|faculty|physician|surgeon|expert|staff|department|speciali"
    r"|nephro|kidney|dialysis|radiolog|imaging|ortho|neuro|emergency|trauma|casualty)",
    re.I,
)
PEOPLE_PATH = re.compile(r"(doctor|our-team|/team|specialist|consultant|faculty|physician)", re.I)
WINDOW = 4  # the "Dr." line and up to three lines after it, stopping at the next "Dr." line


def _path(url: str) -> str:
    try:
        return urlsplit(url).path.rstrip("/") or "/"
    except ValueError:
        return url


def pick_doctor_pages(captures: list[dict], limit: int = 6) -> list[dict]:
    """Doctor and team pages first, then department pages; shortest path first; no blog pages."""
    html = [c for c in captures if c["status"] == "200" and "html" in (c["mime"] or "")
            and DOC_PATH.search(_path(c["url"])) and not ARTICLE_PATH.search(c["url"])]
    html.sort(key=lambda c: (0 if PEOPLE_PATH.search(_path(c["url"])) else 1, len(_path(c["url"]))))
    seen, out = set(), []
    for c in html:
        p = _path(c["url"])
        if p not in seen and len(out) < limit:
            seen.add(p)
            out.append(c)
    return out


def mask(text: str) -> str:
    return DOCTOR.sub("Dr. ▇", text)


def _keys(text: str):
    """Yield (doctor key, specialties) per "Dr." line. Keys stay in memory only."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        names = [m.group(1).lower() for m in DOCTOR.finditer(line)]
        if not names:
            continue
        window = [line]
        for nxt in lines[i + 1:i + WINDOW]:
            if DOCTOR.search(nxt):
                break  # the next doctor's entry starts
            window.append(nxt)
        window = " ".join(window)[:400]
        found = [k for k, rx in SPECIALTIES.items() if rx.search(window)]
        for n in names:
            yield n, found, window


def count_page(html: str) -> dict:
    """Counts for one page: {"thin", "doctors", "specialties": {name: count}, "context": {name: masked}}."""
    _, text = visible_text(html)
    if len(text) < THIN_TEXT:
        return {"thin": True, "doctors": 0, "specialties": {}, "context": {}}
    everyone, by_spec, context = set(), {}, {}
    for key, found, window in _keys(text):
        everyone.add(key)
        for k in found:
            by_spec.setdefault(k, set()).add(key)
            context.setdefault(k, mask(window)[:220])
    return {"thin": False, "doctors": len(everyone),
            "specialties": {k: len(v) for k, v in by_spec.items()}, "context": context}


def count_domain(pages: list[tuple[dict, str]]) -> dict:
    """Aggregate several (capture, html) pages of one domain; each doctor counted once per specialty.

    Returns {"doctor_pages_read", "doctors", "specialties": {name: {"count", "url", "captured"}}}.
    The url/captured pair is the page with the most matches for that specialty.
    """
    everyone, by_spec, best = set(), {}, {}
    read = 0
    for capture, html in pages:
        _, text = visible_text(html)
        read += 1
        if len(text) < THIN_TEXT:
            continue
        page_spec = {}
        for key, found, _ in _keys(text):
            everyone.add(key)
            for k in found:
                by_spec.setdefault(k, set()).add(key)
                page_spec.setdefault(k, set()).add(key)
        for k, s in page_spec.items():
            if k not in best or len(s) > best[k][0]:
                best[k] = (len(s), capture["url"], capture["timestamp"])
    return {
        "doctor_pages_read": read,
        "doctors": len(everyone),
        "specialties": {k: {"count": len(v), "url": best[k][1], "captured": best[k][2]}
                        for k, v in sorted(by_spec.items())},
    }
