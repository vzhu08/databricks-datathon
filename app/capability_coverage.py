"""The capability coverage section of Find care: counts only, about the real directory.

For each kind of care, it says how many of the real directory's records mention it and for how many
of those an outside record supports the same care at the matched facility. It is separate from the
search: it names no facility, reads no patient or search state and is the same whatever is asked.

The counts are the measured figures published by the data owner (the `source` in
capability_coverage.json, kept beside this file). They are aggregates. A file that is missing, or
whose counts do not hold together, shows a plain "not available" line and never a number.

Two things this section must never be read as saying, so it says the opposite in words: a low or
zero share does not mean the care is not offered, and an outside match does not mean the care is
running today.
"""
import html
import json
from pathlib import Path

FILE = "capability_coverage.json"
SCHEMA = "capability-coverage-display.v1"
HEADING = "How often an outside source backs up the care a record mentions"
LABEL = "Real directory · counts only"
APART_DEMO = ("These counts are about the real directory, not the invented facilities the search on this page "
              "runs on. They name no facility.")
APART_REAL = "These counts are about the whole directory. They do not depend on the search above and name no facility."
MEANING = ("Each row takes the real records that mention one kind of care, and counts those where an outside "
           "record supports the same care at the matched facility. Records whose location is still unresolved "
           "stay in the count. One facility can appear in several rows.")
LIMITS = (
    "A low share or a zero means this comparison found few or no outside matches. It does not mean the care "
    "is not offered.",
    "An outside match supports what the record says. It does not confirm the care is running today.",
    "Radiotherapy counts centres licensed in the regulator's roster of 5 June 2026. Whether a machine is "
    "treating patients now is not known.",
    "Blood banking counts named directory entries. Current blood stock is not known.",
    "Some outside map listings may draw on the same original source as the directory, so they are not fully "
    "independent.",
)
UNAVAILABLE = "Capability coverage counts are not available in this copy of the app, so no number is shown."
MORE = "All other measured kinds of care, including those with no outside match"
STYLE = """
<style>
.cc { margin: 2rem 0 1rem; padding: 0.9rem 1.1rem 1rem; background: #ffffff; border: 1.5px solid #c3ced6;
  border-radius: 3px; color: #14283b; }
.cc-label { color: #4b6274; font-size: 0.95rem; }
.cc-head { margin-top: 0.15rem; font-size: 1.25rem; line-height: 1.3; font-weight: 700; }
.cc-quiet { margin-top: 0.35rem; color: #4b6274; font-size: 0.95rem; max-width: 78ch; }
.cc-text { margin-top: 0.5rem; max-width: 78ch; font-size: 1rem; }
.cc-scroll { overflow-x: auto; }
.cc table { margin-top: 0.6rem; border-collapse: collapse; font-size: 1rem; }
.cc th, .cc td { padding: 0.3rem 1.25rem 0.3rem 0; text-align: left; border-bottom: 1px solid #dbe2e7; }
.cc td.cc-n, .cc th.cc-n { text-align: right; font-variant-numeric: tabular-nums; }
.cc td.cc-n { white-space: nowrap; }
.cc th:last-child, .cc td:last-child { padding-right: 0; }
.cc details { margin-top: 0.8rem; }
.cc summary { cursor: pointer; font-weight: 600; }
.cc ul { margin: 0.6rem 0 0; padding-left: 1.3rem; max-width: 78ch; }
.cc li { margin-bottom: 0.3rem; }
.cc.cc-off { color: #4b6274; font-size: 0.95rem; }
@media (max-width: 640px) {
  .cc { padding: 0.8rem 0.8rem 0.9rem; }
  .cc table { font-size: 0.95rem; width: 100%; }
  .cc th, .cc td { padding-right: 0.6rem; }
}
</style>
"""


class Unavailable(Exception):
    """The counts cannot be shown: no file, or counts that do not hold together."""


def _row(row, directory_rows):
    name, supported, mentions, stated = (row["capability"], row["supported"], row["mentions"],
                                         row["stated_percent"])
    if not (isinstance(name, str) and name.strip() and len(name) <= 60):
        raise ValueError("not a capability name")
    for count in (supported, mentions):
        if type(count) is not int or count < 0:
            raise ValueError("not a count")
    if not 0 < mentions <= directory_rows or supported > mentions:
        raise ValueError("counts do not hold together")
    # The published share must be the share of the two counts, to the rounding it was published with.
    if not isinstance(stated, str) or abs(float(stated) - supported / mentions * 100) > 0.051:
        raise ValueError("share does not match its counts")
    return {"capability": name.strip(), "supported": supported, "mentions": mentions, "percent": stated}


def checked(found):
    """The rows this section shows, or ValueError / KeyError / TypeError when anything is off."""
    if found["schema"] != SCHEMA:
        raise ValueError("unknown schema")
    directory_rows = found["directory_rows"]
    if type(directory_rows) is not int or directory_rows <= 0:
        raise ValueError("not a count")
    headline = [_row(row, directory_rows) for row in found["headline"]]
    other = [_row(row, directory_rows) for row in found["other"]]
    names = [row["capability"] for row in headline + other]
    if not headline or len(set(names)) != len(names):
        raise ValueError("rows missing or repeated")
    return {"directory_rows": directory_rows, "headline": headline, "other": other}


def load(folder):
    try:
        return checked(json.loads((Path(folder) / FILE).read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise Unavailable(str(error)) from error


def _table(rows):
    body = "".join(
        f'<tr><td>{html.escape(row["capability"])}</td>'
        f'<td class="cc-n">{row["supported"]:,} of {row["mentions"]:,}</td>'
        f'<td class="cc-n">{html.escape(row["percent"])}%</td></tr>' for row in rows)
    return ('<div class="cc-scroll"><table><thead><tr><th>Kind of care</th>'
            '<th class="cc-n">Records with outside support</th><th class="cc-n">Share</th></tr></thead>'
            f"<tbody>{body}</tbody></table></div>")


def markup(found, demo):
    """The whole section as HTML. Every word outside the capability names is fixed text from this file."""
    return (f'<div class="cc"><div class="cc-label">{LABEL}</div>'
            f'<div class="cc-head" role="heading" aria-level="2">{HEADING}</div>'
            f'<div class="cc-quiet">{APART_DEMO if demo else APART_REAL}</div>'
            f'<div class="cc-text">{MEANING}</div>'
            + _table(found["headline"])
            + "<ul>" + "".join(f"<li>{line}</li>" for line in LIMITS) + "</ul>"
            + (f"<details><summary>{MORE} ({len(found['other'])})</summary>{_table(found['other'])}</details>"
               if found["other"] else "")
            + "</div>")


def render(st, folder, demo):
    """Draw the section. It reads the counts file and nothing else."""
    st.markdown(STYLE, unsafe_allow_html=True)
    try:
        found = load(folder)
    except Unavailable:
        st.markdown(f'<div class="cc cc-off">{UNAVAILABLE}</div>', unsafe_allow_html=True)
        return
    st.markdown(markup(found, demo), unsafe_allow_html=True)
