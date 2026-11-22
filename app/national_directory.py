"""The national directory section of Find care: counts only, about the real Virtue Foundation records.

It says for how many of the directory's records outside evidence supports where the named facility
is. It is separate from the search: it names no facility, reads no patient or search state and is the
same whatever is asked below it.

The counts come from one small summary file that the operator packages beside the app as
`facility-area-display.json`. It is not kept in Git. The bytes are pinned by SHA-256 to the reviewed
edition (the same pin as `research/matching/facility_area_display.py`, which builds the file), so a
missing, changed or older file shows a plain "not available" line and never a number.
"""
import hashlib
import html
import json
from pathlib import Path

FILE = "facility-area-display.json"
DISPLAY_SHA256 = "dfb08860a7b8dfb2eeb4cb42741879deac26a599bb379db3d9f6f9baaa24f914"
MAX_BYTES = 64 * 1024
# Each record falls in exactly one of these, in this order. Labels follow the data handoff for the edition.
TIERS = (
    ("previously_findable", "Already covered before this rule"),
    ("registry_or_operator", "Newly identified in an official registry area"),
    ("agreeing_points", "Added by agreeing coordinates under 1 km"),
    ("map_name_and_area", "Added by a named map listing in the same written area"),
    ("unresolved", "Still open"),
)
OPEN = "unresolved"
OPEN_ROW = '<tr class="nd-open">'
HEADING = "National directory"
LABEL = "Real Virtue Foundation records · counts only"
APART_DEMO = ("These counts are about the real directory, not the six invented facilities the search below "
              "runs on. They name no facility.")
APART_REAL = "These counts are about the whole directory. They do not depend on the search below and name no facility."
UNAVAILABLE = ("Coverage counts are not available in this copy of the app. The counts file is not packaged "
               "here, or it is not the reviewed edition, so no number is shown.")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
STYLE = """
<style>
.nd { margin: 0 0 1.5rem; padding: 0.9rem 1.1rem 1rem; background: #ffffff; border: 1.5px solid #c3ced6;
  border-radius: 3px; color: #14283b; }
.nd-label { color: #4b6274; font-size: 0.95rem; }
.nd-head { margin-top: 0.15rem; font-size: 1.25rem; line-height: 1.3; font-weight: 700; }
.nd-quiet { margin-top: 0.35rem; color: #4b6274; font-size: 0.95rem; max-width: 110ch; }
.nd details { margin-top: 0.6rem; }
.nd summary { cursor: pointer; font-weight: 600; }
.nd table { margin-top: 0.6rem; border-collapse: collapse; font-size: 1rem; }
.nd th, .nd td { padding: 0.3rem 1.25rem 0.3rem 0; text-align: left; border-bottom: 1px solid #dbe2e7; }
.nd td.nd-n, .nd th.nd-n { text-align: right; font-variant-numeric: tabular-nums; }
.nd tr.nd-open td { font-weight: 700; }
.nd ul { margin: 0.6rem 0 0; padding-left: 1.3rem; max-width: 78ch; }
.nd li { margin-bottom: 0.3rem; }
.nd a { color: #14283b; }
.nd.nd-off { color: #4b6274; font-size: 0.95rem; }
</style>
"""


class Unavailable(Exception):
    """The summary cannot be shown: no file, not the reviewed bytes, or counts that do not add up."""


def read_summary(raw):
    """The reviewed summary, or Unavailable. The pin is checked before a single byte is parsed."""
    if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != DISPLAY_SHA256:
        raise Unavailable("not the reviewed edition")
    try:
        return checked(json.loads(raw))
    except (ValueError, KeyError, TypeError) as error:
        raise Unavailable("the counts do not reconcile") from error


def whole(value):
    if type(value) is not int or value < 0:
        raise ValueError("not a count")
    return value


def checked(summary):
    """The same reconciliation the builder applies: every record in one tier, covered = all but open."""
    tiers = {key: whole(summary["coverage_tiers"][key]) for key, _ in TIERS}
    total, covered = whole(summary["population"]), whole(summary["covered"])
    if total == 0 or sum(tiers.values()) != total or covered != total - tiers[OPEN]:
        raise ValueError("coverage does not reconcile")
    for key in ("registry_or_operator", "agreeing_points", "registry_or_agreeing_points",
                "nearby_only_possible_shared_origins"):
        whole(summary["overlapping_evidence"][key])
    for key in ("as_of", "source", "method", "limitations"):
        if not isinstance(summary[key], str) or not summary[key].strip():
            raise ValueError("missing wording")
    return summary


def load(folder):
    """Read the packaged file from the app's own folder. Nothing else is looked for or fetched."""
    path = Path(folder) / FILE
    try:
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            raise Unavailable("no packaged file")
        raw = path.read_bytes()
    except OSError as error:
        raise Unavailable("the file could not be read") from error
    return read_summary(raw)


def number(value):
    return f"{value:,}"


def share(part, total):
    return f"{100 * part / total:.1f}%"


def day(as_of):
    """2026-11-22 as 22 November 2026. Anything else is shown as written."""
    try:
        year, month, date = (int(piece) for piece in as_of.split("-"))
        return f"{date} {MONTHS[month - 1]} {year}"
    except (ValueError, IndexError):
        return as_of


def view(summary):
    """The words and numbers of the section, with no markup."""
    total, covered = summary["population"], summary["covered"]
    tiers, seen = summary["coverage_tiers"], summary["overlapping_evidence"]
    return {
        "headline": f"{number(covered)} of {number(total)} records ({share(covered, total)}) have outside "
                    "evidence for where the named facility is.",
        "open": f"{number(tiers[OPEN])} are still open.",
        "as_of": f"as of {day(summary['as_of'])}",
        "rows": [(label, number(tiers[key]), share(tiers[key], total), key == OPEN) for key, label in TIERS],
        "evidence": [
            f"{number(seen['registry_or_operator'])} records have official directory support in the written "
            "PIN, locality or landmark area.",
            f"{number(seen['agreeing_points'])} have agreeing coordinates under 1 km. For "
            f"{number(seen['nearby_only_possible_shared_origins'])} of those, the only agreeing points may "
            "share their origin with the Virtue Foundation record, so they are weaker support.",
            f"{number(seen['registry_or_agreeing_points'])} have at least one of those two kinds of evidence.",
        ],
        "method": summary["method"],
        "limits": summary["limitations"],
        "source": summary["source"],
        "attribution": summary.get("osm_attribution_url", ""),
    }


def markup(found, demo):
    """The section as HTML. Every word from the file is escaped; the one link must be an https address."""
    safe = lambda text: html.escape(str(text), quote=False)  # noqa: E731
    # Built without a quote or backslash inside an f-string expression: the hosted Python is older than 3.12.
    rows = "".join((OPEN_ROW if still_open else "<tr>") + f"<td>{safe(label)}</td>"
                   f'<td class="nd-n">{count}</td><td class="nd-n">{part}</td></tr>'
                   for label, count, part, still_open in found["rows"])
    link = found["attribution"]
    credit = (f' <a href="{html.escape(link, quote=True)}" target="_blank" rel="noopener noreferrer">'
              "OpenStreetMap copyright and licence</a>." if link.startswith("https://") else "")
    return (f'<div class="nd" data-national="shown"><div class="nd-label">{safe(LABEL)} · {safe(found["as_of"])}'
            f'</div><div class="nd-head" role="heading" aria-level="2">{safe(HEADING)}: {safe(found["headline"])} '
            f'{safe(found["open"])}</div>'
            f'<div class="nd-quiet">{safe(found["limits"])} {safe(APART_DEMO if demo else APART_REAL)}</div>'
            "<details><summary>How the records were counted</summary>"
            '<table><thead><tr><th>Each record counted once</th><th class="nd-n">Records</th>'
            f'<th class="nd-n">Share</th></tr></thead><tbody>{rows}</tbody></table>'
            f"<ul>{''.join(f'<li>{safe(line)}</li>' for line in found['evidence'])}</ul>"
            f'<div class="nd-quiet"><strong>Method.</strong> {safe(found["method"])}</div>'
            f'<div class="nd-quiet"><strong>Sources.</strong> {safe(found["source"])}{credit}</div>'
            "</details></div>")


def render(st, folder, demo):
    """Draw the section, or one quiet line when the reviewed counts are not packaged with this copy."""
    try:
        found = view(load(folder))
    except Unavailable:
        st.markdown(f'{STYLE}<div class="nd nd-off" data-national="unavailable"><strong>{html.escape(HEADING)}.</strong> '
                    f"{html.escape(UNAVAILABLE)}</div>", unsafe_allow_html=True)
        return
    st.markdown(STYLE + markup(found, demo), unsafe_allow_html=True)
