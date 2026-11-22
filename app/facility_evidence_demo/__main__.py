"""Run the provider-off judge decision from a terminal."""

import argparse
import os

from . import area, loader


# Keys are the decision function's request vocabulary. Labels are for presenters.
QUESTIONS = {
    "danger": ("Is there immediate danger?", {"yes": "Yes", "no": "No", "unsure": "Unsure"}),
    "urgency": ("How urgent does this feel?", {
        "routine": "Routine", "soon": "Soon", "emergency": "Emergency", "unsure": "Unsure",
    }),
    "concern": ("What brings you here?", {
        "injury": "Injury", "dialysis": "Existing dialysis need",
        "mri": "Existing MRI referral or order", "other": "Other concern", "unsure": "Unsure",
    }),
    "injury_kind": ("What kind of injury?", {
        "head": "Head injury", "burn": "Burn", "limb_joint": "Limb or joint injury",
        "cut_wound": "Cut or wound", "other": "Other injury", "unsure": "Unsure",
    }),
    "severity": ("How severe is the reported concern?", {
        "mild": "Mild", "moderate": "Moderate", "severe": "Severe", "unsure": "Unsure",
    }),
}


def arguments(argv):
    parser = argparse.ArgumentParser(
        prog="python -m app.facility_evidence_demo",
        description="Use --guided for a live walkthrough, or pass selection flags for a single replay. "
        "Omitted replay selections mean unsure.",
        epilog=f"Point {loader.PATH_SETTING} to the approved local facility display file and "
        f"{area.PATH_SETTING} to the approved local area aggregate. Missing files are reported in the result.",
    )
    parser.add_argument("--guided", action="store_true", help="choose answers at terminal prompts")
    for key, (question, choices) in QUESTIONS.items():
        parser.add_argument("--" + key.replace("_", "-"), choices=tuple(choices),
                            help=f"{question} {' / '.join(choices.values())}.")
    args = vars(parser.parse_args(argv))
    guided = args.pop("guided")
    request = {key: value for key, value in args.items() if value is not None}
    if guided and request:
        parser.error("Use --guided alone, or omit it to replay the selection flags.")
    return guided, request


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


def show_decision(request):
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


def ask(question, choices):
    print("\n" + question)
    answers = {}
    for number, (value, label) in enumerate(choices.items(), start=1):
        print(f"  {number}. {label}")
        for alias in (str(number), value, label.casefold()):
            answers[alias] = value
    while True:
        reply = input("Choice (q to quit): ").strip().casefold()
        if reply in ("q", "quit", "cancel"):
            raise EOFError
        if reply in answers:
            return answers[reply]
        print("Enter a listed number or answer.")


def guided_request():
    from .care_decision import evaluate

    request = {}
    for key, (question, choices) in QUESTIONS.items():
        if key == "injury_kind" and request["concern"] != "injury":
            continue
        request[key] = ask(question, choices)
        if key in ("danger", "urgency") and evaluate(request)["action"] == "interrupt":
            break
    return request


def main(argv=None):
    guided, request = arguments(argv)
    if not guided:
        show_decision(request)
        return
    print("Judge walkthrough. Choose a number or type an answer.")
    try:
        while True:
            show_decision(guided_request())
            if ask("Try another selection?", {"yes": "Yes", "no": "No"}) == "no":
                break
    except (EOFError, KeyboardInterrupt):
        print("\nWalkthrough ended.")


if __name__ == "__main__":
    main()
