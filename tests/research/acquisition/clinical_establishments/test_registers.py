"""Synthetic source layouts, permissions, provenance and downstream regressions."""
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest

from research.acquisition.clinical_establishments.inventory import inventory, portal_inventory
from research.acquisition.clinical_establishments.parser import SEEDS, classify_row, extract, table_rows
from research.acquisition.clinical_establishments.producer import build, compile_rows, scoped_path
from research.acquisition.clinical_establishments.fetch import fetch_one
from research.acquisition.common import canonical, digest, write_json

STAMP = "2026-01-01T00:00:00Z"
URL = "https://registry.example.invalid/synthetic.pdf"
PROFILE = dict(state="Example State", registration_namespace="example:clinical-register",
    column_counts=[8], header_rows={"1": 1, "2": 1},
    columns=dict(serial=0, registration_id=1, name=2, address=3, state=4, district=5,
                 service_wording=6, pin=7))


def synthetic_pdf(path):
    doc = pymupdf.open()
    for page_no, service in enumerate(["Dialysis referral only", "Multispecialty"], 1):
        page = doc.new_page(width=900, height=220)
        xs = [20, 60, 150, 260, 370, 490, 600, 780, 880]
        ys = [30, 70, 110]
        for x in xs:
            page.draw_line((x, ys[0]), (x, ys[-1]))
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))
        header = ["S.No", "Registration", "Name", "Address", "State", "District", "Service", "PIN"]
        values = [str(page_no), "REG-7", "Example MRI Clinic", "1 Fictional Road", "Example State",
                  "Example District", service, "001234"]
        for y, row in zip(ys, [header, values]):
            for x, value in zip(xs, row):
                page.insert_text((x + 3, y + 17), value, fontsize=7)
    doc.save(path)
    doc.close()


def fixtures(tmp_path):
    raw = tmp_path / "source.pdf"
    synthetic_pdf(raw)
    sha = digest(raw.read_bytes())
    capture = dict(url=URL, status="fetched", retrieved_at=STAMP, sha256=sha, raw_path="source.pdf")
    rights = dict(status="cleared", sha256=sha, url=URL, intended_use="private_acquisition_and_team_review",
                  basis="Author-created synthetic fixture", basis_uri="https://example.invalid/permission",
                  reviewer="fixture-author", reviewed_at=STAMP)
    metadata = dict(publisher="Synthetic Publisher", source_family="synthetic-registry",
                    source_key="synthetic-register", layout_reviewer="fixture-author", layout_reviewed_at=STAMP,
                    published_date=None, effective_date=None, source_date_text="Data as on: January 2026")
    write_json(tmp_path / "capture.json", capture)
    manifest = dict(documents=[dict(capture_receipt="capture.json", rights=rights,
                                   profile=PROFILE, metadata=metadata)])
    return capture, rights, metadata, manifest


def test_inventory_counts_not_empty_icons_or_notice():
    raw = b'''<h2>Not adopted</h2><table><tr><th>S.No</th><th>State</th><th>Data Pdf</th></tr>
    <tr><td>1</td><td>Example West</td><td><a href="one.pdf">Part 1</a>
    <a href="two.pdf">Part 2</a><a href="unrelated.pdf"><img alt="PDF"/></a></td></tr>
    <tr><td>2</td><td>Example Notice</td><td>No file provided.</td></tr></table>
    <h2>Adopted</h2><table><tr><th>S.No</th><th>State</th><th>Data Pdf</th></tr>
    <tr><td>1</td><td>Example East</td><td><a href="one.pdf"> </a><a href="/portal">Open</a></td></tr></table>'''
    result = inventory(raw)
    assert result["summary"]["printed_entries"] == 3
    assert result["summary"]["linked_jurisdictions"] == 2
    assert result["summary"]["substantive_links"] == 3
    assert result["summary"]["empty_anchors"] == 2
    assert result["jurisdictions"][1]["notice"] == "No file provided."
    assert result["links"][2]["kind"] == "portal"


def test_inventory_fails_on_shifted_row():
    with pytest.raises(ValueError, match="row shape"):
        inventory(b'<table><tr><th>State</th><th>Data Pdf</th></tr><tr><td>Incomplete</td></tr></table>')


def test_pdf_reconciles_rows_and_excludes_contacts(tmp_path):
    fixtures(tmp_path)
    result = extract(tmp_path / "source.pdf", PROFILE)
    assert result["summary"]["parsed_rows"] == 2
    assert result["summary"]["physical_rows"] == 4
    assert result["summary"]["rejected_physical_rows"] == 2
    assert not result["summary"]["missing_serials"]
    assert result["rows"][0]["registration_id"] == "REG-7"
    assert result["rows"][0]["registration_namespace"] == "example:clinical-register"
    assert result["rows"][0]["locator"] == "PDF page 1, table 1, physical row 2 (1-based)"


def test_scope_and_service_negation_remain_unlinked_inconclusive(tmp_path):
    _, _, _, manifest = fixtures(tmp_path)
    outputs = build(tmp_path, manifest)
    batch, sidecar = outputs["batch.json"], outputs["identity-sidecar.json"]
    assert len(batch["external_facilities"]) == 2  # repeated registration is not a merged campus
    assert len({r["external_facility_id"] for r in batch["external_facilities"]}) == 2
    assert len(batch["facility_evidence"]) == 1
    evidence = batch["facility_evidence"][0]
    assert evidence["service"] == "dialysis" and evidence["polarity"] == "inconclusive"
    assert evidence["excerpt"] == "Dialysis referral only"
    assert evidence["facility_id"] is None and batch["facility_matches"] == []
    assert evidence["effective_date"] is None and evidence["temporal_status"] == "undated"
    assert all(r["pin"] == "001234" for r in batch["external_facilities"])
    assert sidecar[0]["source_date_text"] == "Data as on: January 2026"


@pytest.mark.parametrize("change", [dict(status="permission_required"), dict(sha256="0" * 64),
    dict(url="https://other.example.invalid/file.pdf"), dict(intended_use="public_publication"),
    dict(basis_uri=None), dict(reviewer=None), dict(reviewed_at="2026-01-01")])
def test_clearance_cannot_be_assumed_or_transferred(tmp_path, change):
    capture, rights, metadata, _ = fixtures(tmp_path)
    rights.update(change)
    with pytest.raises(ValueError):
        compile_rows([], capture, metadata, rights)


def test_permission_hold_emits_no_source_rows(tmp_path):
    _, _, _, manifest = fixtures(tmp_path)
    manifest["documents"][0]["rights"] = dict(status="permission_required")
    outputs = build(tmp_path, manifest)
    assert outputs["batch.json"]["external_facilities"] == []
    assert outputs["batch.json"]["source_snapshots"] == []
    assert outputs["release-report.json"]["hold_reasons"] == {"permission_required": 1}


def test_changed_raw_bytes_fail_even_on_hold(tmp_path):
    _, _, _, manifest = fixtures(tmp_path)
    manifest["documents"][0]["rights"] = dict(status="permission_required")
    (tmp_path / "source.pdf").write_bytes(b"changed")
    with pytest.raises(ValueError, match="capture receipt"):
        build(tmp_path, manifest)


def test_duplicate_import_and_offline_rebuild_are_identical(tmp_path):
    _, _, _, manifest = fixtures(tmp_path)
    first, second = build(tmp_path, manifest), build(tmp_path, manifest)
    assert canonical(first) == canonical(second)
    from merge import plan_merge
    batch = first["batch.json"]
    assert plan_merge([batch, batch], [])["batch"] == plan_merge([batch], [])["batch"]


def test_byte_alias_not_an_independent_source(tmp_path):
    _, _, _, manifest = fixtures(tmp_path)
    manifest["documents"].append(copy.deepcopy(manifest["documents"][0]))
    outputs = build(tmp_path, manifest)
    assert len(outputs["batch.json"]["source_snapshots"]) == 1
    assert outputs["release-report.json"]["hold_reasons"] == {"byte_identical_source_alias": 1}


def test_missing_name_bad_pin_and_registration_preserved(tmp_path):
    capture, rights, metadata, _ = fixtures(tmp_path)
    row, reject = classify_row(["1", "REG-001", None, "Unit 123456", "Example State", "District", "MRI planned", "12345"], PROFILE, "row 1")
    batch, sidecar = compile_rows([row], capture, metadata, rights)
    external = batch["external_facilities"][0]
    assert external["name_original"] is None and external["pin"] is None
    assert {"missing_name", "invalid_source_pin"} <= set(external["quality_flags"])
    assert sidecar[0]["pin"] == "12345" and external["source_record_id"] == "REG-001"
    assert batch["facility_evidence"][0]["polarity"] == "inconclusive"


def test_seeds_never_treat_serial_as_registration():
    cells = ["9", "Example District", "Synthetic Hospital", "Private", "Imaginary Street"] + ["omitted"] * 5 + ["Multi Specialty", "Allopathy"]
    row, reject = classify_row(cells, SEEDS["rajasthan"], "page 2 row 3")
    assert row["serial"] == "9" and row["registration_id"] is None
    assert row["district"] == "Example District"
    assert "omitted" not in canonical(row).decode()


def test_split_tables_join_only_identical_row_bounds():
    def table(x0, x1, width, y=10):
        return SimpleNamespace(bbox=(x0, y, x1, 20), col_count=width,
            rows=[SimpleNamespace(bbox=(x0,y,x1,20))], extract=lambda:[[str(i) for i in range(width)]])
    left, right = table(0,10,11), table(20,30,2)
    joined = table_rows([left,right], SEEDS["telangana"])[0][1][0]
    assert len(joined) == 15 and joined[11:13] == [None,None]
    with pytest.raises(ValueError, match="boundaries"):
        table_rows([left,table(20,30,2,y=12)], SEEDS["telangana"])


def test_unknown_shape_is_a_rejected_physical_row():
    row, reject = classify_row(["1", "Incomplete"], PROFILE, "page 4 row 1")
    assert row is None and reject["reason"] == "unreviewed_column_layout"


def test_unreconciled_layout_withholds_whole_source(tmp_path):
    _, _, _, manifest = fixtures(tmp_path)
    bad_profile = copy.deepcopy(PROFILE)
    bad_profile["column_counts"] = [9]
    manifest["documents"][0]["profile"] = bad_profile
    result = build(tmp_path, manifest)
    assert result["batch.json"]["external_facilities"] == []
    assert result["release-report.json"]["holds"][0]["reason"] == "unreconciled_extraction"


def test_snapshot_profile_hash_mismatch_fails(tmp_path):
    fixtures(tmp_path)
    with pytest.raises(ValueError, match="another raw snapshot"):
        extract(tmp_path / "source.pdf", {**PROFILE, "sha256": "0" * 64})


def test_header_mapping_cannot_silently_drop_numbered_facility(tmp_path):
    fixtures(tmp_path)
    with pytest.raises(ValueError, match="Numeric serial"):
        extract(tmp_path / "source.pdf", {**PROFILE, "header_rows": {"1": 2, "2": 1}})


def test_registration_namespace_and_original_state_remain_distinct():
    row, _ = classify_row(["1", "REG-1", "Clinic", "Street", "TypoState", "District", "General", None], PROFILE, "row 2")
    assert row["state"] == "TypoState"
    assert row["registration_namespace"] == "example:clinical-register"
    assert "source_state_differs_from_index_jurisdiction" in row["quality_flags"]


def test_cached_receipt_preserves_first_timestamp_without_network(tmp_path, monkeypatch):
    capture, _, _, _ = fixtures(tmp_path)
    write_json(tmp_path / "receipts" / (digest(URL.encode()) + ".json"), capture)
    monkeypatch.setattr("requests.get", lambda *a, **k: pytest.fail("Unexpected network read"))
    assert fetch_one(URL, tmp_path)["retrieved_at"] == STAMP


@pytest.mark.parametrize("relative", ["../outside", "/tmp/outside"])
def test_package_path_escape_fails(tmp_path, relative):
    with pytest.raises(ValueError):
        scoped_path(tmp_path, relative)


def test_portal_links_keep_repetition_and_hash_check(tmp_path):
    raw = b'<a href="part.xlsx">Sheet</a><a href="part.xlsx">ZIP</a><a href="old.pdf"> </a><form></form>'
    (tmp_path / "page.html").write_bytes(raw)
    a = dict(links=[dict(kind="portal", jurisdiction_printed="Example", url=URL, status="fetched",
                        http_status=200, sha256=digest(raw), raw_path="page.html")])
    p = portal_inventory(a, tmp_path)[0]
    assert len(p["children"]) == 3 and p["unique_child_urls"] == 2
    assert p["substantive_unique_child_urls"] == 1 and p["form_count"] == 1
    (tmp_path / "page.html").write_bytes(b"changed")
    with pytest.raises(ValueError):
        portal_inventory(a, tmp_path)
