"""What the judge walkthrough says, worked out from a loaded display edition. No Streamlit here.

Every number, date and source on the screen comes from the edition (field names in display_schema.json).
The wording below adds no facility, count, score, rank, travel time or percentage of its own. Dates and
periods are shown exactly as the edition writes them.
"""
try:
    from .loader import is_link
except ImportError:  # run as a script by Streamlit
    from loader import is_link

# The steps a facility's evidence has to climb before this project would send anyone there.
RUNGS = (
    ("listed", "A record says it", "A facility record or report mentions the service."),
    ("independent", "A second source agrees", "An independent source places the same facility at the same site."),
    ("dated", "The service is dated", "Someone stated when the service was delivered."),
    ("branch", "The exact branch confirms it now", "The operator names the branch or entrance and confirms "
                                                    "the service runs there today."),
)
SERVICES = {"dialysis": "dialysis", "mri": "MRI", "trauma_care": "trauma care"}
FIELDS = {"name": "name", "healthcare:speciality": "specialty"}
# Fields the edition carries as null on purpose: shown as unknown, never filled in.
UNKNOWN = (
    ("current_building_level_onsite_status", "Which building delivers the service today"),
    ("current_staffed_capacity", "Staffed capacity today"),
    ("entrance", "Which entrance to use"),
    ("travel_minutes", "Travel time"),
    ("shared_address_display", "A street address (the address report is a link only)"),
)


def count(n, one, many=None):
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


def joined(parts):
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def source(text, label):
    """A source as {"url", "label"} when it is a public https link, or as plain text otherwise."""
    if is_link(text):
        host = text.split("/")[2].removeprefix("www.")
        if host == "github.com":
            return {"url": text, "label": label, "note": "team record, needs repository access"}
        return {"url": text, "label": label, "note": host}
    return {"url": None, "label": text, "note": ""}


def national(data):
    n = data["national"]
    p = n["issuer_pilot"]
    return {
        "headline": count(p["exact_vf_links"], "exact link"),
        "line": (f"{p['scope']}: {count(p['issuer_listings_screened'], 'listing')} screened, "
                 f"{count(p['programme_mentions'], 'dialysis programme mention')} on "
                 f"{count(p['distinct_printed_premises_keys'], 'printed premises key')}. "
                 f"{p['exact_vf_links']:,} of them link exactly to a Virtue Foundation facility record, and "
                 f"{p['dated_onsite_claims']:,} carry a dated claim of onsite service."),
        "denominator": (f"Against {n['dataset']}: {count(n['occurrences'], 'original facility record')}, "
                        f"{count(n['distinct_upstream_ids'], 'upstream ID')} and "
                        f"{n['unconfirmed_occurrence_service_decisions']:,} of "
                        f"{count(n['occurrence_service_decisions'], 'service decision')} still unconfirmed, "
                        f"as of {n['baseline_decisions_as_of']}."),
        "accuracy": ("How accurate these records are nationally is not known." if n["unknown_national_accuracy"]
                     else ""),
        "source": source(p["source"], "replay of this count"),
    }


def trace(data):
    t = data["vf_trace_case"]
    by_service = [f"{n:,} {SERVICES.get(k, k)}" for k, n in t["same_osm_by_service"].items() if n]
    fields = [f"{n:,} in the {FIELDS.get(k, k)} field" for k, n in t["exact_object_associations_by_field"].items() if n]
    snapshots = len(t["map_snapshots"])
    limits = [
        (f"The {count(snapshots, 'map edition')} share one origin ({t['same_origin_family']}), so they count "
         "as one source, not two." if snapshots > 1 else f"The map comes from one origin ({t['same_origin_family']})."),
        (f"{t['cohort_associations_with_service_observation_date']:,} of the "
         f"{count(t['cohort_candidate_associations'], 'association')} in this cohort say when the service was "
         "delivered."),
        (f"{count(t['missing_branch_crosswalk_keys'], 'key')} "
         f"{'lacks' if t['missing_branch_crosswalk_keys'] == 1 else 'lack'} a branch crosswalk, and "
         f"{count(t['explicit_competing_branch_bindings'], 'key')} "
         f"{'is' if t['explicit_competing_branch_bindings'] == 1 else 'are'} bound to a specific competing "
         "branch."),
        (f"{count(t['keys_with_another_retained_site_group'], 'key')} also "
         f"{'reaches' if t['keys_with_another_retained_site_group'] == 1 else 'reach'} another possible site "
         "group."),
        (f"{count(t['independent_same_premises_bindings'], 'independent same-premises binding')} and "
         f"{count(t['reviewed_onsite_pairs'], 'reviewed onsite pair')} enter the result."),
        f"Precision: {t['point_precision']}",
    ]
    independent = ("met" if t["independent_same_premises_bindings"] else
                   "partial" if t["exact_shared_osm_object_keys"] else "missing")
    return {
        "headline": f"{t['exact_shared_osm_object_keys']:,} of {t['campus_located_lead_keys']:,}",
        "line": (f"Of {count(t['national_external_lead_keys'], 'external lead key')}, "
                 f"{t['campus_located_lead_keys']:,} were classified as campus-located in directory v4. {t['exact_shared_osm_object_keys']:,} point "
                 f"to the same mapped object as their reference ({joined(by_service) if by_service else 'none'})"
                 + "." + (f" The matching mentions: {joined(fields)}." if fields else "")),
        "grain": t["grain"],
        "limits": limits,
        "snapshots": t["map_snapshots"],
        "source": source(t["source"], "frozen source trace"),
        "rungs": {"listed": "met" if t["national_external_lead_keys"] else "missing",
                  "independent": independent,
                  "dated": "met" if t["cohort_associations_with_service_observation_date"] else "missing",
                  "branch": "met" if t["reviewed_onsite_pairs"] else "missing"},
        "rung_notes": {"independent": "Same map object, one map origin" if independent == "partial" else "",
                       "dated": "" if t["cohort_associations_with_service_observation_date"] else
                       "No association is dated",
                       "branch": "" if t["reviewed_onsite_pairs"] else "No reviewed onsite pair"},
    }


def public(data):
    c = data["public_case"]
    h = c["added_historical_branch_evidence"]
    links = []
    if not c["has_documented_vf_occurrence_link_in_this_case"]:
        links.append("a Virtue Foundation record")
    if not c["has_documented_nabh_pilot_link_in_this_case"]:
        links.append("the accreditation pilot")
    facts = [{"when": f["period"] or f"Reported {c['release_date']}, period not stated",
              "what": f"{f['value']:,} {f['unit']}", "scope": f["locator"],
              "source": source(c["source"], f"{c['publisher']}, {c['release_date']}")}
             for f in c["known_at_shared_campus"]]
    facts.append({"when": h["event_date"], "what": h["event"], "scope": h["building"],
                  "source": source(h["source"], f"{c['publisher']}, {h['publication_date']}")})
    return {
        "title": c["name"],
        "buildings": c["buildings_named_in_pib"],
        "link_line": (f"No documented link to {' or '.join(links)} in this case. It shows the method on real, "
                      "attributable public facts." if links else
                      "Documented links to a Virtue Foundation record and the accreditation pilot."),
        "facts": facts,
        "lineage": h["same_operator_lineage"],
        "reference": source(c["shared_address_source_reference"], "Facility address report"),
        "unknown": [label for key, label in UNKNOWN if c[key] is None],
        "rungs": {"listed": "met", "independent": "partial",
                  "dated": "met" if any(f["period"] for f in c["known_at_shared_campus"]) or h["event_date"]
                  else "missing",
                  "branch": "missing" if c["current_building_level_onsite_status"] is None else "met"},
        "rung_notes": {"independent": "Every source shares the operator's lineage",
                       "dated": "Dated for the campus, and for one building in the past",
                       "branch": "Not known for either building"},
    }


def decision(data):
    d = data["decision"]
    e = d["evaluation"]
    unknown_rates = [name for key, name in (("wrong_branch_rate", "wrong-branch rate"),
                                            ("unsupported_service_rate", "unsupported-service rate"),
                                            ("unstable_winner_rate", "unstable-winner rate"),
                                            ("measured_deferral_cost", "cost of deferring")) if e[key] is None]
    return {
        "eligible": d["point_rank"]["eligible_destinations_in_cases"],
        "next_check": d["verify"]["highest_value_fact"],
        "policies": [
            ("Rank by distance and detour", d["point_rank"]["status"]),
            ("Penalise weak evidence", f"{d['quality_penalty']['status']} Provenance: "
                                       f"{d['quality_penalty']['provenance']} Recency: {d['quality_penalty']['recency']} "
                                       f"Conflict: {d['quality_penalty']['conflict']}"),
            ("Best and worst case range", f"{d['range_rank']['status']} {d['range_rank']['reason']}"),
            ("Shortlist and verify", d["verify"]["status"]),
        ],
        "evaluation": (f"{count(e['scored_requests'], 'request')} could be scored, so the "
                       f"{joined(unknown_rates)} {'is' if len(unknown_rates) == 1 else 'are'} unknown."
                       if unknown_rates else f"{count(e['scored_requests'], 'request')} scored."),
    }


def build(data):
    """The whole walkthrough, in the order a judge reads it."""
    d = decision(data)
    return {
        "edition": data["schema"],
        "audience": data["audience"],
        "result": {
            "headline": "No facility can be recommended yet",
            "line": (f"{count(d['eligible'], 'eligible destination')} in either case. No score, rank or travel "
                     "time is shown, because none can be computed from this evidence."),
            "next_check": d["next_check"],
        },
        "decision": d,
        "national": national(data),
        "trace": trace(data),
        "public": public(data),
        "rungs": RUNGS,
    }
