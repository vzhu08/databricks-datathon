"""Facility evidence walkthrough: the judges' real-data view (#252).

    FACILITY_EVIDENCE_DISPLAY=<path to the frozen display.json> streamlit run app/facility_evidence_demo/app.py

The path is a local file or a /Volumes/... path read through the Databricks SDK. The file must be the pinned
edition (loader.PINNED_SHA256); anything else shows the data-unavailable state and nothing in its place.
"""
import html
import sys
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.append(str(HERE))

import area  # noqa: E402
import loader  # noqa: E402
import walkthrough  # noqa: E402

STYLE = (HERE / "style.css").read_text(encoding="utf-8")
MARKS = {"met": "Reached", "partial": "Partly", "missing": "Not yet"}


def esc(text):
    return html.escape(str(text), quote=False)


def cite(src):
    """A source from walkthrough.source: a link with its host or access note, or plain text."""
    if not src["url"]:
        return esc(src["label"])
    note = f' <span class="fe-host">({esc(src["note"])})</span>' if src["note"] else ""
    return (f'<a href="{html.escape(src["url"], quote=True)}" target="_blank" rel="noopener noreferrer">'
            f"{esc(src['label'])}</a>{note}")


def show(markup):
    st.markdown(markup, unsafe_allow_html=True)


def ladder(view):
    cases = [("Virtue Foundation records", view["trace"]), (view["public"]["title"], view["public"])]
    head = "".join(f'<th scope="col">{esc(name)}</th>' for name, _ in cases)
    rows = []
    for number, (key, title, meaning) in enumerate(view["rungs"], start=1):
        cells = []
        for _, case in cases:
            state = case["rungs"][key]
            word = MARKS[state]
            note = case["rung_notes"].get(key, "")
            cells.append(f'<td class="fe-{state}"><span class="fe-mark" aria-hidden="true"></span>'
                         f'<span class="fe-state">{word}</span>'
                         f'{f"<span class=fe-note>{esc(note)}</span>" if note else ""}</td>')
        rows.append(f'<tr><th scope="row"><span class="fe-step">{number}</span>{esc(title)}'
                    f'<span class="fe-meaning">{esc(meaning)}</span></th>{"".join(cells)}</tr>')
    rows.append('<tr class="fe-gate"><th scope="row">Eligible to recommend</th>'
                + '<td>No</td>' * len(cases) + "</tr>")
    return (f'<table class="fe-ladder"><thead><tr><th scope="col">Evidence step</th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def answer(view):
    r = view["result"]
    show(f'<section class="fe-answer" aria-labelledby="fe-answer-h">'
         f'<p class="fe-kicker">The answer</p>'
         f'<h2 id="fe-answer-h">{esc(r["headline"])}</h2>'
         f'<p class="fe-lead">{esc(r["line"])}</p>'
         f'<div class="fe-next"><span>The one check that would change this</span>{esc(r["next_check"])}</div>'
         f"</section>")


def why(view):
    show('<section class="fe-sec"><h2>Why: how far the evidence gets</h2>'
         '<p class="fe-intro">A facility becomes a destination only after its evidence clears all four steps. '
         "Each piece of evidence addresses a specific step, and a later step counts only with its own evidence. "
         "Neither case clears the last "
         "step, which is why nothing is recommended.</p>"
         f"{ladder(view)}</section>")


def items(lines):
    return "".join(f"<li>{esc(line)}</li>" for line in lines)


def national(view):
    n = view["national"]
    quiet = n["denominator"] + (" " + n["accuracy"] if n["accuracy"] else "")
    show(f'<section class="fe-sec fe-case"><p class="fe-num">{esc(n["headline"])}</p>'
         '<h2>Across the national records</h2>'
         f'<p>{esc(n["line"])}</p><p class="fe-quiet">{esc(quiet)}</p>'
         f'<p class="fe-src">Source: {cite(n["source"])}</p></section>')


def trace(view):
    t = view["trace"]
    show(f'<section class="fe-sec fe-case"><p class="fe-num">{esc(t["headline"])}</p>'
         '<h2>Virtue Foundation records checked against the map</h2>'
         f'<p>{esc(t["line"])}</p><h3>What that does not show</h3><ul>{items(t["limits"])}</ul>'
         f'<p class="fe-quiet">{esc(t["grain"])}. Map editions: {esc(", ".join(t["snapshots"]))}. '
         "Individual facility records stay private to the team.</p>"
         f'<p class="fe-src">Source: {cite(t["source"])} · Map data © '
         '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">'
         "OpenStreetMap contributors</a></p></section>")


def public(view):
    p = view["public"]
    facts = "".join(
        f'<li><span class="fe-when">{esc(f["when"])}</span><span class="fe-fact">{esc(f["what"])}</span>'
        f'<span class="fe-scope">{esc(f["scope"])} · {cite(f["source"])}</span></li>' for f in p["facts"])
    show(f'<section class="fe-sec fe-case"><h2>{esc(p["title"])}</h2>'
         f'<p class="fe-flag">{esc(p["link_line"])}</p>'
         f'<p>Buildings named: {esc(", ".join(p["buildings"]))}. Operator lineage: {esc(p["lineage"])}.</p>'
         f'<h3>What the sources say, and when</h3><ol class="fe-facts">{facts}</ol>'
         f'<p class="fe-src">Reference only: {cite(p["reference"])}</p>'
         f'<h3>Still unknown</h3><ul>{items(p["unknown"])}</ul></section>')


def area_view(loaded_area):
    """Where the records place facilities: counts by precision, loaded and checked on its own."""
    head = ('<section class="fe-sec fe-case fe-area" aria-labelledby="fe-area-h"><p class="fe-kicker">Area view</p>'
            '<h2 id="fe-area-h">Where the records place facilities</h2>')
    if loaded_area["status"] != "ok":
        show(f'{head}<div class="fe-down fe-down-small" role="status"><h3>Area data unavailable</h3>'
             f"<p>{esc(loaded_area['reason'])}</p><p>Nothing is shown in its place.</p></div></section>")
        return
    a = area.build(loaded_area["data"])
    label = "Synthetic test file. Every figure in this section is invented. " if loaded_area["synthetic"] else ""
    rows = []
    for row in a["rows"]:
        width = max(row["share"] * 100, 0.4 if row["count"] else 0)
        note = f'<span class="fe-note">{esc(row["note"])}</span>' if row["note"] else ""
        rows.append(
            f'<li class="fe-bar fe-bar-{row["key"]}" title="{esc(row["label"])}: {row["count"]:,} of {a["total"]:,}">'
            f'<span class="fe-bar-label">{esc(row["label"])}<span class="fe-meaning">{esc(row["meaning"])}</span>{note}</span>'
            f'<span class="fe-bar-track" aria-hidden="true"><span class="fe-bar-fill" style="width:{width:.2f}%"></span></span>'
            f'<span class="fe-bar-value">{row["count"]:,}</span></li>')
    show(f'{head}{f"<p class=fe-synthetic role=note>{esc(label)}</p>" if label else ""}'
         f'<p class="fe-num">{esc(a["headline"])}</p>'
         f'<p>{esc(a["line"])}</p>'
         f'<ul class="fe-bars" aria-label="Original records by how precisely they are located">{"".join(rows)}</ul>'
         f'<p class="fe-quiet">Out of {esc(a["ids"])} Each record is counted once, at the most specific level '
         "its evidence supports. This view shows no facility pin, travel time, distance order, receiving capacity "
         "or service claim, because an area is not a destination.</p>"
         "<h3>What the private search can do</h3>"
         "<p>Inside the team's private records, the search returns each record's supported area and its type. "
         "That per-record view is not cleared for this page, so only the totals appear here.</p>"
         '<h3>What a richer view needs</h3><ul>'
         "<li>Area names or boundaries cleared for this audience, so each area can be shown by name or on a map.</li>"
         "<li>Reviewed building evidence for a record before it moves from an area to a building.</li>"
         "<li>Exact membership of the area-only records, which stays with the data owners.</li></ul>"
         f'<p class="fe-src">Source: {cite(a["source"])}</p></section>')


def policies(view):
    d = view["decision"]
    body = "".join(f'<tr><th scope="row">{esc(name)}</th><td>{"<br>".join(esc(line) for line in lines)}</td></tr>'
                   for name, lines in d["policies"])
    show('<section class="fe-sec"><h2>How each ranking rule handles this evidence</h2>'
         f'<table class="fe-policies"><tbody>{body}</tbody></table>'
         f'<p class="fe-quiet">{esc(d["evaluation"])}</p></section>')


st.set_page_config(page_title="Facility evidence", layout="centered")
show(f"<style>{STYLE}</style>")
loaded = loader.load()
show('<header class="fe-top"><p class="fe-kicker">Facility evidence walkthrough</p>'
     "<h1>Can we send a patient to these facilities yet?</h1></header>")
if loaded["status"] != "ok":
    show('<section class="fe-down" role="alert"><h2>Data unavailable</h2>'
         f"<p>{esc(loaded['reason'])}</p>"
         "<p>Nothing is shown in its place. This screen never substitutes invented or example data.</p>"
         "</section>")
    st.stop()

view = walkthrough.build(loaded["data"])
if loaded["synthetic"]:
    show('<p class="fe-synthetic" role="note"><strong>Synthetic test file.</strong> Every figure below is '
         "invented for testing the screen. It is not the real edition.</p>")
show(f'<p class="fe-edition">{"Test edition" if loaded["synthetic"] else "Real data"}: {esc(view["edition"])}. '
     "Fingerprint checked before anything is shown.</p>")
answer(view)
why(view)
national(view)
trace(view)
public(view)
policies(view)
area_view(area.load())
show(f'<footer class="fe-foot">Cleared audience: {esc(view["audience"])}. No scores, ranks, travel times, free slots or percentages appear here, because '
     "none can be computed from this evidence. Release of this page is the team lead's decision.</footer>")
