"""Entirely synthetic source fixtures; no downloaded source records."""
import io
import json
import zipfile


def feature(source="osm", identifier="node/1", name="Example अस्पताल", coordinates=None, **properties):
    p = {"id": identifier, "name": name, "amenity": "hospital", "healthcare": None} if source == "osm" else {
        "Sr_No": identifier, "Hospital_Name": name, "State": "Example State", "Pincode": "001234",
        "Hospital_Care_Type": "Hospital", "Address_Original_First_Line": "1 Example Road", "Specialties": "0"}
    p.update(properties)
    return {"type": "Feature", "properties": p,
            "geometry": {"type": "Point", "coordinates": [75.5, 26.5] if coordinates is None else coordinates}}


def geojson(features):
    return json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False).encode()


def osm_archive(features, extra=None):
    metadata = {"id": "hotosm_ind_health_facilities-osm", "properties": {
        "oex:source": "osm", "oex:snapshot": "2020-01-02", "license": "Synthetic fixture license",
        "table:row_count": len(features), "table:columns": []}}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("health.geojson", geojson(features))
        archive.writestr("metadata.json", json.dumps(metadata))
        for name, value in (extra or {}).items():
            archive.writestr(name, value)
    return stream.getvalue(), metadata


def landing(download="https://example.invalid/nhp.geojson", date=None):
    metadata = {"@type": "Dataset", "url": "https://bharatlas.com/view/nhp_hospitals",
                "creator": {"name": "National Health Portal (synthetic test)"},
                "license": "Synthetic fixture license", "creditText": "Synthetic NHP mirror test",
                "dateModified": "2020-01-01",
                "distribution": [{"encodingFormat": "application/geo+json", "contentUrl": download}]}
    if date:
        metadata["datePublished"] = date
    return ('<html><script type="application/ld+json">' + json.dumps(metadata) +
            '</script><a href="' + download + '">GeoJSON</a></html>').encode()


def snapshot():
    return {"snapshot_id": "synthetic:source:" + "0" * 64, "source_key": "synthetic",
            "publisher": "Synthetic publisher", "source_family": "synthetic",
            "url": "https://example.invalid/source", "retrieved_at": "2020-01-01T00:00:00Z",
            "published_date": None, "license": "Synthetic", "attribution": "Synthetic fixtures only",
            "sha256": "0" * 64, "artifact_uri": "synthetic://raw", "parser_version": "test-1",
            "independence_status": "unassessed"}
