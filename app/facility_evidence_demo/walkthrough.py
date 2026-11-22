"""What the judge walkthrough says, worked out from a loaded display edition. No Streamlit here.

Every number and source link on the screen comes from the edition. The wording below adds no facility, count,
score, rank, travel time or percentage of its own.
"""
from datetime import date

# The steps a facility's evidence has to climb before this project would send anyone there.
RUNGS = (
    ("listed", "A record says it", "A facility record or report mentions the service."),
    ("independent", "A second source agrees", "An independent source places the same facility at the same site."),
    ("dated", "The service is dated", "Someone stated when the service was delivered."),
    ("branch", "The exact branch confirms it now", "The operator names the branch or entrance and confirms "
                                                    "the service runs there today."),
)


def count(n, one, many=None):
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


def day(iso):
    return date.fromisoformat(iso).strftime("%-d %B %Y")


def services(by_service):
    parts = [f"{n:,} {name}" for name, n in by_service.items()]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def national(data):
    n, p = data["national_result"], data["national_result"]["pilot"]
    return {
        "headline": f"{p['exact_vf_links']:,} exact links",
        "line": (f"The accreditation pilot of {day(p['as_of'])} screened {count(p['listings_screened'], 'listing')} "
                 f"and found {count(p['programme_mentions'], 'dialysis programme mention')} on "
                 f"{count(p['premises_keys'], 'printed premises key')}. "
                 f"{p['exact_vf_links']:,} of them link exactly to a Virtue Foundation facility record, and "
                 f"{p['dated_onsite_claims']:,} carry a dated claim of onsite service."),
        "denominator": (f"Out of {count(n['originals'], 'original facility record')} "
                        f"({count(n['upstream_ids'], 'upstream ID')}, "
                        f"{count(n['frozen_unconfirmed_decisions'], 'frozen unconfirmed decision')}) "
                        f"as of {day(n['as_of'])}."),
        "source_url": n["source_url"],
    }


def trace(data):
    t = data["vf_trace"]
    origin = ("Both map editions come from the same OpenStreetMap lineage, so they count as one source, not two."
              if t["map_origins"] == 1 else f"The map editions come from {count(t['map_origins'], 'origin')}.")
    lines = [origin,
             f"{t['dated_service_associations']:,} of the {t['cohort_associations']:,} associations in this cohort "
             "say when the service was delivered."]
    if t["missing_branch_crosswalk"]:
        lines.append(f"{count(t['missing_branch_crosswalk'], 'key')} lack a branch crosswalk, so branch and "
                     "entrance are not established.")
    if t.get("other_group_keys"):
        lines.append(f"{count(t['other_group_keys'], 'key')} also "
                     f"{'reaches' if t['other_group_keys'] == 1 else 'reach'} another possible site group.")
    return {
        "headline": f"{t['same_object_keys']:,} of {t['campus_located_keys']:,}",
        "line": (f"Of {count(t['lead_keys'], 'external lead key')}, {t['campus_located_keys']:,} locate a campus on "
                 f"{count(t['originals'], 'facility record')}. {t['same_object_keys']:,} point to the same mapped "
                 f"object as their reference ({services(t['same_object_by_service'])})."),
        "limits": lines,
        "source_url": t["source_url"],
        "credit": t["credit"],
        "rungs": {"listed": "met", "independent": "partial" if t["map_origins"] == 1 else "met",
                  "dated": "met" if t["dated_service_associations"] else "missing", "branch": "missing"},
        "rung_notes": {"independent": "Same map object, but one map origin",
                       "dated": "None of the associations is dated" if not t["dated_service_associations"] else ""},
    }


def public(data):
    c = data["public_case"]
    linked = c["vf_link"] in ("established", "verified")
    return {
        "title": c["title"],
        "link_line": ("This case has an established link to a Virtue Foundation record." if linked else
                      "This public case is not linked to any Virtue Foundation record. It shows the method on "
                      "real, attributable facts."),
        "facts": c["facts"],
        "references": c.get("reference_links", []),
        "unknown": c["unknown"],
        "rungs": {"listed": "met", "independent": "partial",
                  "dated": "met" if c["facts"] else "missing", "branch": "missing"},
        "rung_notes": {"independent": "Government and operator sources only",
                       "dated": "Dated, but not for one branch today",
                       "branch": "Not known for either hospital"},
    }


def result(data):
    r = data["result"]
    n = r["eligible_destinations"]
    return {
        "headline": "No facility can be recommended yet" if n == 0 else count(n, "eligible destination"),
        "line": (f"{count(n, 'eligible destination')} on the evidence in this edition. No score, rank or travel "
                 "time is shown, because none can be computed from evidence this thin."),
        "next_check": r["next_check"],
        "policies": r.get("policies", []),
    }


def build(data):
    """The whole walkthrough, in the order a judge reads it."""
    e = data["edition"]
    return {
        "edition": f"{e['label']}, frozen {day(e['as_of'])}",
        "audience": e.get("audience", ""),
        "synthetic": bool(data.get("synthetic")),
        "result": result(data),
        "national": national(data),
        "trace": trace(data),
        "public": public(data),
        "rungs": RUNGS,
    }
