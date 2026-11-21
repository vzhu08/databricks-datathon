"""Reviewed multiplicity handles for the pinned VF facilities snapshot only."""
from collections import defaultdict

from common import canonical, digest, require, stable_id

POLICY = "vf_v0_identical_occurrences"
SOURCE = "databricks_virtue_foundation_dataset_dais_2026_databricks.virtue_foundation_dataset.facilities"
VERSION = 0


def map_occurrences(rows, id_column, source_identity, source_version, policy):
    require(policy == POLICY, "id_policy", "unknown occurrence policy")
    require(source_identity == SOURCE and type(source_version) is int and source_version == VERSION,
            "id_policy", "reviewed policy requires the exact VF facilities table at version 0")
    require(id_column == "unique_id", "id_policy", "reviewed policy requires the original unique_id column")
    grouped = defaultdict(list)
    for row in rows:
        require(isinstance(row, dict) and isinstance(row.get(id_column), str) and row[id_column].strip(),
                "id_policy", "original unique_id must be nonempty text")
        grouped[row[id_column]].append(row)
    base, groups, keys = [], [], set()
    for original_id, copies in sorted(grouped.items()):
        payloads = {canonical(row) for row in copies}
        require(len(payloads) == 1, "id_policy", "same-ID/different-payload rows require a new reviewed policy")
        generated = len(copies) > 1
        handles = []
        for ordinal, raw in enumerate(copies, 1):
            handle = (stable_id("base-occurrence", source_identity, str(source_version), original_id, str(ordinal))
                      if generated else original_id)
            require(handle not in keys, "id_policy", "generated or retained internal key collision")
            keys.add(handle)
            handles.append(handle)
            base.append({"facility_id": handle, "source_row": raw})
        if generated:
            groups.append({"group_id": stable_id("base-duplicate-group", source_identity, str(source_version), original_id),
                           "original_unique_id": original_id, "source_row_sha256": digest(copies[0]),
                           "multiplicity": len(copies), "facility_ids": handles,
                           "meaning": "Interchangeable occurrences in one pinned snapshot; not physical row identities, separate campuses, independent confirmations or cross-version identities."})
    return sorted(base, key=lambda row: row["facility_id"]), groups
