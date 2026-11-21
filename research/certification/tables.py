"""Parse observed QPS views without inferring unseen certificate-register fields."""
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from .common import canonical, require, sha
from .fetch import public_url

LANDING = "https://qps.nhsrcindia.org/nqas-facility-list"
REGISTER = "https://nqas.nhsrcindia.org/facilities/list"
POLICY = "https://nhsrcindia.org/copyright-policy"
TERMS = "https://nhsrcindia.org/terms-and-conditions"
HEADERS = ["S.No.", "State", "District", "Name of Facility", "Department Assessed", "Validity From", "Validity date"]


def soup(raw):
    return BeautifulSoup(raw, "html.parser")


def discover(raw):
    page = soup(raw)
    endpoints = {}
    for form in page.select("form[action]"):
        action = urljoin(LANDING, form["action"])
        mode = next((m for m in ("full", "partial") if urlsplit(action).path == "/nqas-certification-" + m), None)
        if mode:
            require(form.get("method", "get").lower() == "get", "unexpected_filter_method")
            names = {field.get("name") for field in form.select("input,select")}
            require({"field_state1_value", "field_district1_value", "title"} <= names, "filter_fields_changed")
            endpoints[mode] = public_url(action + "?" + urlencode({
                "field_state1_value": "Rajasthan", "field_district1_value": "", "title": ""}))
    require(set(endpoints) == {"full", "partial"}, "full_partial_forms_missing")
    exports = [urljoin(LANDING, a["href"]) for a in page.select("a[href]")
               if any(term in (a["href"] + a.get_text()).lower() for term in (".csv", ".xlsx", "export", "download"))]
    return {"endpoints": endpoints, "public_export_links": sorted(set(exports)),
            "tabs": [a.get_text(" ", strip=True) for a in page.select(".quicktabs-tabs a")]}


def page_rows(raw, url, mode, expected_page=0):
    require(mode in {"full", "partial"}, "unknown_view_mode")
    document = soup(raw)
    view_id = "page_1" if mode == "full" else "page_2"
    views = document.select(".view-nqas.view-display-id-" + view_id)
    require(len(views) == 1, "expected_view_missing_or_duplicated")
    view = views[0]
    tables = view.select("table")
    if not tables:
        require(view.select_one(".view-empty") is not None, "table_missing_without_empty_marker")
        return [], None
    require(len(tables) == 1, "multiple_view_tables")
    table = tables[0]
    require([th.get_text(" ", strip=True) for th in table.select("th")] == HEADERS, "source_headers_changed")
    records = []
    for index, tr in enumerate(table.select("tbody tr"), 1):
        cells = tr.select("td")
        require(len(cells) == len(HEADERS), "source_row_width_changed")
        original = [cell.get_text() for cell in cells]
        display = [cell.get_text(" ", strip=True) for cell in cells]
        require(display[1].casefold() == "rajasthan", "state_filter_not_applied")
        require(display[0].isdigit() and display[3] and display[4], "row_identity_or_scope_missing")
        records.append({"mode": mode, "page": expected_page, "row_index": index,
                        "serial": display[0], "state": display[1], "district": display[2],
                        "facility": display[3], "scope": display[4], "valid_from_raw": display[5],
                        "valid_until_raw": display[6], "nin": None, "category": None,
                        "original_cells": original, "display_cells": display,
                        "source_url": url, "view_id": view_id})
    next_links = view.select('a[rel="next"], .pager__item--next a')
    hrefs = sorted(set(urljoin(url, link["href"]) for link in next_links))
    require(len(hrefs) <= 1, "ambiguous_next_page")
    next_url = hrefs[0] if hrefs else None
    if next_url:
        public_url(next_url)
        parsed, current = urlsplit(next_url), urlsplit(url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        require(parsed.hostname == current.hostname and parsed.path == current.path, "pagination_changed_source")
        require(query.get("field_state1_value") == ["Rajasthan"] and query.get("field_district1_value", [""]) == [""]
                and query.get("title", [""]) == [""], "pagination_changed_filter")
        require(query.get("page") == [str(expected_page + 1)], "pagination_not_sequential")
    return records, next_url


def row_signature(records):
    return sha(canonical([r["display_cells"] for r in records]))


def combined_url(page):
    values = {"field_state1_value": "Rajasthan", "field_district1_value": "", "title": ""}
    if page:
        values["page"] = str(page)
    return LANDING + "?" + urlencode(values)
