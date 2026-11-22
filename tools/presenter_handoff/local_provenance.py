"""Show pinned local public source evidence beside simulated placements."""

from collections import Counter
from hashlib import sha256
import json
from urllib.parse import urlsplit


SIDECAR = "plan-evidence.json"
ROSTER = "approved-local-provenance-roster.json"
APPROVED = {
    "a9c15cc82590ce3272b006562cad61e92de5d97cba9cbdb5752797839b762047":
        "fa7a23dfb3c9ae47b338b37cfd0f2993ab1f486142edbcafbfbfc49972323748",
}
CLASS = {
    "trauma_care": "major_trauma",
    "minor_injury_urgent_care": "minor_injury_wound_care",
    "dialysis": "maintenance_outpatient_dialysis",
    "ophthalmic_treatment": "eye_procedures",
}
TIERS = {
    "operator_reports_specific_service": "Specific service reported by the facility operator",
    "related_service_scope_only": "Related service information",
}
PRECISION = {"mapped facility point": "mapped_point", "campus simulation anchor": "campus_anchor"}


def trusted_bytes(path, expected):
    if not path.is_file():
        return None
    raw = path.read_bytes()
    return raw if sha256(raw).hexdigest() == expected else None


def approved_rosters(assets):
    return {
        roster for roster, sidecar in APPROVED.items()
        if trusted_bytes(assets / ROSTER, roster) and trusted_bytes(assets / SIDECAR, sidecar)
    }


def validate_locations(plan, assets):
    roster = plan["geography"].get("roster_sha256")
    if roster not in APPROVED:
        return
    raw = trusted_bytes(assets / ROSTER, roster)
    if raw is None:
        raise ValueError("The exact local public source roster is unavailable")
    rows = {r["planning_id"]: r for r in json.loads(raw)["facilities"]}
    facilities = {f["id"]: f for f in plan["facilities"]}
    if rows.keys() != facilities.keys():
        raise ValueError("The local provenance plan does not match the twelve pinned site IDs")
    for fid, facility in facilities.items():
        row = rows[fid]
        expected = (row["label"], row["latitude"], row["longitude"], PRECISION[row["location_class"]],
                    row["publisher"], row["license"], row["source_url"])
        source = facility.get("source") or {}
        actual = (facility["label"], facility["latitude"], facility["longitude"], facility["precision"],
                  source.get("publisher"), source.get("license"), source.get("url"))
        if actual != expected:
            raise ValueError("A local provenance plan site differs from its pinned source record")


def load(plan, assets):
    roster = plan["geography"].get("roster_sha256")
    expected = APPROVED.get(roster)
    raw = trusted_bytes(assets / SIDECAR, expected) if expected else None
    if raw is None:
        return None
    data = json.loads(raw)
    if data["schema_version"] != "storm-service-provenance-v1" or data["roster_sha256"] != roster:
        return None
    sites = {site["planning_id"]: site for site in data["sites"]}
    facilities = {facility["id"]: facility for facility in plan["facilities"]}
    if set(sites) != set(facilities) or any(
        site["label"] != facilities[fid]["label"] for fid, site in sites.items()
    ):
        return None
    return sites


def sources(ui, rows):
    for row in rows:
        url = row.get("url") or row.get("source_url")
        if not isinstance(url, str):
            continue
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            continue
        label = row.get("issuer") or row.get("publisher") or parsed.hostname
        ui.link_button(str(label), url)
        date = row.get("publication_date") or "unknown"
        detail = row.get("locator")
        ui.caption(f"Publication date {date}" + (f" · {detail}" if detail else ""))


def render(ui, plan, sites):
    labels = {row["category"]: row["label"] for row in plan.get("condition_breakdown", [])}
    labels = {key: value for key, value in labels.items() if key in CLASS}
    if not labels:
        return
    groups = {p["id"]: p.get("condition_category") for p in plan["patients"]}
    backed = {
        (site["planning_id"], finding["service_class"])
        for site in sites.values() for finding in site["findings"]
        if finding["evidence_tier"] == "operator_reports_specific_service"
    }

    def evidence_counts(policy):
        counts = Counter(
            (row["facility"], CLASS.get(groups[row["patient"]])) in backed
            for row in plan["policies"][policy]["assignments"]
        )
        return f"{counts[True]} operator-reported · {counts[False]} modeled-only"

    ui.caption(f"Service evidence among simulated placements · Nearest first: {evidence_counts('nearest_first')} "
               f"· Exact optimum: {evidence_counts('exact_optimum')}. Staffed slots are simulated.")
    with ui.expander("Public source evidence for modeled placements", expanded=False):
        ui.caption("Public claims are scoped to the named branch. Staffed appointments and travel are simulated.")
        group = ui.selectbox("Simulated condition group", list(labels), format_func=labels.__getitem__,
                             key="_local_evidence_group")
        counts = {
            policy: Counter(row["facility"] for row in result["assignments"] if groups[row["patient"]] == group)
            for policy, result in plan["policies"].items()
        }
        selected_sites = set(counts["nearest_first"]) | set(counts["exact_optimum"])
        if not selected_sites:
            ui.write("This group has no simulated placement.")
            return
        options = sorted(selected_sites, key=lambda fid: (
            not any(f["service_class"] == CLASS[group] for f in sites[fid]["findings"]),
            -counts["exact_optimum"][fid], sites[fid]["label"],
        ))
        fid = ui.selectbox("Facility used for this group", options, format_func=lambda key: sites[key]["label"],
                           key=f"_local_evidence_{group}")
        site = sites[fid]
        ui.write(f"Simulated placements at this site · Nearest first {counts['nearest_first'][fid]} · "
                 f"Exact optimum {counts['exact_optimum'][fid]}")
        ui.caption(str(site["site_precision"]))
        branch = site.get("branch")
        if branch and branch.get("civic_address"):
            ui.write(branch["civic_address"])
            if branch.get("location_binding"):
                ui.caption(branch["location_binding"])
        findings = [item for item in site["findings"] if item["service_class"] == CLASS[group]]
        if not findings:
            ui.info("The cleared evidence packet has no matching service claim for this site and group.")
        for item in findings:
            ui.write(TIERS[item["evidence_tier"]])
            ui.write(item["reported_service"])
            ui.caption(f"Service observation date {item['service_observation_date'] or 'unknown'}")
            ui.caption(item["limits"])
            sources(ui, item["sources"])
        if branch:
            ui.markdown("**Branch and map references**")
            references = list(branch["public_branch_sources"])
            nhp = branch.get("public_nhp_reference")
            if isinstance(nhp, dict):
                references.append(nhp)
            sources(ui, references)
        if site.get("site_source_url"):
            sources(ui, [{"issuer": "OpenStreetMap location record", "url": site["site_source_url"]}])
