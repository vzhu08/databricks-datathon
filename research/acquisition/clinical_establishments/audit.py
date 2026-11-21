"""Hash-verify every capture and inventory PDF pages without emitting source text."""
import argparse
from collections import Counter
from pathlib import Path

import pymupdf

from research.acquisition.common import canonical, digest, read_json, write_json
from .producer import scoped_path


def audit(acquisition, root):
    documents = []
    for capture in acquisition["receipts"]:
        result = {key: capture[key] for key in ("url", "status", "sha256", "byte_count", "retrieved_at")}
        if capture["status"] == "fetched":
            path = scoped_path(root, capture["raw_path"])
            raw = path.read_bytes()
            if len(raw) != capture["byte_count"] or digest(raw) != capture["sha256"]:
                raise ValueError("Capture readback differs")
            result["readback_verified"] = True
            if raw.startswith(b"%PDF-"):
                try:
                    with pymupdf.open(path) as pdf:
                        result["pages"] = len(pdf)
                        result["pages_without_extractable_text"] = [i for i, page in enumerate(pdf, 1) if not page.get_text().strip()]
                    result["format"] = "pdf"
                except Exception as exc:
                    result.update(format="malformed_pdf", error_type=type(exc).__name__)
            else:
                result["format"] = "html_or_other"
        documents.append(result)
    pdfs = [d for d in documents if d.get("format") == "pdf"]
    return dict(documents=documents, summary=dict(destinations=len(documents),
        outcomes=dict(Counter(d["status"] for d in documents)), pdf_files=len(pdfs),
        pdf_pages=sum(d["pages"] for d in pdfs),
        pdf_pages_without_extractable_text=sum(len(d["pages_without_extractable_text"]) for d in pdfs),
        raw_bytes=sum(d["byte_count"] for d in documents),
        unique_raw_hashes=len({d["sha256"] for d in documents if d["sha256"]})))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--acquisition", required=True, type=Path)
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    result = audit(read_json(args.acquisition), args.root)
    write_json(args.out, result)
    print(canonical(result["summary"]).decode())


if __name__ == "__main__":
    main()
