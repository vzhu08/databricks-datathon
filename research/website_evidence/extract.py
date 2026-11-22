"""Find dated, quotable service mentions in archived first-party web pages.

The input is one archived HTML page plus its capture timestamp. The output is
one record per service (dialysis, MRI, trauma care) with the sentence that
mentions it. A mention is evidence that the page said this on the capture
date. It is not a reviewed "yes" under docs/implementation/SERVICE_STATUS.md:
the campus attribution and a named reviewer are still required.

Standard library only, so the same code runs in Databricks, CI or a laptop.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

SERVICES = {
    "dialysis": re.compile(r"\b(h(a)?emo[- ]?dialysis|dialysis|CAPD|peritoneal dialysis)\b", re.I),
    "mri": re.compile(r"\b(MRI|M\.R\.I\.?|magnetic resonance)(?![a-z])"),
    "trauma_care": re.compile(
        r"\b(trauma\s*(care|cent(re|er)|unit|ward|team|services?|ICU|surgery)|polytrauma"
        r"|accident\s*(and|&)\s*emergency|emergency\s*(and|&)\s*trauma|level\s*(I{1,3}|[123])\s*trauma)\b",
        re.I,
    ),
}

# Wording that can turn a mention into "not here", "not yet" or "elsewhere".
QUALIFIERS = re.compile(
    r"\b(not available|not provide\w*|no (dialysis|mri)|do not|don't|refer(red|s)? (to|out)|coming soon"
    r"|upcoming|proposed|planning|plan to|will feature|will be (started|available|launched)|under construction|outsourc\w*"
    r"|tie[- ]?up|should be confirmed)\b",
    re.I,
)

# Pages that explain a condition rather than describe the facility.
ARTICLE_PATH = re.compile(r"(/blogs?[/_-]|/post\.php|/tag/|/category/|/news/|/articles?/|/faqs?/|/\d{4}/\d{2}/|/testimonial)", re.I)
# Wording that ties a mention to this facility: "we", "our", "in-house", "equipped", "24x7", "1.5 Tesla" ...
ONSITE = re.compile(
    r"\b(we|our|us|in[- ]house|available|equipped|offer(s|ing)?|provid(e|es|ing)|facilit(y|ies)|unit|"
    r"cent(re|er)|department|24\s*[x×*/]\s*7|24[- ]hours?|round[- ]the[- ]clock|machines?|beds?|tesla|slice)\b",
    re.I,
)
# Patient-education wording: "your doctor may order an MRI", "tests like CT or MRI".
EDUCATION = re.compile(
    r"\b(may (order|use|be|need)|your doctor|doctors? (may|will|might|can)|is a (painless|procedure|test)"
    r"|is the process|what is|tests? (like|such as)|diagnosis (involves|typically|includes)|imaging tests"
    r"|may be ordered|is required to|is very good)\b",
    re.I,
)

BLOCK_TAGS = {
    "p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "td", "tr", "th", "br",
    "section", "article", "header", "footer", "nav", "a", "span", "table", "dd", "dt", "option",
}
SKIP_TAGS = {"script", "style", "noscript", "svg", "iframe", "template", "head"}
THIN_TEXT = 300  # fewer visible characters than this: likely a bot check or a JavaScript shell
MAX_QUOTE = 280


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.title: list[str] = []
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True
        if tag in SKIP_TAGS:
            self.skip += 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in SKIP_TAGS and self.skip:
            self.skip -= 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)
        if not self.skip:
            self.parts.append(data)


def visible_text(html: str) -> tuple[str, str]:
    """Return (title, visible text with one block per line)."""
    parser = _Text()
    parser.feed(html)
    parser.close()
    text = "".join(parser.parts)
    lines = (re.sub(r"\s+", " ", line).strip() for line in text.split("\n"))
    return re.sub(r"\s+", " ", "".join(parser.title)).strip()[:150], "\n".join(line for line in lines if line)


def sentences(text: str) -> list[str]:
    out = []
    for line in text.split("\n"):
        out.extend(s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", line) if len(s.strip()) >= 3)
    return out


def _rank(sentence: str) -> tuple:
    # Prefer facility wording over patient education, full sentences over menu items,
    # unqualified over qualified, then longer.
    return (not EDUCATION.search(sentence), bool(ONSITE.search(sentence)), len(sentence) >= 40,
            not QUALIFIERS.search(sentence), -abs(len(sentence) - 160))


GLUE = {"the", "and", "of", "with", "is", "are", "we", "our", "to", "for", "in", "at", "by", "has", "have", "a", "an"}


def looks_like_menu(quote: str) -> bool:
    """A run of capitalised menu labels ("Department Select a Department Cardiology Nephrology ...")."""
    if re.search(r"\bSelect (a )?(Department|Speciality|Specialty|Location)\b", quote):
        return True
    words = re.findall(r"[A-Za-z][A-Za-z&-]*", quote)
    if len(words) <= 12:
        return False
    glue = sum(w.lower() in GLUE for w in words)
    return glue / len(words) < 0.08 and sum(w[0].isupper() for w in words) / len(words) > 0.55


def strength(quote: str, url: str = "", qualified: bool = False) -> str:
    """direct: a full sentence tying the service to this facility; listed: a short menu/list item; weak: other."""
    if ARTICLE_PATH.search(url) or EDUCATION.search(quote) or qualified or looks_like_menu(quote):
        return "weak"
    if len(quote) < 40:
        return "listed" if len(quote.split()) <= 6 else "weak"
    return "direct" if ONSITE.search(quote) and len(quote.split()) <= 60 else "weak"


def mentions(html: str, url: str = "") -> dict:
    """Service mentions on one page.

    Returns {"title", "chars", "thin", "services": {service: {"quote", "qualified", "count"}}}.
    """
    title, text = visible_text(html)
    found: dict[str, list[str]] = {}
    for s in sentences(text):
        for service, pattern in SERVICES.items():
            if pattern.search(s):
                found.setdefault(service, []).append(s[:MAX_QUOTE])
    services = {}
    for service, quotes in found.items():
        best = max(quotes, key=_rank)
        qualified = bool(QUALIFIERS.search(best))
        services[service] = {"quote": best, "qualified": qualified, "count": len(quotes),
                             "strength": strength(best, url, qualified)}
    thin = len(text) < THIN_TEXT
    return {"title": title, "chars": len(text), "thin": thin, "services": {} if thin else services}
