"""Optional local macOS OCR for PDF pages whose text extraction is empty.

Output is an explicitly unreviewed OCR ledger with page/box/confidence. It is
never consumed by the equipment-row or service-status producers. Reuses each
completed page on retry; record the OS/engine version with a handoff.
"""
import argparse
import json
import platform
import subprocess
import tempfile
from pathlib import Path

from .capture import canonical, sha256, write_json
from .extract import modality_hits, NOTICE


def run(root, binary):
    import pypdfium2 as pdfium
    root, binary = Path(root), Path(binary).resolve()
    editions = json.loads((root / "editions.json").read_text())
    output = root / "ocr"
    output.mkdir(exist_ok=True)
    pages, mentions, gaps, notice_hits = [], [], [], []
    for edition in editions:
        if edition["suffix"] != ".pdf":
            continue
        empty = [part["page"] for part in edition["parts"] if part.get("status") == "requires_visual_or_ocr_review"]
        if not empty:
            continue
        document = pdfium.PdfDocument(root / edition["path"])
        try:
            for number in empty:
                key = f"{edition['sha256']}-{number}"
                target = output / f"{key}.json"
                if target.exists():
                    result = json.loads(target.read_text())
                else:
                    page = document[number - 1]
                    try:
                        with tempfile.TemporaryDirectory(dir=output) as tmp:
                            png = Path(tmp) / "page.png"
                            page.render(scale=3).to_pil().save(png)
                            done = subprocess.run([str(binary), str(png)], capture_output=True, text=True, timeout=120)
                            if done.returncode:
                                raise RuntimeError(done.stderr[:1000])
                            result = {"edition_sha256": edition["sha256"], "page": number,
                                      "render_scale": 3, "render_sha256": sha256(png),
                                      "engine": "Apple Vision VNRecognizeTextRequest accurate en-US no language correction",
                                      "platform": platform.platform(), "binary_sha256": sha256(binary),
                                      "status": "ocr_unreviewed", "lines": json.loads(done.stdout)}
                            write_json(target, result)
                    except Exception as exc:
                        gaps.append({"edition_sha256": edition["sha256"], "page": number, "error": str(exc)})
                        continue
                    finally:
                        page.close()
                pages.append({"edition_sha256": edition["sha256"], "page": number,
                              "line_count": len(result["lines"]), "path": str(target.relative_to(root)), "sha256": sha256(target)})
                for line_number, line in enumerate(result["lines"], 1):
                    locator = {"edition_sha256": edition["sha256"], "page": number, "line": line_number, **line}
                    if NOTICE.search(line["text"]):
                        notice_hits.append(locator)
                    for modality, start, end, exact in modality_hits(line["text"]):
                        mentions.append({**locator, "modality": modality, "start": start, "end": end,
                                         "exact_match": exact, "assertion_type": "ocr_unreviewed_lexical_mention",
                                         "campus_id": None, "service_decision": None})
                write_json(root / "ocr-progress.json", {"pages_completed": len(pages), "gaps": gaps})
        finally:
            document.close()
    write_json(root / "ocr-manifest.json", {"pages": pages, "gaps": gaps, "notice_hits": notice_hits})
    write_json(root / "ocr-mentions.json", mentions)
    return {"pages_completed": len(pages), "gaps": len(gaps), "lexical_mentions": len(mentions), "notice_hits": len(notice_hits)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    args = parser.parse_args()
    print(canonical(run(args.root, args.binary)))


if __name__ == "__main__":
    main()
