"""Create a local decision inventory. This module never copies or uploads files."""
import argparse
import json
from collections import Counter
from pathlib import Path

from research.acquisition.common import canonical, file_digest, write_json
from .collector import require, text

DISPOSITIONS = {"candidate_code_synthetic", "candidate_metadata", "hold_rights",
                "hold_source_review", "hold_mixed_package", "hold_unclassified"}


def inventory(roots, decisions):
    files = []
    for alias, root in sorted(roots.items()):
        require(alias and "/" not in alias and "\\" not in alias, "invalid_root_alias")
        root = Path(root).resolve()
        require(root.is_dir(), "missing_inventory_root")
        for path in sorted(root.rglob("*")):
            require(not path.is_symlink(), "inventory_symlink_requires_review")
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            name = alias + "/" + path.relative_to(root).as_posix()
            decision = decisions.get(name, {"disposition": "hold_unclassified", "reason": "No item-specific review decision supplied."})
            require(decision.get("disposition") in DISPOSITIONS, "invalid_file_disposition")
            text(decision.get("reason"))
            files.append({"path": name, "bytes": path.stat().st_size, "sha256": file_digest(path),
                          "disposition": decision["disposition"], "reason": decision["reason"],
                          "authorization_reference": decision.get("authorization_reference"),
                          "transfer_authorized": False})
    require(not (set(decisions) - {f["path"] for f in files}), "inventory_decision_has_no_file")
    return {"inventory_version": "1.0.0", "local_only": True, "transfer_performed": False,
            "decision_owner": "Oliver", "file_count": len(files),
            "counts_by_disposition": dict(sorted(Counter(f["disposition"] for f in files).items())),
            "note": "Candidates are not transfer approvals. Oliver must select the exact files and recipient separately.",
            "files": files}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", required=True, metavar="ALIAS=PATH")
    parser.add_argument("--decisions", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="local JSON file outside all inventoried roots")
    args = parser.parse_args()
    roots = {}
    for value in args.root:
        alias, separator, path = value.partition("=")
        require(separator and alias not in roots, "invalid_inventory_root")
        roots[alias] = Path(path).resolve()
    output = args.out.resolve()
    require(all(root != output and root not in output.parents for root in roots.values()), "inventory_output_must_be_outside_roots")
    result = inventory(roots, json.loads(args.decisions.read_text(encoding="utf-8")))
    write_json(output, result)
    print(canonical({"file_count": result["file_count"], "counts_by_disposition": result["counts_by_disposition"],
                     "inventory_sha256": file_digest(output), "transfer_performed": False}).decode())


if __name__ == "__main__":
    main()
