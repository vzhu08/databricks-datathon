"""Measure patient-runtime.v1 with independent scripted provider responses.

Run in a fresh, isolated process with only the pinned candidate's app/ added
to the import path. This measures the runtime API, not browser rendering.
"""

import argparse
from collections import deque
from contextlib import contextmanager
from datetime import date
import json
from pathlib import Path
import sys
from threading import Event, Lock, Thread
from unittest.mock import patch


class ProviderScript:
    identity = ("audit-stub", "v1")

    def __init__(self, replies):
        self.remaining = deque(replies)
        self.requests = []
        self.active = 0
        self.peak = 0
        self.lock = Lock()
        self.unexpected = False

    def assess(self, interview, *, continuation=None):
        with self.lock:
            self.requests.append(interview)
            if not self.remaining:
                self.unexpected = True
                raise RuntimeError("unscripted provider call")
            step = self.remaining.popleft()
            self.active += 1
            self.peak = max(self.active, self.peak)
        try:
            reply = step() if callable(step) else step
            if isinstance(reply, Exception):
                raise reply
            return dict(reply, provider_id=self.identity[0], provider_version=self.identity[1])
        finally:
            with self.lock:
                self.active -= 1


def completion(tag):
    return dict(state="completed", guidance=tag, uncertainty="Synthetic uncertainty",
                urgency="self_care", possible_causes=["Synthetic category"], next_step=None)


def question(ident="Q-ALPHA"):
    return dict(state="awaiting_clarification", question=dict(
        id=ident, kind="single", prompt=ident,
        options=[{"id": key, "label": key} for key in ("yes", "no", "unknown")]))


def evidence(presence="present", timing="current"):
    return dict(state="awaiting_clarification", question=dict(
        id="S-FACT", kind="evidence_review", prompt="Review the fictional observation.",
        options=[{"id": key, "label": key} for key in ("confirm", "uncertain", "disagree")],
        evidence=dict(concept_id="fictional", label="Fictional sensation", presence=presence,
                      temporality=timing, source_ref="description")))


class Encounter:
    def __init__(self, owner, service, provider):
        self.owner = owner
        self.service = service
        self.provider = provider
        self.handle = owner.open(consent=True, notice_version="audit-v1")

    def invoke(self, action, **kwargs):
        rev, _ = self.handle.read()
        return getattr(self.service, action)(self.handle, rev, **kwargs)

    def edit(self, text="A fictional sensation.", age=32, language="en"):
        return self.invoke("edit", description=text, context=dict(age_years=age, language=language))

    def submit(self, text="A fictional sensation.", **context):
        self.edit(text, **context)
        self.invoke("consent", granted=True)
        return self.invoke("assess")

    def answer(self, view, value):
        return self.invoke("answer", question_id=view["question"]["issuance_id"], answers=value)


@contextmanager
def encounter(replies=(), *, configured=True, budget=8, handoff=None):
    from patient_intake import PatientIntakeService
    from patient_intake.interview import PatientInterview
    from patient_intake.session import PatientSession

    stub = ProviderScript(replies)
    service = PatientIntakeService(
        interview=PatientInterview(supported_age_range=(18, 85), supported_languages=["en"]),
        provider=stub if configured else None, provider_identity=stub.identity if configured else None,
        max_turns=budget, handoff=handoff)
    owner = PatientSession(notice_version="audit-v1")
    flow = Encounter(owner, service, stub)
    try:
        yield flow
        if stub.unexpected:
            raise AssertionError("unexpected provider call")
    finally:
        if owner.status == "active":
            owner.delete(flow.handle)


def reviewed_fact(case_id):
    if case_id == "historical":
        text, replies = "Only last year, never today.", [evidence(), evidence(timing="historical"), question()]
    elif case_id == "unknown":
        text, replies = "I am unsure about this fictional sensation.", [question(), completion("NEW")]
    elif case_id == "negated":
        text = "I do not have the fictional sensation now."
        replies = [evidence(), evidence("absent"), question()]
    else:
        text = "This morning I noticed a fictional prickling feeling near my elbow."
        replies = [evidence(), question()]
    with encounter(replies) as flow:
        view = flow.submit(text)
        if case_id in {"negated", "historical"}:
            flow.answer(view, "disagree")
            view = flow.invoke("assess")
        flow.answer(view, "unknown" if case_id == "unknown" else "confirm")
        view = flow.invoke("assess")
        sent = flow.provider.requests[-1]
        if case_id == "unknown":
            encoded = sent["answers"][-1]["answer"]
            return dict(polarity="unknown" if encoded == ["unknown"] else "other",
                        encoded_negative=encoded == ["no"])
        review = sent["patient_evidence"][-1]
        timing = review["candidate"]["temporality"]
        if case_id == "historical":
            return dict(temporality="past" if timing == "historical" else "other",
                        current_positive=timing == "current" and review["patient_presence"] == "present")
        origin = ("patient_confirmed" if review["origin"] == "patient_review"
                  and review["decision"] == "confirm" else "other")
        if case_id == "negated":
            return dict(polarity=review["patient_presence"], fact_origin=origin)
        prompt = (view.get("question") or {}).get("prompt")
        return dict(fact_origin=origin, question="Q-ALPHA" if prompt == "Q-ALPHA" else "other",
                    mock_attempts_min=len(flow.provider.requests))


def outage(case_id):
    recovery = case_id == "new-turn-recovery"
    replies = [TimeoutError(), completion("NEW")] if recovery else [completion("OLD"), TimeoutError()]
    with encounter(replies) as flow:
        initial = flow.submit()
        if recovery:
            if initial["state"] != "provider_unavailable":
                raise AssertionError("outage precondition")
            starts = len(flow.provider.requests)
            result = flow.invoke("assess")
            return dict(assessment_tag="NEW" if result["guidance"] == "NEW" else "other",
                        mock_attempts=len(flow.provider.requests)-starts,
                        current_assessment=result["state"] == "completed")
        result = flow.submit("Changed fictional description.")
        # Actual rendered old-result visibility remains a browser observation.
        return dict(initial_success=initial["state"] == "completed" and initial["guidance"] == "OLD",
                    current_assessment=result["state"] == "completed")


def overlap(case_id):
    entered, release = Event(), Event()

    def delayed():
        entered.set()
        if not release.wait(5):
            raise TimeoutError()
        return completion("OLD")

    race = case_id == "late-first-response"
    with encounter([delayed, completion("NEW")] if race else [delayed], budget=2) as flow:
        flow.edit()
        flow.invoke("consent", granted=True)
        errors = []
        revision, _ = flow.handle.read()

        def submit():
            try:
                flow.service.assess(flow.handle, revision)
            except Exception as exc:
                errors.append(exc)

        thread = Thread(target=submit)
        thread.start()
        try:
            if not entered.wait(5):
                raise AssertionError("first request did not start")
            if race:
                if flow.submit("Edited fictional description.")["guidance"] != "NEW":
                    raise AssertionError("second completion missing")
            else:
                submit()
        finally:
            release.set()
            thread.join(6)
        if thread.is_alive():
            raise AssertionError("provider did not return")
        # Only the expected stale revision / in-progress rejection is benign.
        for exc in errors:
            code = getattr(exc, "code", None) or str(exc)
            if not isinstance(exc, ValueError) or code not in (
                "revision_stale", "session_revision_stale", "assessment_action_unavailable"
            ):
                raise AssertionError("unexpected runtime error")
        if race:
            displayed = flow.service.view(flow.handle)
            return dict(assessment_tag="NEW" if displayed["guidance"] == "NEW" else "other",
                        late_applied=displayed["guidance"] == "OLD")
        return dict(mock_attempts=len(flow.provider.requests), peak_in_flight=flow.provider.peak)


def consultation():
    return dict(completion("NEW"), urgency="consultation",
                next_step={"kind": "consultation", "specialty_code": None})


def handoff_case(case_id):
    from patient_intake import handoff

    as_of = date(2026, 11, 22)
    campus = {
        "facility_id": "CAMPUS-S-1", "as_of": as_of.isoformat(),
        "latitude": 20.0, "longitude": 75.0, "coordinate_status": "reviewed",
        "campus_review_ref": "audit-campus", "coordinate_review_ref": "audit-coordinates",
        "display_permission_ref": "audit-display",
        "services": {"dialysis": {
            "status": "unconfirmed" if case_id == "no-eligible-campus" else "yes",
            "service_review_ref": "audit-service", "source_date": as_of.isoformat(),
            "independent_families": ["audit-source"], "capabilities": {}, "availability": "unknown",
        }},
    }
    orders = {}
    verified = []

    def read_order(handle, revision):
        order = orders.get((handle, revision))
        if order is not None:
            verified.append(revision)
        return order

    release = {"release_ref": "audit-release", "as_of": as_of.isoformat(), "campuses": [campus]}
    service = handoff.PatientHandoff(read_verified_order=read_order,
                                     read_reviewed_release=lambda day: release if day == as_of.isoformat() else None,
                                     today=lambda: as_of)
    with encounter([consultation()], handoff=service) as flow:
        view = flow.submit()
        if view["state"] != "completed" or not view["guidance"]:
            raise AssertionError("missing handoff precondition")
        if case_id != "qualified-completion":
            orders[flow.handle, view["revision"]] = {"service": "dialysis", "required_capabilities": []}
        confirmation = flow.invoke("confirm")
        with patch.object(handoff, "rank_campuses", wraps=handoff.rank_campuses) as finder:
            result = flow.invoke("navigate", confirmation=confirmation)
        if case_id == "qualified-completion":
            return dict(current_assessment=view["state"] == "completed" and bool(view["guidance"]),
                        verified_order=bool(verified), finder_calls=finder.call_count)
        ids = [row["facility_id"] for row in result.get("destinations", [])]
        if result["state"] == "no_reviewed_destination" and not ids:
            destination = "none"
        elif result["state"] == "reviewed_destinations" and len(ids) == 1:
            destination = "CAMPUS-S-1" if ids == ["CAMPUS-S-1"] else "unexpected"
        else:
            destination = "unexpected"
        if case_id == "no-eligible-campus":
            return dict(destination=destination)
        return dict(destination=destination, verified_order=bool(verified), finder_calls=finder.call_count)


def runtime_case(case_id):
    if case_id in {"qualified-completion", "valid-reviewed-handoff", "no-eligible-campus"}:
        return handoff_case(case_id)
    if case_id == "malformed-provider":
        reply = completion("NEW")
        del reply["urgency"]
        with encounter([reply]) as flow:
            view = flow.submit()
            return dict(current_assessment=view["state"] == "completed" and bool(view["guidance"]))
    if case_id in {"novel-intake", "negated", "historical", "unknown"}:
        return reviewed_fact(case_id)
    if case_id in {"new-turn-recovery", "outage-after-success"}:
        return outage(case_id)
    if case_id in {"late-first-response", "concurrent-submit"}:
        return overlap(case_id)
    if case_id == "consent":
        with encounter() as flow:
            flow.edit("Synthetic consent marker.")
            flow.invoke("consent", granted=False)
            flow.invoke("assess")
            return dict(mock_attempts=len(flow.provider.requests),
                        unapproved_transmissions=len(flow.provider.requests))
    if case_id in {"unsupported-age", "unsupported-language", "no-configuration"}:
        with encounter(configured=case_id != "no-configuration") as flow:
            result = flow.submit(age=10 if case_id == "unsupported-age" else 32,
                                 language="fr" if case_id == "unsupported-language" else "en")
            return dict(current_assessment=result["state"] == "completed", mock_attempts=len(flow.provider.requests))
    if case_id == "budget-exhausted":
        with encounter([completion("OLD")], budget=1) as flow:
            if flow.submit()["state"] != "completed":
                raise AssertionError("initial completion missing")
            starts = len(flow.provider.requests)
            flow.submit("Edited fictional statement.")
            return dict(initial_attempts=starts, additional_provider_attempts=len(flow.provider.requests)-starts)
    if case_id == "question-loop":
        with encounter([question(), question()], budget=2) as flow:
            result = flow.submit()
            for _ in range(2):
                flow.answer(result, "unknown")
                result = flow.invoke("assess")
            return dict(post_limit_attempts=max(0, len(flow.provider.requests)-2),
                        current_assessment=result["state"] == "completed")
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, type=Path, help="Staged app/ from the recorded component SHAs")
    args = parser.parse_args()
    sys.path.insert(0, str(args.app.resolve()))
    external = []
    processes = []

    def deny(event, unused):
        if event.startswith("socket."):
            external.append(event)
            raise PermissionError("offline observer")
        if event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.fork", "os.exec"}:
            processes.append(event)
            raise PermissionError("offline observer")

    sys.addaudithook(deny)
    cases = json.loads(Path(__file__).with_name("cases.v1.json").read_bytes())["cases"]
    rows = {}
    for case in cases:
        key = case["id"]
        before = len(external)
        try:
            captured = runtime_case(key)
            if captured is None:
                rows[key] = {"blocker": "observer_missing"}
            else:
                captured["live_network_attempts"] = len(external) - before
                rows[key] = {"measured": captured}
        except Exception:
            rows[key] = {"error": True, "measured": {"live_network_attempts": len(external)-before}}
    print(json.dumps({"stage": "binding_smoke_only", "observations": rows,
                      "blocked_process_starts": len(processes)}, indent=2))
    return int(bool(external or processes) or any(row.get("error") for row in rows.values()))


if __name__ == "__main__":
    raise SystemExit(main())
