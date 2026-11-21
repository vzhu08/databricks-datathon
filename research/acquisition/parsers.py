"""Strict input envelopes; conservative row normalization with raw locators."""
from __future__ import annotations

import json
import math
import re
import stat
import unicodedata
import zipfile
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlsplit

from shapely.errors import GEOSException
from shapely.geometry import shape

from .common import AcquisitionError, canonical, digest, envelope, public_url, review

MAX_UNPACKED = 512 * 1024 * 1024


def strict_json(data):
    def reject(value):
        raise AcquisitionError("nonstandard_json_constant")
    try:
        return json.loads(data, parse_constant=reject)
    except (ValueError, UnicodeError) as exc:
        raise AcquisitionError("invalid_json") from exc


def load_features(path, source):
    """Never extract archive entries; reject unsafe paths, links, CRC errors, bombs."""
    path = Path(path)
    metadata = None
    member = None
    if source == "osm":
        try:
            with zipfile.ZipFile(path) as archive:
                infos = archive.infolist()
                if len(infos) > 100 or sum(i.file_size for i in infos) > MAX_UNPACKED:
                    raise AcquisitionError("archive_size_limit")
                names = [i.filename for i in infos]
                if len(names) != len(set(names)):
                    raise AcquisitionError("duplicate_archive_members")
                for info in infos:
                    name = info.filename
                    parts = PurePosixPath(name).parts
                    if (info.orig_filename != name or name.startswith("/") or ".." in parts or "\\" in name or ":" in name
                            or stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1):
                        raise AcquisitionError("unsafe_archive_path_or_type")
                candidates = [n for n in names if n.lower().endswith(".geojson")]
                if len(candidates) != 1:
                    raise AcquisitionError("expected_one_geojson_member")
                if archive.testzip() is not None:
                    raise AcquisitionError("archive_crc_error")
                member = candidates[0]
                data = strict_json(archive.read(member))
                if "metadata.json" in names:
                    metadata = strict_json(archive.read("metadata.json"))
        except (zipfile.BadZipFile, EOFError, RuntimeError, OSError) as exc:
            raise AcquisitionError("invalid_archive") from exc
    else:
        if path.stat().st_size > MAX_UNPACKED:
            raise AcquisitionError("input_size_limit")
        data = strict_json(path.read_bytes())
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
        raise AcquisitionError("expected_feature_collection")
    features = data["features"]
    if not features:
        raise AcquisitionError("empty_feature_collection")
    if data.get("crs") and "CRS84" not in json.dumps(data["crs"]) and "4326" not in json.dumps(data["crs"]):
        raise AcquisitionError("unsupported_crs")
    for feature in features:
        if (not isinstance(feature, dict) or feature.get("type") != "Feature"
                or not isinstance(feature.get("properties"), dict)):
            raise AcquisitionError("invalid_feature_structure")
    # Fail on source schema drift, but retain individual rows with null names/IDs.
    expected = {"id", "name", "healthcare", "amenity"} if source == "osm" else {"Sr_No", "Hospital_Name", "State", "Pincode"}
    keys = set().union(*(f["properties"].keys() for f in features))
    if not expected <= keys:
        raise AcquisitionError("source_schema_drift")
    return features, member, metadata


class LandingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.datasets, self.script = [], [], None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag == "script" and attrs.get("type") == "application/ld+json":
            self.script = []

    def handle_data(self, data):
        if self.script is not None:
            self.script.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.script is not None:
            try:
                value = json.loads("".join(self.script))
                self.datasets.extend(value if isinstance(value, list) else [value])
            except ValueError:
                pass
            self.script = None


def resolve_nhp_landing(data, url):
    parser = LandingParser()
    try:
        parser.feed(data.decode("utf-8"))
    except UnicodeError as exc:
        raise AcquisitionError("invalid_landing_encoding") from exc
    datasets = [d for d in parser.datasets if isinstance(d, dict) and d.get("@type") == "Dataset"
                and urlsplit(d.get("url", "")).path.rstrip("/") == urlsplit(url).path.rstrip("/")]
    if len(datasets) != 1:
        raise AcquisitionError("nhp_dataset_metadata_missing_or_ambiguous")
    dataset = datasets[0]
    links = {urljoin(url, link) for link in parser.links}
    downloads = [d.get("contentUrl") for d in dataset.get("distribution", [])
                 if d.get("encodingFormat") == "application/geo+json"]
    downloads = sorted({urljoin(url, u) for u in downloads if isinstance(u, str)})
    if len(downloads) != 1 or downloads[0] not in links:
        raise AcquisitionError("nhp_download_missing_or_ambiguous")
    return public_url(downloads[0]), dataset


def present(value, nhp=False):
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    value = str(value)
    if not value.strip() or (nhp and value.strip() == "0"):
        return None
    return value


def pick(properties, *keys, nhp=False):
    for key in keys:
        value = present(properties.get(key), nhp=nhp)
        if value is not None:
            return value
    return None


def in_india_bbox(x, y):
    # Screening envelope includes mainland and islands, not a country boundary test.
    return 68 <= x <= 98 and 6 <= y <= 38


def position(value):
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        raise ValueError("invalid position")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value[:2]):
        raise ValueError("non-numeric position")
    x, y = value[:2]
    if not math.isfinite(x) or not math.isfinite(y) or not -180 <= x <= 180 or not -90 <= y <= 90:
        raise ValueError("outside WGS84")
    return x, y


def coordinates(geometry):
    flags = []
    if geometry is None:
        return None, None, None, ["coordinates_missing"]
    if not isinstance(geometry, dict):
        return None, None, None, ["coordinates_invalid"]
    kind = geometry.get("type")
    method = "source_point"
    try:
        if kind == "Point":
            xy = geometry.get("coordinates")
            if xy is None or xy == []:
                return None, None, None, ["coordinates_missing"]
            x, y = position(xy)
        elif kind in {"Polygon", "MultiPolygon"}:
            polygons = [geometry["coordinates"]] if kind == "Polygon" else geometry["coordinates"]
            for polygon in polygons:
                if not polygon:
                    raise ValueError("empty polygon")
                for ring in polygon:
                    if len(ring) < 4 or ring[0] != ring[-1]:
                        raise ValueError("unclosed polygon")
                    for vertex in ring:
                        position(vertex)
            geom = shape(geometry)
            if geom.is_empty or not geom.is_valid:
                raise ValueError("invalid geometry")
            point = geom.representative_point()
            x, y = position([point.x, point.y])
            method = "polygon_representative_point"
            flags.extend(["geometry_" + kind.lower(), "representative_point_not_entrance"])
        else:
            return None, None, "unknown", ["geometry_unsupported", "coordinates_unavailable"]
    except (ValueError, TypeError, KeyError, IndexError, GEOSException):
        return None, None, None, ["coordinates_invalid"]
    if not in_india_bbox(x, y):
        flags.append("outside_india_bbox")
        if in_india_bbox(y, x):
            flags.append("possibly_swapped_coordinates")
    return y, x, method, flags


def normalize(feature, snapshot_id, source, locator):
    p = feature["properties"]
    flags = []
    if source == "osm":
        source_id = pick(p, "id") or present(feature.get("id"))
        # Do not replace absent native names with transliterations or fabricated names.
        name = pick(p, "name")
        address = pick(p, "addr_full", "addr:full")
        city = pick(p, "addr_city", "addr:city")
        state = pick(p, "adm1_name", "addr_state", "addr:state")
        pin = pick(p, "addr_postcode", "addr:postcode", "postal_code")
        specialty = pick(p, "healthcare_speciality", "healthcare:speciality")
        healthcare, amenity = pick(p, "healthcare"), pick(p, "amenity")
        kind = healthcare if healthcare and healthcare not in {"yes", "no"} else amenity
        for field, value in [("healthcare", healthcare), ("amenity", amenity)]:
            if value:
                flags.append("source_" + field + "=" + value)
    else:
        source_id = pick(p, "Sr_No") or present(feature.get("id"))
        name = pick(p, "Hospital_Name", nhp=True)
        address = pick(p, "Address_Original_First_Line", nhp=True)
        city = pick(p, "Town", nhp=True)  # District/Subdistrict are not silently made cities.
        state = pick(p, "State", nhp=True)
        pin = pick(p, "Pincode")
        specialty = pick(p, "Specialties", nhp=True)
        kind = pick(p, "Hospital_Care_Type", nhp=True)
        for field in ("Hospital_Category", "Hospital_Care_Type", "Discipline_Systems_of_Medicine"):
            value = pick(p, field, nhp=True)
            if value:
                flags.append("source_" + field + "=" + value)
    if not source_id:
        flags.append("source_identifier_missing")
    if name is None:
        flags.append("name_missing")
    if address is None:
        flags.append("address_missing")
    if specialty is None:
        flags.append("specialty_unknown")
    if pin is not None and not re.fullmatch(r"[0-9]{6}", pin):
        pin = None
        flags.append("pin_invalid")
    if pin is None:
        flags.append("pin_missing")
    if not kind:
        kind = "unknown"
        flags.append("facility_type_unknown")
    latitude, longitude, method, geo_flags = coordinates(feature.get("geometry"))
    flags.extend(geo_flags)
    row = {
        "external_facility_id": "acq-external:" + digest(canonical([snapshot_id, source_id, feature])),
        "snapshot_id": snapshot_id, "source_record_id": source_id, "record_locator": locator,
        "name_original": name,
        "name_normalized": " ".join(unicodedata.normalize("NFKC", name).casefold().split()) if name else None,
        "address_original": address, "facility_type": kind, "city": city, "state": state,
        "pin": pin, "latitude": latitude, "longitude": longitude, "coordinate_method": method,
        "quality_flags": sorted(set(flags)),
    }
    return row


def counts(rows):
    return {
        "rows": len(rows),
        "name_populated": sum(r["name_original"] is not None for r in rows),
        "address_populated": sum(r["address_original"] is not None for r in rows),
        "specialty_populated": sum("specialty_unknown" not in r["quality_flags"] for r in rows),
        "coordinates_populated": sum(r["latitude"] is not None for r in rows),
        "coordinates_missing": sum("coordinates_missing" in r["quality_flags"] for r in rows),
        "coordinates_invalid": sum("coordinates_invalid" in r["quality_flags"] for r in rows),
        "coordinates_unavailable": sum("coordinates_unavailable" in r["quality_flags"] for r in rows),
        "outside_country_candidates_bbox": sum("outside_india_bbox" in r["quality_flags"] for r in rows),
        "possibly_swapped_coordinates": sum("possibly_swapped_coordinates" in r["quality_flags"] for r in rows),
        "distinct_source_identifiers": len({r["source_record_id"] for r in rows if r["source_record_id"] is not None}),
    }


def make_batch(features, member, snapshot, source):
    batch = envelope()
    batch["source_snapshots"] = [snapshot]
    unique, input_rows, by_id = {}, [], defaultdict(set)
    for index, feature in enumerate(features):
        locator = ("zip:" + member if member else "raw") + "#/features/" + str(index)
        row = normalize(feature, snapshot["snapshot_id"], source, locator)
        input_rows.append(row)
        key = row["external_facility_id"]
        unique.setdefault(key, row)  # Exact repeats use the first resolving source locator.
        if row["source_record_id"] is not None:
            by_id[row["source_record_id"]].add(key)
    conflicts = {source_id: variants for source_id, variants in by_id.items() if len(variants) > 1}
    conflicting_ids = set().union(*conflicts.values()) if conflicts else set()
    for row in unique.values():
        key = row["external_facility_id"]
        if key in conflicting_ids:
            row["quality_flags"] = sorted(set(row["quality_flags"] + ["conflicting_source_identifier"]))
            batch["review_queue"].append(review("conflicting_source_identifier", key, key))
        reasons = set(row["quality_flags"]) & {"coordinates_invalid", "outside_india_bbox", "geometry_unsupported"}
        for reason in sorted(reasons):
            batch["review_queue"].append(review(reason, key, key))
    batch["external_facilities"] = sorted(unique.values(), key=lambda r: r["external_facility_id"])
    batch["review_queue"].sort(key=lambda r: r["review_id"])
    output = batch["external_facilities"]
    types = sorted({r["facility_type"] for r in input_rows})
    coverage = {
        "input": counts(input_rows), "output": counts(output),
        "exact_duplicates_removed": len(features) - len(output),
        "conflicting_source_identifiers": len(conflicts), "conflicting_variants": len(conflicting_ids),
        "geometry_types": dict(sorted(Counter((f["geometry"].get("type") or "missing") if isinstance(f.get("geometry"), dict) else "missing" for f in features).items())),
        "by_facility_type": {t: {"input": counts([r for r in input_rows if r["facility_type"] == t]),
                                  "output": counts([r for r in output if r["facility_type"] == t])} for t in types},
        "limitations": ["India bounding-box screening is not a political boundary test.",
                        "Representative points are interior geometry points, not verified entrances.",
                        "Specialty missingness is unknown, not absence of care.",
                        "Source records await C's identity matching; no clinical quality or independent VF corroboration asserted."],
    }
    id_counts = Counter(r["source_record_id"] for r in input_rows if r["source_record_id"] is not None)
    coverage["repeated_identifier_rows"] = sum(n - 1 for n in id_counts.values())
    return batch, coverage
