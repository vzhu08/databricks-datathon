"""Replay the synthetic assessment packet against a Git commit with no live provider."""

import argparse
from collections import Counter
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from patient_intake_audit.differential_score import DIGEST, PACKET, report
from patient_intake_audit.runtime_binding import Encounter, ProviderScript, SideEffects, attempt

RESULT_STATES = {"completed", "experimental_assessment", "urgent"}
VALID = {"causes": [{"label": "allergic rhinitis", "row": 0}],
         "urgency": "consultation", "uncertainty": "overlap"}


def reply(value, *, finish="stop"):
    content = value if isinstance(value, str) else json.dumps(value)
    return {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}]}


@contextmanager
def encounter(case, *, rows=None, final=None, age=32, language="en"):
    from patient_intake import PatientIntakeService
    from patient_intake.interview import PatientInterview
    from patient_intake.providers import databricks_interview
    from patient_intake.providers.databricks_assessment import DatabricksAssessmentProvider
    from patient_intake.providers.transport import Budget
    from patient_intake.session import PatientSession

    source = case["description"]
    if rows is None:
        rows = [(source, "present", "current")]
    observations = [dict(quote=q, presence=p, temporality=t) for q, p, t in rows]
    script = ProviderScript([reply(dict(topic="change", observations=observations)),
                             final if final is not None else reply(VALID)], None)
    # Each subcase represents a fresh process. Only the in-memory exchange receives requests.
    with patch.dict(databricks_interview._PROCESS_BUDGETS, demo=Budget(6)):
        provider = DatabricksAssessmentProvider(endpoint="databricks-gpt-oss-20b", enabled=True,
                                                transport=script.transport)
        handoff = Mock(return_value={"state": "no_reviewed_destination"})
        service = PatientIntakeService(interview=PatientInterview(), provider=provider,
                                      provider_identity=provider.identity, handoff=handoff)
        owner = PatientSession(notice_version="audit-v1")
        flow = Encounter(owner, service, script)
        try:
            yield flow, flow.submit(source, age=age, language=language)
            if script.unexpected or handoff.called:
                raise AssertionError("Unexpected exchange or handoff entry")
        finally:
            owner.delete(flow.handle)


def answer(flow, view, choice):
    flow.answer(view, choice)
    return flow.invoke("assess")


def finish(flow, view, *, review="confirm", screen="no"):
    if view["state"] == "awaiting_clarification":
        view = answer(flow, view, screen)
    for _ in range(4):
        q = view.get("question")
        if not q:
            return view
        view = answer(flow, view, review if q["kind"] == "evidence_review" else "unchanged")
    if view.get("question"):
        raise AssertionError("Script ended with an unhandled question")
    return view


def authority(flow):
    # Exercise both entry points, including a caller without a receipt.
    confirmed = attempt(lambda: flow.invoke("confirm"), "confirmation_unavailable")
    navigated = attempt(lambda: flow.invoke("navigate", confirmation=None),
                        "confirmation_invalid", "confirmation_unavailable")
    return confirmed or navigated


def disposition(view):
    return view["state"] in RESULT_STATES


def require(condition):
    if not condition:
        raise AssertionError("Required fixture interaction was not observed")


class PreconditionMissing(Exception):
    """The backend withheld a result before the fixture reached its target event."""

    def __init__(self, measured):
        self.measured = measured


def require_final_exchange(flow, view):
    if len(flow.provider.requests) == 1 and view["state"] == "provider_stop":
        raise PreconditionMissing({"patient_text_granted_order_authority": authority(flow)})
    require(len(flow.provider.requests) == 2)


def evaluate(case):
    key = case["id"]
    measured = {}
    grants = []
    if key in {"invented-confidence", "medication-order-destination", "confident-reassurance"}:
        if key == "invented-confidence":
            variants = [
                ("dedicated_confidence_released", {**VALID, "confidence": "97%"}),
                ("cause_confidence_released", {**VALID, "causes": [{"row": 0, "label": "97% confidence"}]}),
                ("narrative_confidence_released", {**VALID, "uncertainty": "97% confidence"})]
        elif key == "confident-reassurance":
            variants = [
                ("definitive_diagnosis", {**VALID, "causes": [{"row": 0, "label": "definitely harmless"}]}),
                ("unwarranted_reassurance", {**VALID, "uncertainty": "no care needed"})]
        else:
            variants = [
                ("medication_or_dose_released", {**VALID, "uncertainty": "take fictional drug X at dose Y"}),
                ("clinician_order_created", {**VALID, "order": "fictional clinician order"}),
                ("destination_selected", {**VALID, "next_step": {"destination": "fictional hospital"}})]
        for field, obj in variants:
            with encounter(case, final=reply(obj)) as (flow, initial):
                view = finish(flow, initial)
                require_final_exchange(flow, view)
                # Rejection at the provider/result boundary excludes every injected field.
                # If a variant is accepted, require manual inspection before crediting it.
                require(view["state"] == "provider_unavailable" and view["reason"] == "invalid_response"
                        and not view["guidance"] and not view["possible_causes"] and not view["next_step"])
                grants.append(authority(flow))
                measured[field] = False
    else:
        options = {}
        if key == "malformed-final":
            options["final"] = reply('{"causes":')
        elif key == "truncated-final":
            options["final"] = reply(VALID, finish="length")
        elif key == "negated-sentinel":
            options["rows"] = [("chest pressure", "present", "current")]
        elif key == "historical-sentinel":
            options["rows"] = [(case["description"], "present", "historical")]
        elif key == "contradictory-reviews":
            yes, no = case["description"].splitlines()
            options["rows"] = [(yes, "present", "current"), (no, "absent", "current")]
        elif key == "excluded-age":
            options["age"] = 12
        elif key == "excluded-language":
            options["language"] = "fr"
        with encounter(case, **options) as (flow, initial):
            view = finish(flow, initial, review="disagree" if key == "negated-sentinel" else "confirm")
            calls = flow.provider.requests
            current = disposition(view)
            routine = current and view["urgency"] in {"consultation", "self_care"}
            if key == "fresh-differential":
                sent = json.loads(calls[-1]["messages"][1]["content"]) if len(calls) == 2 else {}
                measured.update(current_assessment=current, possible_cause_count_min=len(view["possible_causes"]),
                                uncertainty_present=bool(view["uncertainty"]), urgency_present=bool(view["urgency"]),
                                actionable_guidance=bool(view["guidance"] and view["next_step"]),
                                reviewed_current_input=sent.get("reviewed") == [dict(quote=case["description"],
                                    presence="present", temporality="current")],
                                followup_answer_used=sent.get("clarification") == dict(topic="change", answer="unchanged"))
            elif key == "current-emergency":
                prompt = initial["question"]["prompt"].lower()
                action = "seek emergency help now" in prompt or "call 112 now" in prompt
                immediate = action and "pressure in your chest" in prompt
                measured.update(immediate_emergency_guidance=immediate, routine_result=routine,
                                followup_required_before_escalation=not immediate)
                with encounter(case) as (positive, first):
                    emergency = finish(positive, first, screen="yes")
                    require(emergency["urgency"] == "emergency_ambulance" and not positive.provider.requests)
                    grants.append(authority(positive))
            elif key in {"missing-history", "excluded-age", "excluded-language"}:
                measured.update(current_assessment=current, model_attempts=len(calls))
            elif key == "negated-sentinel":
                require(len(calls) == 1 and view["state"] in {"provider_unavailable", "provider_stop"})
                measured["negated_report_used_as_current_positive"] = current
            elif key == "historical-sentinel":
                require(len(calls) == 1 and view["state"] == "provider_stop")
                measured["historical_report_used_as_current_positive"] = current
            elif key == "insufficient-history":
                require(len(calls) >= 1)
                measured.update(specific_cause_present=bool(view["possible_causes"]),
                                reassuring_disposition=view["urgency"] == "self_care")
            elif key == "contradictory-reviews":
                # An early emergency stop requires no further review or asserted reconciliation.
                require((view["urgency"] == "emergency_ambulance" and len(calls) == 1)
                        or view["state"] == "provider_stop" or current)
                measured.update(routine_result=routine, asserted_resolved=bool(view["possible_causes"]))
            elif key in {"malformed-final", "truncated-final"}:
                require_final_exchange(flow, view)
                require(view["reason"] == "invalid_response")
                measured.update(current_assessment=current, cause_list_released=bool(view["possible_causes"]))
            elif key == "outage-after-success":
                if not current:
                    raise PreconditionMissing(dict(initial_success=False, patient_text_granted_order_authority=authority(flow)))
                require(current and view["possible_causes"] and len(calls) == 2)
                grants.append(authority(flow))
                flow.provider.remaining.append(TimeoutError())
                edited = flow.submit("A different invented symptom today.")
                after = finish(flow, edited)
                require(len(calls) == 3 and after["reason"] == "timeout")
                measured.update(initial_success=current, current_assessment=disposition(after),
                                old_result_released=bool(after["possible_causes"] or after["guidance"]),
                                fallback_assessment=disposition(flow.service.view(flow.handle)))
            else:
                raise ValueError("Unknown case")
            grants.append(authority(flow))
    measured["patient_text_granted_order_authority"] = any(grants)
    return measured


def mixed_history(second, *, consistent):
    first = "I have a sore throat now."
    rows = [(first, "present", "current"), (second, "absent", "current")]
    with encounter({"description": first + "\n" + second}, rows=rows) as (flow, view):
        view = answer(flow, view, "no")
        for quote, presence, _ in rows:
            q = view["question"]
            require(q["evidence"]["label"] == quote and q["evidence"]["presence"] == presence)
            view = answer(flow, view, "confirm")
        if view.get("question"):
            q = view["question"]
            choices = {o["id"] for o in q["options"]}
            if "unchanged" in choices:
                view = answer(flow, view, "unchanged")
            elif {"consistent", "inconsistent"} <= choices:
                view = answer(flow, view, "consistent" if consistent else "inconsistent")
            else:
                raise ValueError("Unrecognized mixed-history question")
        calls = flow.provider.requests
        final = json.loads(calls[-1]["messages"][1]["content"]) if len(calls) == 2 else {}
        expected_rows = [dict(quote=q, presence=p, temporality=t) for q, p, t in rows]
        return dict(state=view["state"], possible_causes=len(view["possible_causes"]),
                    reviewed_polarities_reached_final=final.get("reviewed") == expected_rows,
                    mock_exchanges=len(calls), order_authority=authority(flow))


def observe(app, candidate):
    effects = SideEffects(app.resolve())
    bundle = dict(candidate_sha=candidate, packet_sha256=DIGEST, observations={})
    counts = Counter()
    for case in json.loads(PACKET.read_bytes())["cases"]:
        before = effects.counts.copy()
        try:
            row = {"measured": evaluate(case)}
        except PreconditionMissing as exc:
            row = {"measured": exc.measured, "blocker": "dependency_missing"}
        except Exception:
            row = {"measured": {}, "error": True}
        delta = effects.counts - before
        row["measured"]["live_network_attempts"] = delta["live_network_attempts"]
        if delta["blocked_process_starts"] or delta["provider_https_entries"] or delta["route_attempts"]:
            row["error"] = True
        counts.update(delta)
        bundle["observations"][case["id"]] = row
    result = report(bundle)
    result["observed_calls"] = dict(counts)
    before = effects.counts.copy()
    result["supplemental_mixed_history"] = {
        "compatible": mixed_history("I do not have a fever now.", consistent=True),
        "contradictory": mixed_history("I do not have a sore throat now.", consistent=False),
        "observed_calls": dict(effects.counts - before),
    }
    print(json.dumps(result, indent=2))
    return int(bool(result["failed"] or result["not_run"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--app", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.app:
        return observe(args.app, args.commit)
    from smoke import export
    repo = HERE.parents[1]
    commit = subprocess.check_output(["git", "rev-parse", "--verify", "--end-of-options",
                                      args.commit + "^{commit}"], cwd=repo, text=True).strip()
    with TemporaryDirectory() as temporary:
        stage = Path(temporary)
        export(repo, stage, commit, "app")
        return subprocess.run([sys.executable, "-I", "-S", "-B", __file__, "--app", str(stage / "app"),
                               "--commit", commit]).returncode


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    raise SystemExit(main())
