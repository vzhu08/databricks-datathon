"""Reproduce the frozen B02 release from a directory of permitted original files."""

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from contextlib import ExitStack
from pathlib import Path

from bs4 import BeautifulSoup
import pdfplumber

from .release import compact, encode, publish


DEFAULT_RECIPE = Path(__file__).with_name("release02_recipe.json")


def file_hash(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def find_originals(directory, sources):
    required = {source["sha256"] for source in sources}
    if len(required) != len(sources):
        raise ValueError("Duplicate original in source recipe")
    originals = {}
    for path in sorted(directory.iterdir()):
        if path.is_file():
            sha = file_hash(path)
            if sha in required:
                originals.setdefault(sha, path)
    missing = [s["key"] for s in sources if s["sha256"] not in originals]
    if missing:
        raise ValueError(f"Missing exact original bytes for {', '.join(missing)}. "
                         "Use the frozen files or a publisher copy with the recorded hash.")
    return originals


def read_fields(path, source):
    """Read half-open character spans in the whitespace-normalized source view."""
    selectors = source["fields"]
    views = {selector[0] for selector in selectors.values()}
    with ExitStack() as stack:
        if source["format"] == "pdf":
            document = stack.enter_context(pdfplumber.open(path))
            if any(i < 1 or i > len(document.pages) for i in views):
                raise ValueError("PDF page outside the frozen document")
            text = {i: compact(document.pages[i - 1].extract_text() or "") for i in views}
        elif source["format"] == "html":
            soup = BeautifulSoup(path.read_bytes(), "html.parser")
            for tag in soup.select("script, style, noscript, template"):
                tag.decompose()
            segments = list(soup.stripped_strings)
            if any(i < 0 or i >= len(segments) for i in views):
                raise ValueError("HTML segment outside the frozen document")
            text = {i: compact(segments[i]) for i in views}
        else:
            raise ValueError("Unknown document format")

    fields = {}
    for name, (index, start, end) in selectors.items():
        if not 0 <= start < end <= len(text[index]):
            raise ValueError(f"Invalid source span for {name}")
        fields[name] = text[index][start:end]
    return fields


def source_claim(path, source, rules):
    fields = read_fields(path, source)
    matches = [rule for rule in rules if re.search(rule["contains"], fields["excerpt"], re.IGNORECASE)]
    if len(matches) != 1:
        raise ValueError("Expected a single frozen interpretation rule for the extracted passage")
    # Frozen annotations apply only to these original hashes and selected passages.
    # The patterns dispatch the original review, they are not a general clinical classifier.
    claim = {key: matches[0][key] for key in ("kind", "time_specific", "assertion", "ownership")}
    if source.get("expand_aiims"):
        if fields["acronym"] != "AIIMS":
            raise ValueError("Unexpected institution acronym")
        fields["acronym"] = "All India Institute of Medical Sciences"
    if "year_range" in fields:
        fields["year_range"] = fields["year_range"].replace("-", "–")
    claim["source"] = source["key"]
    claim["format"] = source["format"]
    claim["excerpt"] = fields["excerpt"]
    kind = source["format"]
    index = source["fields"]["excerpt"][0]
    claim["page" if kind == "pdf" else "segment"] = index
    identity_locator = source["identity_locator"].format_map(fields)
    claim["identity_locator"] = identity_locator
    prefix = f"PDF page {index}" if kind == "pdf" else f"HTML visible-text segment {index} (zero-based)"
    claim["locator"] = f"{prefix}; {identity_locator}"
    claim["assertion"] = claim["assertion"].format_map(fields)
    claim["next_action"] = "Review source wording, campus and service date before using this unlinked observation."
    claim["temporal_status"] = "historical" if claim["time_specific"] else "undated"
    campus = {"name": source["name_format"].format_map(fields),
              "address": source["address_format"].format_map(fields) if source.get("address_format") else None,
              "city": fields["city"], "district": fields["city"], "ownership": claim.pop("ownership")}
    claim["campus"] = campus
    return claim


def replay(original_dir, recipe_path, out):
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    if recipe["format_version"] != 1:
        raise ValueError("Unsupported source recipe version")
    originals = find_originals(original_dir, recipe["sources"])
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent) as temp:
        work = Path(temp)
        manifest = {"sources": [], "claims": []}
        for entry in recipe["sources"]:
            sha = entry["sha256"]
            # Staging a copy keeps the bytes stable between extraction and compilation.
            dest = work / sha
            shutil.copyfile(originals[sha], dest)
            metadata = {key: entry[key] for key in
                        ("key", "url", "publisher", "family", "retrieved_at", "sha256", "independence_status")}
            metadata.update(path=dest.name, published_date=entry.get("published_date"))
            manifest["sources"].append(metadata)
            manifest["claims"].append(source_claim(dest, entry, recipe["interpretation_rules"]))
        manifest_path = work / "manifest.json"
        manifest_path.write_bytes(encode(manifest))
        stage = work / "release"
        publish(manifest_path, stage)
        expected = recipe["release_sha256"]
        for name in ("batch.json", "claim_ledger.json"):
            if file_hash(stage / name) != expected[name]:
                raise ValueError(f"Replayed {name} differs from the frozen release")
        if out.exists():
            for name in ("batch.json", "claim_ledger.json", "sha256.json"):
                if (stage / name).read_bytes() != (out / name).read_bytes():
                    raise ValueError(f"Existing output differs at {name}")
        else:
            stage.rename(out)
    return expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--originals", type=Path, required=True,
                        help="Directory containing the nine original files; filenames can differ")
    parser.add_argument("--recipe", type=Path, default=DEFAULT_RECIPE)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(replay(args.originals, args.recipe, args.out), sort_keys=True))


if __name__ == "__main__":
    main()
