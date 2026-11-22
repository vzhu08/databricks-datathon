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

import loader  # noqa: E402
import walkthrough  # noqa: E402

STYLE = (HERE / "style.css").read_text(encoding="utf-8")
MARKS = {"met": "Reached", "partial": "Partly", "missing": "Not yet"}


def esc(text):
    return html.escape(str(text), quote=False)


def link(url, label):
    return (f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">'
            f"{esc(label)}</a>")


def host(url):
    return url.split("/")[2].removeprefix("www.")


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
         "Each new, independent piece of evidence moves a case one step down. Neither case clears the last "
         "step, which is why nothing is recommended.</p>"
         f"{ladder(view)}</section>")


def national(view):
    n = view["national"]
    show(f'<section class="fe-sec fe-case"><p class="fe-num">{esc(n["headline"])}</p>'
         '<h2>Across the national records</h2>'
         f'<p>{esc(n["line"])}</p><p class="fe-quiet">{esc(n["denominator"])}</p>'
         f'<p class="fe-src">Source: {link(n["source_url"], "replay of this count on GitHub")}</p></section>')


def trace(view):
    t = view["trace"]
    limits = "".join(f"<li>{esc(line)}</li>" for line in t["limits"])
    show(f'<section class="fe-sec fe-case"><p class="fe-num">{esc(t["headline"])}</p>'
         '<h2>Virtue Foundation records checked against the map</h2>'
         f'<p>{esc(t["line"])}</p><h3>What that does not show</h3><ul>{limits}</ul>'
         f'<p class="fe-quiet">Counts only. Individual facility records stay private to the team.</p>'
         f'<p class="fe-src">Source: {link(t["source_url"], "frozen source trace on GitHub")} · Map data © '
         f'{link(t["credit"]["url"], t["credit"]["text"])}</p></section>')


def public(view):
    p = view["public"]
    facts = "".join(
        f'<li><span class="fe-when">{esc(f["as_of"])}</span><span class="fe-fact">{esc(f["statement"])}</span>'
        f'<span class="fe-scope">Scope: {esc(f["scope"])} · {link(f["source_url"], f["source_label"])} '
        f'({esc(host(f["source_url"]))})</span></li>' for f in p["facts"])
    refs = "".join(f'<li>{link(r["url"], r["label"])}' + (f' · {esc(r["note"])}' if r.get("note") else "")
                   + "</li>" for r in p["references"])
    unknown = "".join(f"<li>{esc(u)}</li>" for u in p["unknown"])
    show(f'<section class="fe-sec fe-case"><h2>{esc(p["title"])}</h2>'
         f'<p class="fe-flag">{esc(p["link_line"])}</p>'
         f'<h3>What the sources say, and when</h3><ol class="fe-facts">{facts}</ol>'
         + (f"<h3>Reference only</h3><ul>{refs}</ul>" if refs else "")
         + f"<h3>Still unknown</h3><ul>{unknown}</ul></section>")


def policies(view):
    rows = view["result"]["policies"]
    if not rows:
        return
    body = "".join(f'<tr><th scope="row">{esc(r["policy"])}</th><td>{esc(r["result"])}</td></tr>' for r in rows)
    show('<section class="fe-sec"><h2>How each ranking rule handles this evidence</h2>'
         f'<table class="fe-policies"><tbody>{body}</tbody></table></section>')


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
if view["synthetic"]:
    show('<p class="fe-synthetic" role="note"><strong>Synthetic test file.</strong> Every figure below is '
         "invented for testing the screen. It is not the real edition.</p>")
show(f'<p class="fe-edition">{"Test edition" if view["synthetic"] else "Real data"}: {esc(view["edition"])}. '
     "Fingerprint checked before anything is shown.</p>")
answer(view)
why(view)
national(view)
trace(view)
public(view)
policies(view)
show('<footer class="fe-foot">No scores, ranks, travel times, free slots or percentages appear here, because '
     "none can be computed from this evidence. Release of this page is the team lead's decision.</footer>")
