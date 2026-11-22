"""Run the provider-off judge decision from a terminal."""

import argparse
import os

from . import area, loader


def arguments(argv):
    parser = argparse.ArgumentParser(
        prog="python -m app.facility_evidence_demo",
        description="Replay an anonymous judge selection using local evidence files. "
        "Omitted selections mean unsure.",
        epilog=f"Set {loader.PATH_SETTING} and {area.PATH_SETTING} to local copies "
        "of the approved editions to include evidence.",
    )
    parser.add_argument("--concern", choices=("injury", "dialysis", "mri", "other", "unsure"),
                        help="injury, existing dialysis need, existing MRI referral/order, or other")
    parser.add_argument("--injury-kind", choices=("head", "burn", "limb_joint", "cut_wound", "other", "unsure"),
                        help="kind of injury when concern is injury")
    parser.add_argument("--severity", choices=("mild", "moderate", "severe", "unsure"),
                        help="reported severity")
    parser.add_argument("--urgency", choices=("routine", "soon", "emergency", "unsure"),
                        help="self-rated urgency")
    parser.add_argument("--danger", choices=("yes", "no", "unsure"),
                        help="reported immediate danger")
    return {key: value for key, value in vars(parser.parse_args(argv)).items() if value is not None}


def load_local(module):
    # The shared loaders can download a Volume path. This command runs offline.
    location = os.environ.get(module.PATH_SETTING, "").strip()
    if location.startswith(("dbfs:", "/Volumes/")):
        return loader.unavailable(f"Set {module.PATH_SETTING} to a local copy of the approved file.")
    return module.load()


def show_source(source):
    print("Source:", " ".join(part for part in (source["label"], source["url"], source["note"]) if part))


def show_evidence(evidence):
    trace = evidence["trace"]
    print(evidence["summary"])
    print("Scope:", trace["grain"])
    print("Map editions:", ", ".join(trace["snapshots"]))
    print("Source family:", trace["source_family"])
    print("Location precision:", trace["precision"])
    print("Baseline:", evidence["baseline"]["dataset"], evidence["baseline"]["as_of"])
    show_source(trace["source"])
    pilot = evidence["issuer_pilot"]
    if pilot:
        print(pilot["line"])
        show_source(pilot["source"])
    case = evidence["historical_case"]
    if case:
        print("Separate historical case:", case["title"])
        print(case["link_line"])
        for fact in case["facts"]:
            print(f"{fact['when']} — {fact['what']} ({fact['scope']})")
            show_source(fact["source"])
        print("Unknown:", ", ".join(case["unknown"]))


def main(argv=None):
    request = arguments(argv)
    from .care_decision import evaluate

    result = evaluate(request, None, None)
    if result["action"] != "interrupt":
        display_result = load_local(loader)
        area_result = load_local(area)
        result = evaluate(request, display_result, area_result)

    if result["action"] == "interrupt":
        print(result["next_check"])
    print("Judge selections")
    for key, value in result["request"].items():
        label = "Self-rated urgency" if key == "urgency" else key.replace("_", " ").capitalize()
        print(f"  {label}: {value.replace('_', ' ')}")
    for title, key in (("Automatic assessment priority", "assessment_priority"),
                       ("Combined workflow urgency", "workflow_urgency"), ("Action", "action"),
                       ("Outcome", "status"), ("Service checked", "service")):
        if result[key] is not None:
            print(f"{title}: {result[key].replace('_', ' ')}")
    print(result["reason"])
    if result["action"] == "interrupt":
        return

    if display_result["status"] == "unavailable":
        print("Facility evidence unavailable.", display_result["reason"])
    elif result["evidence"]:
        show_evidence(result["evidence"])
    if area_result["status"] == "unavailable":
        print("Area evidence unavailable.", area_result["reason"])
    elif result["area"]:
        context = result["area"]
        print("National location coverage:", context["line"])
        print(context["ids"])
        show_source(context["source"])
    if result["eligible_destinations"] is not None:
        print(f"Eligible destinations: {result['eligible_destinations']}")
    print("Next check:", result["next_check"])


if __name__ == "__main__":
    main()
