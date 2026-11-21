"""Generate tiny synthetic PDFs in temporary directories; commit no source PDFs."""
import tempfile
import unittest
from pathlib import Path

from research.acquisition.cghs.collector import compile_collection
from research.acquisition.cghs.extract_pdf import extract
from research.acquisition.common import AcquisitionError, canonical, file_digest


def synthetic_pdf(pages):
    """Minimal PDF writer for ASCII fixture tables; no extra document library."""
    objects = [b"", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    page_ids = []
    for rows in pages:
        commands = ["0.5 w"]
        xs = [20, 60, 240, 440, 620, 780]
        top, height = 240, 30
        for x in xs:
            commands.append(f"{x} {top} m {x} {top-len(rows)*height} l S")
        for i in range(len(rows) + 1):
            y = top - i * height
            commands.append(f"20 {y} m 780 {y} l S")
        for i, row in enumerate(rows):
            for j, value in enumerate(row):
                escaped = value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                commands.append(f"BT /F1 9 Tf {xs[j]+3} {top-i*height-18} Td ({escaped}) Tj ET")
        content = "\n".join(commands).encode("ascii")
        stream_id = len(objects) + 1
        objects.append(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream")
        page_id = len(objects) + 1
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 800 260] /Resources << /Font << /F1 3 0 R >> >> /Contents {stream_id} 0 R >>".encode())
        page_ids.append(page_id)
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = (f"<< /Type /Pages /Count {len(page_ids)} /Kids [" + " ".join(f"{p} 0 R" for p in page_ids) + "] >>").encode()
    output = b"%PDF-1.4\n"
    offsets = [0]
    for i, body in enumerate(objects, 1):
        offsets.append(len(output)); output += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(output)
    output += f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode()
    output += b"".join(f"{n:010d} 00000 n \n".encode() for n in offsets[1:])
    output += f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return output


HEADERS = ["Serial", "Name", "Address", "Scope", "Validity"]


def layout(page, section="synthetic-main"):
    return {"page": page, "table": 1, "section": section, "columns": [
        {"header": header, "field": field} for header, field in zip(HEADERS,
            ["serial", "name_raw", "address_raw", "scope_raw", "validity_raw"])]}


class PdfExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "synthetic.pdf"

    def test_continuations_keep_fragments_and_need_producer_review(self):
        self.path.write_bytes(synthetic_pdf([
            [HEADERS, ["1", "Synthetic Campus East", "Example Street", "Synthetic scope", "01.01.2025 to 31.12.2027"]],
            [HEADERS, ["", "", "Example continuation", "More synthetic scope", ""],
             ["2", "Synthetic Campus West", "Other Example Street", "Other scope", ""]],
        ]))
        result = extract(self.path, [layout(1), layout(2)])
        self.assertEqual(result["raw_sha256"], file_digest(self.path))
        self.assertEqual(result["review_status"], "unreviewed")
        self.assertIsNone(result["reviewer"])
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(result["rows"][0]["address_raw"], "Example Street\nExample continuation")
        self.assertEqual([f["page"] for f in result["rows"][0]["fragments"]], [1, 2])
        self.assertNotIn("kind", result["rows"][0])
        self.assertEqual(result["rows"][1]["locator"]["row"], "2")

    def test_explicit_sections_allow_serial_restart_without_guessing(self):
        row = ["1", "Synthetic Centre", "Example Street", "Synthetic scope", ""]
        self.path.write_bytes(synthetic_pdf([[HEADERS, row], [HEADERS, row]]))
        with self.assertRaisesRegex(AcquisitionError, "repeated_serial"):
            extract(self.path, [layout(1), layout(2)])
        result = extract(self.path, [layout(1), layout(2, "synthetic-annexure")])
        self.assertEqual(len(result["rows"]), 2)

    def test_header_change_and_orphan_continuation_are_rejected(self):
        self.path.write_bytes(synthetic_pdf([[HEADERS, ["", "Synthetic orphan", "Example", "Scope", ""]]]))
        with self.assertRaisesRegex(AcquisitionError, "orphan_continuation"):
            extract(self.path, [layout(1)])
        changed = layout(1)
        changed["columns"][1]["header"] = "Unexpected header"
        with self.assertRaisesRegex(AcquisitionError, "table_header_changed"):
            extract(self.path, [changed])

    def test_pdf_to_compiler_requires_review_and_preserves_page_fragments(self):
        self.path.write_bytes(synthetic_pdf([
            [HEADERS, ["1", "Synthetic Campus", "Example Street", "Synthetic scope", ""]],
            [HEADERS, ["", "", "Example continuation", "More synthetic scope", ""]],
        ]))
        extracted = extract(self.path, [layout(1), layout(2)])
        row_path = self.path.parent / "rows.json"
        row_path.write_bytes(canonical(extracted))
        source = {"source_key": "synthetic_cghs", "source_family": "cghs_empanelment",
                  "issuer": "Synthetic Issuer", "publisher": "Synthetic Publisher", "series_key": "synthetic",
                  "eligible_population": "Synthetic population", "coverage_scope": "Synthetic jurisdiction",
                  "url": "https://example.org/synthetic.pdf", "retrieved_at": "2026-11-01T00:00:00Z",
                  "document_date": "2026-10-01", "raw_file": self.path.name, "sha256": file_digest(self.path),
                  "rows_file": row_path.name, "rows_sha256": file_digest(row_path),
                  "reuse": {"status": "permitted", "third_party_rights": "cleared", "reason": "Invented fixture",
                            "license": "Synthetic fixture", "attribution": "Synthetic fixture author"}}
        manifest = {"manifest_version": "1.0.0", "as_of": "2026-11-21", "sources": [source]}
        with self.assertRaisesRegex(AcquisitionError, "producer_transcription_review_required"):
            compile_collection(manifest, self.path.parent)
        extracted.update(review_status="producer_checked", reviewer="synthetic-reviewer")
        extracted["rows"][0]["kind"] = "campus"
        row_path.write_bytes(canonical(extracted)); source["rows_sha256"] = file_digest(row_path)
        result = compile_collection(manifest, self.path.parent)
        self.assertEqual(len(result["batch.json"]["external_facilities"]), 1)
        self.assertEqual([f["page"] for f in result["observations.json"][0]["fragments"]], [1, 2])
