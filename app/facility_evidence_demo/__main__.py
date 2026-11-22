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


def show_fields(fields, indent="  "):
    for key, value in fields.items():
        label = key.replace("_", " ").capitalize()
        if isinstance(value, dict):
            print(f"{indent}{label}")
            show_fields(value, indent + "  ")
        elif isinstance(value, list):
            print(f"{indent}{label}")
            for item in value:
                if isinstance(item, dict):
                    show_fields(item, indent + "  ")
                else:
                    print(f"{indent}  {item}")
        elif value is not None:
            print(f"{indent}{label}: {value}")


def main(argv=None):
    request = arguments(argv)
    from .care_decision import evaluate

    result = evaluate(request, None, None)
    if result["action"] != "interrupt":
        display_result = load_local(loader)
        area_result = load_local(area)
        result = evaluate(request, display_result, area_result)

    print(result["next_check"])
    print("Judge selections")
    show_fields(result["request"])
    for title, key in (("Workflow urgency", "workflow_urgency"), ("Action", "action"),
                       ("Outcome", "status"), ("Service checked", "service")):
        if result[key] is not None:
            print(f"{title}: {result[key].replace('_', ' ')}")
    print(result["reason"])
    if result["action"] == "interrupt":
        return

    for title, loaded, section in (("Facility evidence", display_result, result["evidence"]),
                                   ("Area evidence", area_result, result["area"])):
        if loaded["status"] == "unavailable":
            print(f"{title} unavailable. {loaded['reason']}")
        elif section:
            print(title)
            show_fields(section)
    if result["eligible_destinations"] is not None:
        print(f"Eligible destinations: {result['eligible_destinations']}")


if __name__ == "__main__":
    main()
