"""The notice a public copy of the app shows above every screen.

A copy is public when the setting `FIND_CARE_PUBLIC_SOURCE` holds the https address of the project's
source and write-up. The team's signed-in deployments do not set it, so they are unchanged: no notice,
and Check symptoms opens first.

The notice tells a first-time visitor what the app is, where to start, which parts are real and where
the source is. It reads no patient or search state and makes no request.
"""
import html
import os

SETTING = "FIND_CARE_PUBLIC_SOURCE"
LABEL = "Public demo · CMU × Databricks Datathon, November 2026"
WHAT = ("Find Care helps a community health worker in India find a facility whose own published evidence "
        "supports the care a patient needs, and says what is still unknown.")
START = "Start on Find care and press Search public sources."
REAL = ("The two Pune hospitals and the national counts are real. Every campus, patient and travel time is "
        "simulated, and symptom assessment is off.")
LINK = "Source code and write-up"
STYLE = """
<style>
.pd { margin: 0 0 1.25rem; padding: 0.8rem 1.1rem 0.9rem; background: #ffffff; border: 1.5px solid #14283b;
  border-radius: 3px; color: #14283b; }
.pd-label { color: #4b6274; font-size: 0.95rem; }
.pd-what { margin-top: 0.15rem; font-size: 1.0625rem; line-height: 1.45; max-width: 110ch; }
.pd-line { margin-top: 0.35rem; font-size: 1rem; line-height: 1.45; max-width: 110ch; }
.pd a { color: #14283b; font-weight: 600; white-space: nowrap; }
</style>
"""


def source_url(environ=None):
    """The source address when this copy is public, otherwise an empty string. Anything other than a
    plain https address is treated as unset, so a mistyped setting never changes a deployment."""
    environ = os.environ if environ is None else environ
    address = str(environ.get(SETTING) or "").strip()
    if address.startswith("https://") and not any(mark in address for mark in '"<> '):
        return address
    return ""


def markup(address):
    """The notice as HTML. Every word is escaped."""
    safe = lambda text: html.escape(str(text), quote=False)  # noqa: E731
    link = (f' <a href="{html.escape(address, quote=True)}" target="_blank" rel="noopener noreferrer">'
            f"{safe(LINK)}</a>")
    return (f'<div class="pd" data-public-demo="shown"><div class="pd-label">{safe(LABEL)}</div>'
            f'<div class="pd-what">{safe(WHAT)}</div>'
            f'<div class="pd-line"><strong>{safe(START)}</strong> {safe(REAL)}{link}</div></div>')


def render(st, environ=None):
    """Draw the notice on a public copy and report whether this copy is public."""
    address = source_url(environ)
    if not address:
        return False
    st.markdown(STYLE + markup(address), unsafe_allow_html=True)
    return True
