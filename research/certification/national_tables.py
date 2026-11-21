"""Observed national-register and map layouts; do not infer absent fields."""
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from .common import canonical, identity, require, sha
from .episodes import parse_date
from .fetch import public_url
from .tables import soup

LANDING = "https://qps.nhsrcindia.org/quality-certification/national-level-certificate"
MAP = "https://qps.nhsrcindia.org/nqas-map-report"
HEADERS = ["Sr No.", "Facility Name", "Certified", "Validity Till Date"]
MAP_HEADERS = ["State", "No. of DH", "No. of SDH", "No. of CHC", "No. of AAM-PHC", "No. of AAM-UPHC", "No. of AAM-SHC"]
VIEW = ".view-national-level-certificate.view-display-id-page_1"


def view(raw):
    views = soup(raw).select(VIEW)
    require(len(views) == 1, "national_view_missing_or_duplicated")
    return views[0]


def controls(raw):
    forms = view(raw).select("form[action]")
    require(len(forms) == 1, "national_filter_form_changed")
    form = forms[0]
    action = urljoin(LANDING, form["action"])
    require(action == LANDING and form.get("method", "get").lower() == "get", "national_filter_action_changed")
    state = form.select_one('select[name="field_state_target_id"]')
    status = form.select_one('select[name="field_certified_value"]')
    require(state is not None and status is not None, "national_filters_missing")
    options = [o for o in state.select("option") if o.get_text(" ", strip=True) == "Rajasthan"]
    require(len(options) == 1 and options[0].get("value"), "rajasthan_option_missing_or_duplicated")
    states = [o.get("value") for o in state.select("option[selected]")]
    labels = {o.get("value"): o.get_text(" ", strip=True) for o in status.select("option")}
    require("All" in labels, "all_status_option_missing")
    return {"action": action, "state_value": options[0]["value"], "status_options": labels,
            "selected_state": states, "selected_status": [o.get("value") for o in status.select("option[selected]")]}


def filtered_url(control, status="All"):
    require(status in control["status_options"], "unobserved_status_filter")
    return public_url(control["action"] + "?" + urlencode({"field_state_target_id": control["state_value"],
                                                          "field_certified_value": status}))


def updated_till(raw):
    values = [x.get_text(" ", strip=True) for x in soup(raw).select(".views-field-changed .field-content")]
    require(len(set(values)) <= 1, "conflicting_page_update_labels")
    return parse_date(values[0] if values else "")


def page(raw, url, expected_page=0, status="All"):
    control = controls(raw)
    require(control["selected_state"] == [control["state_value"]] and control["selected_status"] == [status],
            "national_selected_filter_not_applied")
    p = urlsplit(url)
    query = parse_qs(p.query, keep_blank_values=True)
    require(p.scheme == "https" and p.hostname == urlsplit(LANDING).hostname and p.path == urlsplit(LANDING).path,
            "national_page_changed_source")
    require(query.get("field_state_target_id") == [control["state_value"]]
            and query.get("field_certified_value") == [status], "national_url_filter_not_applied")
    require(query.get("page", [",0"]) == ["," + str(expected_page)], "national_page_not_sequential")
    container = view(raw)
    headers = container.select(".view-header")
    require(len(headers) == 1, "national_total_missing")
    total = re.fullmatch(r"Total Number of facility\s*:\s*([\d,]+)", headers[0].get_text(" ", strip=True))
    require(total is not None, "national_total_changed")
    advertised = int(total.group(1).replace(",", ""))
    tables = container.select("table")
    records = []
    if not tables:
        require(advertised == 0 and container.select_one(".view-empty") is not None, "national_missing_table")
    for table_number, table in enumerate(tables, 1):
        require(table.caption is not None and table.caption.get_text(" ", strip=True) == "Rajasthan", "national_state_caption_changed")
        require([th.get_text(" ", strip=True) for th in table.select("th")] == HEADERS, "national_headers_changed")
        for row_number, tr in enumerate(table.select("tbody tr"), 1):
            cells = tr.select("td")
            require(len(cells) == 4, "national_row_width_changed")
            original = [c.get_text() for c in cells]
            display = [c.get_text(" ", strip=True) for c in cells]
            require(display[0].isdigit(), "national_serial_missing")
            require(status == "All" or display[2] == status, "national_status_filter_not_applied")
            records.append({"serial": display[0], "facility": display[1] or None, "status_original": display[2],
                            "valid_until_raw": display[3], "state": "Rajasthan", "district": None, "nin": None,
                            "category": None, "department_scope": None, "valid_from_raw": None,
                            "original_cells": original, "display_cells": display,
                            "record_id": identity("nqas-national-record", display[1:]),
                            "page": expected_page, "table": table_number, "row": row_number, "source_url": url,
                            "locator": url + "#table=" + str(table_number) + ";tbody-row=" + str(row_number) + ";serial=" + display[0]})
    links = sorted({urljoin(url, a["href"]) for a in container.select('.pager__item--next a, a[rel="next"]')})
    require(len(links) <= 1, "national_ambiguous_next_link")
    next_url = links[0] if links else None
    if next_url:
        public_url(next_url)
        following = urlsplit(next_url)
        q = parse_qs(following.query, keep_blank_values=True)
        require(following.netloc == p.netloc and following.path == p.path, "national_next_changed_source")
        require(q == {"field_state_target_id": [control["state_value"]], "field_certified_value": [status],
                      "page": ["," + str(expected_page + 1)]}, "national_next_changed_filter_or_page")
    return {"rows": records, "next_url": next_url, "advertised_total": advertised, "updated_till": updated_till(raw),
            "signature": sha(canonical([r["display_cells"][1:] for r in records]))}


def map_summary(raw):
    tables = soup(raw).select(".view-map-report table")
    require(len(tables) == 1, "map_table_missing_or_duplicated")
    table = tables[0]
    require([h.get_text(" ", strip=True) for h in table.select("th")] == MAP_HEADERS, "map_headers_changed")
    rows = [[c.get_text(" ", strip=True) for c in r.select("td")] for r in table.select("tbody tr")]
    selected = [(i + 1, row) for i, row in enumerate(rows) if row and row[0] == "Rajasthan"]
    require(len(selected) == 1, "map_rajasthan_missing_or_duplicated")
    index, row = selected[0]
    require(len(row) == 7 and all(not v or v.isdigit() for v in row[1:]), "map_counts_invalid")
    counts = {k: int(v) if v else None for k, v in zip(MAP_HEADERS[1:], row[1:])}
    return {"url": MAP, "locator": MAP + "#tbody-row=" + str(index), "updated_till": updated_till(raw),
            "counts": counts, "sum_of_displayed_categories": sum(counts.values()) if all(v is not None for v in counts.values()) else None,
            "definition_observed": "NQAS Certified Facility Map Report; counts by printed facility category",
            "inclusion_of_conditionality": "not_stated", "deduplication_and_expiry_rules": "not_stated"}
