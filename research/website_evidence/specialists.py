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
import argparse
import collections
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

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
# A doctor entry is skipped for specialty counting when it is not a medical specialist's own entry:
# dental, ENT and AYUSH doctors (their pages often sit next to a department word), menus and forms
# (three or more department names in one entry), and blog bylines (a date or "Comments").
NOT_THIS_DOCTOR = re.compile(
    r"\b(BDS|MDS|ENT|BAMS|BHMS|BPT|MPT|B\.P\.Th|M\.P\.Th)\b|\b(dental|dentist|orthodont\w*|endodont\w*|prosthodont\w*"
    r"|periodont\w*|maxillofacial|otorhinolaryng\w*|otolaryng\w*|ayurved\w*|homoeopath\w*|homeopath\w*|physiotherap\w*)",
    re.I,
)
DEPARTMENT = re.compile(
    r"\b(cardiolog|neurolog|nephrolog|urolog|gastroenterolog|pulmonolog|endocrinolog|oncolog|dermatolog"
    r"|paediatric|pediatric|gyn(a)?ecolog|obstetric|orthop(a)?edic|radiolog|psychiatr|ophthalmolog|general medicine"
    r"|general surgery|neuro ?surg|rheumatolog|intensivist|emergency|trauma|casualty|joint replacement)\w*",
    re.I,
)
FORM_OR_BYLINE = re.compile(
    r"\b(select (a )?(department|doctor|speciality)|book an appointment|your name|submit|send message"
    r"|\d+ comments?|posted (by|on)|(january|february|march|april|may|june|july|august|september|october"
    r"|november|december) \d{1,2}, 20\d\d)\b",
    re.I,
)
NEAR_NAME = 150  # in a long paragraph, the specialty must follow the name within this many characters


def _family(word: str) -> str:
    w = word.lower()
    for k, rx in SPECIALTIES.items():
        if rx.search(w):
            return k
    if w.startswith("neurolog"):
        return "neurology"
    if w.startswith(("emergency", "trauma", "casualty", "intensivist")):
        return "emergency_trauma"
    if w.startswith("joint replacement"):
        return "orthopaedics"
    return w[:6]


def first_specialty(window: str) -> str | None:
    """The specialty family named first after the doctor's name (a later "Department of X" is a heading)."""
    m = DEPARTMENT.search(window)
    return _family(m.group(0)) if m else None


def entry_is_specialist(window: str) -> bool:
    if NOT_THIS_DOCTOR.search(window) or FORM_OR_BYLINE.search(window):
        return False
    return len({_family(m.group(0)) for m in DEPARTMENT.finditer(window)}) < 3


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


# Wider than DOCTOR, for masking only: initials without spaces and up to four name words.
_MASK = re.compile(r"\b(Dr|Prof|Mr|Mrs|Ms)\.?\s*(?:[A-Z]\.\s*)*[A-Z][a-zA-Z]*\.?(?:\s+(?:[A-Z]\.|[A-Z][a-zA-Z]+)){0,4}")
_PROFILE_PARENT = re.compile(r"^(doctors?|team|team-member|our-doctors?|our-team|specialists?|consultants?|faculty"
                             r"|find-a-doctor|cmsms_doctor|doctors_detail|doctor-profile|team_member|profile)$", re.I)
_LIST_WORDS = re.compile(r"^(page|index|list|all|\d+|[a-z]+\.(php|html?|aspx?))$", re.I)


def mask(text: str) -> str:
    return _MASK.sub(lambda m: m.group(1) + ". ▇", text)


def redact_url(url: str) -> str:
    """Remove a doctor's name from a profile URL ("/doctor/dr-a-b/" -> "/doctor/[name removed]/")."""
    parts = urlsplit(url)
    segs = parts.path.split("/")
    for i, seg in enumerate(segs):
        if not seg:
            continue
        named = re.match(r"(dr|prof)[-_.]|doctor[-_](?!list|search|and|appointment|profile|details|opd)", seg, re.I) or re.search(r"[-_]dr[-_]", seg, re.I)
        after_profile = i > 0 and _PROFILE_PARENT.match(segs[i - 1] or "") and not _LIST_WORDS.match(seg)
        if named or after_profile:
            segs[i] = "[name removed]"
    query = re.sub(r"(slug|name|doctor|id)=[^&]*", r"\1=[removed]", parts.query, flags=re.I)
    return urlunsplit((parts.scheme, parts.netloc, "/".join(segs), query, ""))


def _found(window: str) -> list[str]:
    """Specialties credited to one doctor entry: the first one named, plus neurosurgery after neurology."""
    if not entry_is_specialist(window):
        return []
    first = first_specialty(window)
    hits = [k for k, rx in SPECIALTIES.items() if rx.search(window)]
    if first == "neurology":
        return [k for k in hits if k == "neurosurgery"]
    return [k for k in hits if k == first]


def _keys(text: str):
    """Yield (doctor key, specialties) per "Dr." line. Keys stay in memory only."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        names = [m.group(1).lower() for m in DOCTOR.finditer(line)]
        if not names:
            continue
        if len(line) > 200:  # a paragraph, not a doctor card: only the text right after the name counts
            m = DOCTOR.search(line)
            window = line[m.start():m.start() + NEAR_NAME]
            found = _found(window)
            for n in names:
                yield n, found, window
            continue
        window = [line]
        for nxt in lines[i + 1:i + WINDOW]:
            if DOCTOR.search(nxt):
                break  # the next doctor's entry starts
            window.append(nxt)
        window = " ".join(window)[:400]
        found = _found(window)
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
        "specialties": {k: {"count": len(v), "url": redact_url(best[k][1]), "captured": best[k][2]}
                        for k, v in sorted(by_spec.items())},
    }


def records(rows: list[dict], domains: dict, crawl: str) -> tuple[list[dict], dict]:
    """Row-level records (one per row x specialty) and a coverage report.

    domains: {domain: count_domain() output, plus "html_capture": bool}. Domains missing from it
    had no readable capture.
    """
    use = collections.Counter(d for r in rows for d in r["domains"])
    out, state, by_spec = [], collections.Counter(), collections.Counter()
    for r in rows:
        ds = [domains[d] | {"domain": d} for d in r["domains"] if d in domains]
        if not ds:
            state["no_html_capture"] += 1
            continue
        if not any(d["doctor_pages_read"] for d in ds):
            state["no_doctor_page"] += 1
            continue
        if not any(d["doctors"] for d in ds):
            state["doctor_page_without_named_doctor"] += 1
            continue
        state["named_doctors_listed"] += 1
        found = {}
        for d in ds:
            for k, v in d["specialties"].items():
                if k not in found or v["count"] > found[k][1]["count"]:
                    found[k] = (d["domain"], v)
        if found:
            state["at_least_one_target_specialist"] += 1
        for k, (domain, v) in sorted(found.items()):
            by_spec[k] += 1
            ts = v["captured"]
            out.append({
                "facility_id": r["facility_id"], "specialty": k, "supports_service": SUPPORTS[k],
                "kind": "dated_specialist_count", "status_effect": "none_until_reviewed",
                "doctors_listed": v["count"], "domain": domain, "domain_shared_by_rows": use[domain],
                "campus_attribution": "needs_review" if use[domain] > 1 else "single_row_domain",
                "source": {"archive": "Common Crawl", "crawl": crawl, "url": redact_url(v["url"]),
                           "captured_at": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}T{ts[8:10]}:{ts[10:12]}:{ts[12:14]}Z"},
            })
    report = {"crawl": crawl, "rows_in_sample": len(rows), "rows_by_state": dict(state),
              "rows_by_specialty": dict(by_spec)}
    return out, report


def load_run(path: Path) -> dict:
    """Read the browser run: domain|doctor_pages|read|thin|doctors|spec:count:timestamp:url;..."""
    out = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        d, pages, read, thin, doctors, spec = line.split("|", 5)
        sp = {}
        for e in filter(None, spec.split(";")):
            k, c, ts, u = e.split(":", 3)
            sp[k] = {"count": int(c), "captured": ts, "url": redact_url(u)}
        out[d] = {"doctor_pages_read": int(read), "doctors": int(doctors), "specialties": sp}
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description="Row-level specialist counts from a browser run (no names).")
    p.add_argument("--rows", required=True, type=Path)
    p.add_argument("--run", required=True, type=Path)
    p.add_argument("--crawl", required=True)
    p.add_argument("--out", required=True, type=Path)
    a = p.parse_args(argv)
    recs, report = records(json.loads(a.rows.read_text()), load_run(a.run), a.crawl)
    a.out.mkdir(parents=True, exist_ok=True)
    with (a.out / "specialists.jsonl").open("w") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (a.out / "specialists_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
