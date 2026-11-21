import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.main import app, normalize_upload
from app.contracts import validate_contract, utf16_length

ROOT = Path(__file__).resolve().parents[3]
@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

def test_shared_fixture_contracts(client):
    cases = json.loads((ROOT / "packages/contracts/fixtures/transform.json").read_text())
    for case in cases:
        response = client.post("/transform", json=case["input"])
        assert response.status_code == 200
        assert response.json() == case["expected"]
        validate_contract("TransformResult", response.json())
    validate_contract("ApiError", json.loads((ROOT / "packages/contracts/fixtures/error.json").read_text()))

def test_unicode_utf16_and_errors(client):
    response = client.post("/transform", json={"text": "🌿 garden"})
    assert response.json()["characters"] == 9
    invalid = client.post("/transform", json={"text": 3})
    assert invalid.status_code == 422
    validate_contract("ApiError", invalid.json())
    assert "x-request-id" in invalid.headers
    assert client.post("/transform", json={"text": "🌿" * 50001}).status_code == 422

def test_raw_upload_and_bounds(client):
    response = client.post("/documents/text?filename=garden.md", content="🌿\nGarden".encode(), headers={"content-type": "text/markdown"})
    assert response.status_code == 200
    value = response.json()
    validate_contract("Document", value)
    assert value["segments"][1]["start"] == 3
    assert value["segments"][1]["end"] == 9
    assert client.post("/documents/text", content=b"\xff", headers={"content-type":"text/plain"}).status_code == 422
    assert client.post("/documents/text", content=b"x"*1000001, headers={"content-type":"text/plain"}).status_code == 413
    assert client.post("/documents/text", content=b"x", headers={"content-type":"application/pdf"}).status_code == 415
    assert client.post("/documents/text", content=b"", headers={"content-type":"text/plain"}).json()["text"] == ""

def test_health_cors_and_document_validation(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/ready").json()["status"] == "ready"
    response = client.options("/transform", headers={"origin":"https://untrusted.example", "access-control-request-method":"POST"})
    assert "access-control-allow-origin" not in response.headers
    doc = normalize_upload(b"hello", "a.txt")
    doc["segments"][0]["end"] = 99
    with pytest.raises(ValueError): validate_contract("Document", doc)
    assert utf16_length("🌿") == 2


def test_shared_unicode_document_fixture(client):
    fixtures = json.loads((ROOT / "packages/contracts/fixtures/documents.json").read_text())
    for fixture in fixtures["cases"]:
        expected = fixture["document"]
        validate_contract("Document", expected)
        response = client.post("/documents/text", params={"filename": fixture["input"]["filename"]}, content=fixture["input"]["text"].encode("utf-8"), headers={"content-type": "text/plain"})
        assert response.status_code == 200
        actual = response.json()
        for key, value in expected.items():
            assert actual[key] == value
        encoded = actual["text"].encode("utf-16-le")
        for citation in fixture["citations"]:
            validate_contract("Citation", citation)
            assert encoded[citation["start"] * 2:citation["end"] * 2].decode("utf-16-le") == citation["quote"]
            segment = next(s for s in actual["segments"] if s["id"] == citation["segmentId"])
            assert segment["start"] <= citation["start"] < citation["end"] <= segment["end"]
        actual["segments"][0]["end"] = fixture["invalidEndOffset"]
        with pytest.raises(ValueError):
            validate_contract("Document", actual)
