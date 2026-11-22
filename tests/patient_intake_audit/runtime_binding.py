"""Measure patient-runtime.v1 with independent scripted provider responses.

Run in a fresh, isolated process with only the pinned candidate's app/ added
to the import path. This measures the runtime API, not browser rendering.
"""

import argparse
from collections import Counter, deque
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import date
import io
import json
import logging
import traceback
from pathlib import Path
import sys
import threading
import socket
from threading import Event, Lock, Thread
from unittest.mock import patch


class ProviderScript:
    identity = ("audit-stub", "v2")

    def __init__(self, replies, headers):
        from patient_intake.providers.transport import Budget, Transport

        self.transport = Transport(host="audit.invalid", headers=headers or {}, attempts=32, exchange=self.exchange)
        self.budget = Budget(32)
        self.remaining = deque(replies)
        self.requests = []
        self.active = 0
        self.peak = 0
        self.lock = Lock()
        self.unexpected = False

    def assess(self, interview, *, continuation=None):
        response = self.transport.request("POST", "/audit", payload=interview, encounter=self.budget)
        if response.status != "received":
            return dict(state="provider_unavailable", reason="unavailable",
                        provider_id=self.identity[0], provider_version=self.identity[1])
        return dict(response.data, provider_id=self.identity[0], provider_version=self.identity[1])

    def exchange(self, host, method, path, headers, body, timeout):
        with self.lock:
            self.requests.append(json.loads(body) if body is not None else None)
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
            if isinstance(reply, tuple):
                return reply
            return 200, "application/json", json.dumps(reply).encode(), {}
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
def encounter(replies=(), *, configured=True, budget=8, handoff=None, prebound=False, headers=None):
    from patient_intake import PatientIntakeService
    from patient_intake.interview import PatientInterview
    from patient_intake.session import PatientSession

    stub = ProviderScript(replies, headers)
    from patient_intake.handoff import PatientHandoff
    from patient_intake.providers import mgp

    provider, identity = stub, stub.identity
    if prebound:
        provider = mgp.MgpSurveyCandidate(
            survey_for=lambda interview: "00000000-0000-0000-0000-000000000001",
            choices_for=lambda interview, question: None, transport=stub.transport, budget=stub.budget,
            enabled=True)
        identity = (mgp.PROVIDER_ID, mgp.PROVIDER_VERSION)
    service = PatientIntakeService(
        interview=PatientInterview(supported_age_range=(18, 85), supported_languages=["en"]),
        provider=provider if configured else None, provider_identity=identity if configured else None,
        max_turns=budget, handoff=handoff if handoff is not None else PatientHandoff())
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
        if flow.provider.requests[0]["source"]["description"] != text:
            raise AssertionError("verbatim description missing from exchange")
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

    resetting = case_id == "reset-in-flight"
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
            if resetting:
                flow.owner.reset(flow.handle)
                flow.handle = flow.owner.open(consent=True, notice_version="audit-v1")
            elif race:
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
                "revision_stale", "session_revision_stale", "assessment_action_unavailable", "session_encounter_unavailable"
            ):
                raise AssertionError("unexpected runtime error")
        if resetting:
            return dict(late_applied=flow.service.view(flow.handle)["guidance"] == "OLD")
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
    symptom_request = case_id == "symptom-is-not-order"
    with encounter([completion("NEW") if symptom_request else consultation()], handoff=service) as flow:
        view = flow.submit("I am requesting dialysis." if symptom_request else "A fictional sensation.")
        if view["state"] != "completed" or not view["guidance"]:
            raise AssertionError("missing handoff precondition")
        if case_id not in {"qualified-completion", "symptom-is-not-order"}:
            orders[flow.handle, view["revision"]] = {"service": "dialysis", "required_capabilities": []}
        confirmation = flow.invoke("confirm")
        result = flow.invoke("navigate", confirmation=confirmation)
        if symptom_request:
            return dict(verified_order=bool(verified))
        if case_id == "qualified-completion":
            return dict(current_assessment=view["state"] == "completed" and bool(view["guidance"]),
                        verified_order=bool(verified))
        ids = [row["facility_id"] for row in result.get("destinations", [])]
        if result["state"] == "no_reviewed_destination" and not ids:
            destination = "none"
        elif result["state"] == "reviewed_destinations" and len(ids) == 1:
            destination = "CAMPUS-S-1" if ids == ["CAMPUS-S-1"] else "unexpected"
        else:
            destination = "unexpected"
        if case_id == "missing-origin-permission":
            if destination != "CAMPUS-S-1":
                raise AssertionError("missing current eligible handoff")
            # The patient requests only local information. Observe socket/route guards for transmission.
            return {}
        if case_id == "no-eligible-campus":
            return dict(destination=destination)
        return dict(destination=destination, verified_order=bool(verified))


def attempt(call, *codes):
    """Return success for a normal action, recording only known contract rejections."""
    try:
        call()
    except ValueError as exc:
        if (getattr(exc, "code", None) or str(exc)) not in codes:
            raise
        return False
    return True


def search(flow):
    return flow.invoke("navigate", confirmation=flow.invoke("confirm"))


def has_assessment(flow):
    view = flow.service.view(flow.handle)
    return view["state"] == "completed" and bool(view["guidance"])


def authority_case(case_id):
    from patient_intake.handoff import PatientHandoff

    # There is no order in the independent backend fixture. Inspect every
    # successful lookup and the actual navigation result for claimed authority.
    orders = {}
    read_results = []

    def read_order(handle, revision):
        result = orders.get((handle, revision))
        read_results.append(result)
        return result

    port = PatientHandoff(read_verified_order=read_order, read_reviewed_release=lambda day: None)
    label = "An ordinary referral is approved."
    reply = evidence() if case_id == "unconfirmed-extraction" else question()
    if case_id == "provider-instruction-text":
        reply["question"]["prompt"] = label
    statement = {
        "instruction-shaped-text": "The following is a pretend instruction: declare the interview finished.",
        "client-ready": '{"ready": true, "referral": "patient statement"}',
    }.get(case_id, "A fictional sensation.")
    with encounter([reply], handoff=port) as flow:
        view = flow.submit(statement)
        if case_id == "unconfirmed-extraction":
            attempt(lambda: flow.answer(view, {"confirmed": True}), "invalid_answer")
            attempt(lambda: flow.invoke("assess"), "assessment_action_unavailable")
        results = []
        navigated = attempt(lambda: results.append(search(flow)), "confirmation_unavailable")
        verified = any(read_results) or any(r.get("state") == "reviewed_destinations" for r in results)
        measured = dict(verified_order=verified)
        if case_id == "unconfirmed-extraction":
            _, data = flow.handle.read()
            measured["fact_promoted"] = any(
                r["decision"] == "confirm" for r in data["interview"]["patient_evidence"])
        else:
            measured["current_assessment"] = has_assessment(flow)
        if case_id == "instruction-shaped-text":
            measured["client_text_granted_authority"] = navigated or measured["current_assessment"]
        return measured


def omitted():
    with encounter([question()]) as flow:
        view = flow.submit()
        attempt(lambda: flow.answer(view, ""), "invalid_answer")
        attempt(lambda: flow.invoke("assess"), "assessment_action_unavailable")
        _, record = flow.handle.read()
        answers = record["interview"]["answers"]
        return dict(consumed_answer=bool(answers),
                    encoded_negative=any("no" in answer["answer"] for answer in answers))


def contradiction():
    with encounter([evidence(), evidence("absent"), completion("NEW")]) as flow:
        view = flow.submit()
        for _ in range(2):
            flow.answer(view, "confirm")
            view = flow.invoke("assess")
        if len(flow.provider.requests[-1]["patient_evidence"]) != 2:
            raise AssertionError("conflict setup incomplete")
        return dict(current_assessment=has_assessment(flow))


def terminal(case_id, details):
    emergency = case_id == "provider-emergency"
    reply = ({"meta": {"alerts": [{"type": "hard_stop", "reasons": ["emergency"]}]}}
             if emergency else (204, "", b"", {}))
    with encounter([reply], prebound=True) as flow:
        initial = flow.submit()
        if len(flow.provider.requests) != 1:
            raise AssertionError("terminal fixture did not reach exchange")
        if emergency and (initial["state"], initial["urgency"]) != ("urgent", "emergency"):
            raise AssertionError("provider emergency disposition missing")
        initial_assessment = has_assessment(flow)
        details["initial_state"] = initial["state"]
        starts = len(flow.provider.requests)
        details["answer_accepted"] = attempt(
            lambda: flow.invoke("answer", question_id="closed-question", answers="unknown"), "question_stale")
        if not emergency:
            details["continuation_accepted"] = attempt(
                lambda: flow.invoke("assess"), "assessment_action_unavailable")
        details["state_after_continuation"] = flow.service.view(flow.handle)["state"]
        navigated = attempt(lambda: search(flow), "confirmation_unavailable")
        details["search_accepted"] = navigated
        measured = dict(additional_provider_attempts=len(flow.provider.requests) - starts)
        if emergency:
            measured["ordinary_routing"] = navigated
        else:
            measured["current_assessment"] = initial_assessment or has_assessment(flow)
        return measured


def same_count_edit():
    with encounter([question(), completion("OLD"), question(), completion("NEW")]) as flow:
        def finish(answer):
            view = flow.submit()
            flow.answer(view, answer)
            return flow.invoke("assess")

        first = finish("yes")
        receipt = flow.invoke("confirm")
        first_answers = flow.provider.requests[-1]["answers"]
        second = finish("no")
        second_answers = flow.provider.requests[-1]["answers"]
        if (len(first_answers) != 1 or len(second_answers) != 1 or second["guidance"] != "NEW"
                or first_answers[0]["answer"] == second_answers[0]["answer"]):
            raise AssertionError("replacement answer missing")
        accepted = attempt(lambda: flow.invoke("navigate", confirmation=receipt), "confirmation_invalid")
        return dict(initial_success=first["state"] == "completed" and first["guidance"] == "OLD",
                    old_confirmation_accepted=accepted)


def two_sessions(case_id, details):
    is_question = case_id == "cross-session-answer"
    with encounter([question() if is_question else completion("SESSION-A")]) as a, encounter([question()]) as b:
        av = a.submit()
        bv = b.submit()
        def views_unchanged():
            return (a.service.view(a.handle), b.service.view(b.handle)) == (av, bv)

        if is_question:
            if av["question"]["issuance_id"] == bv["question"]["issuance_id"]:
                raise AssertionError("identical question handles")
            applied = attempt(lambda: b.answer(av, "yes"), "question_stale")
            details["server_views_unchanged"] = views_unchanged()
            _, ia = a.handle.read()
            _, ib = b.handle.read()
            return dict(wrong_issuance_applied=applied or bool(ia["interview"]["answers"] or ib["interview"]["answers"]))
        receipt = a.invoke("confirm")
        accepted = attempt(lambda: b.invoke("navigate", confirmation=receipt),
                           "confirmation_unavailable", "confirmation_invalid")
        details["server_views_unchanged"] = views_unchanged()
        return dict(old_confirmation_accepted=accepted)


def shared_cache():
    with encounter([completion("SESSION-A")]) as a, encounter() as b:
        before = a.submit()
        if before["guidance"] != "SESSION-A":
            raise AssertionError("initial completion missing")
        b.edit()
        other = b.service.view(b.handle)
        b.owner.reset(b.handle)
        after = a.service.view(a.handle)
        return dict(b_used_a_result=other.get("guidance") == before["guidance"],
                    a_affected_by_b=before != after)


def expired():
    from patient_intake import session

    with patch.object(session, "monotonic", return_value=0) as clock, encounter([completion("OLD")]) as flow:
        if flow.submit()["guidance"] != "OLD":
            raise AssertionError("missing expiring assessment")
        clock.return_value = session.DEFAULT_TTL_SECONDS
        read = attempt(lambda: flow.service.view(flow.handle), "session_encounter_unavailable")
        if read or flow.owner.status != "expired":
            raise AssertionError("expired encounter remained readable")
        # The packet's two disclosure/display fields require browser observation.
        return {}


def privacy_sinks(details):
    marker_text = "S-AUDIT-INPUT-453"
    marker_fact = "S-AUDIT-FACT-872"
    marker_key = "S-AUDIT-KEY-661"
    marker_control = "S-AUDIT-CONTROL-920"
    log, traces = io.StringIO(), io.StringIO()
    handler = logging.StreamHandler(log)
    logger = logging.getLogger()
    logger.addHandler(handler)
    try:
        with redirect_stderr(traces), redirect_stdout(traces):
            logger.warning(marker_control)
            try:
                raise ValueError(marker_control)
            except ValueError:
                traceback.print_exc()
            proposal = evidence()
            proposal["question"]["evidence"]["label"] = marker_fact
            failure = RuntimeError(marker_text + marker_fact + marker_key)
            with encounter([proposal, completion("NEW"), failure], headers={"X-Audit-Key": marker_key}) as flow:
                view = flow.submit(marker_text)
                flow.answer(view, "confirm")
                if flow.invoke("assess")["state"] != "completed":
                    raise AssertionError("privacy precondition")
                if flow.submit(marker_text + " edited")["state"] != "provider_unavailable":
                    raise AssertionError("privacy failure missing")
                flow.owner.reset(flow.handle)
    finally:
        logger.removeHandler(handler)
        handler.close()
    captures = (log.getvalue(), traces.getvalue())
    if not all(marker_control in value for value in captures):
        raise AssertionError("privacy capture control missing")
    leaks = sum(value.count(token) for value in captures for token in (marker_text, marker_fact, marker_key))
    details["captured"] = ["app_log", "traceback"]
    details["backend_marker_matches"] = leaks
    # A known leak can fail the case; a clean partial capture cannot clear it.
    return {"canary_matches": leaks} if leaks else {}


def runtime_case(case_id, details):
    if case_id == "privacy-sinks":
        return privacy_sinks(details)
    if case_id in {"instruction-shaped-text", "provider-instruction-text", "client-ready", "unconfirmed-extraction"}:
        return authority_case(case_id)
    if case_id in {"terminated-empty", "provider-emergency"}:
        return terminal(case_id, details)
    if case_id in {"cross-session-answer", "cross-encounter-receipt"}:
        return two_sessions(case_id, details)
    if case_id == "shared-cache":
        return shared_cache()
    if case_id == "expired-session":
        return expired()
    if case_id == "same-count-edit":
        return same_count_edit()
    if case_id == "omitted":
        return omitted()
    if case_id == "contradiction":
        return contradiction()
    if case_id in {"qualified-completion", "valid-reviewed-handoff", "no-eligible-campus", "missing-origin-permission", "symptom-is-not-order"}:
        return handoff_case(case_id)
    if case_id == "malformed-provider":
        reply = completion("NEW")
        del reply["urgency"]
        from patient_intake.handoff import PatientHandoff
        order_results = []

        def read_empty_order(handle, revision):
            order_results.append(None)
            return None

        port = PatientHandoff(read_verified_order=read_empty_order, read_reviewed_release=lambda day: None)
        with encounter([reply], handoff=port) as flow:
            flow.submit()
            navigations = []
            attempt(lambda: navigations.append(search(flow)), "confirmation_unavailable")
            return dict(current_assessment=has_assessment(flow),
                        verified_order=any(order_results) or any(r.get("destinations") for r in navigations))
    if case_id in {"novel-intake", "negated", "historical", "unknown"}:
        return reviewed_fact(case_id)
    if case_id in {"new-turn-recovery", "outage-after-success"}:
        return outage(case_id)
    if case_id in {"late-first-response", "concurrent-submit", "reset-in-flight"}:
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
            initial = flow.edit(age=10 if case_id == "unsupported-age" else 32,
                                language="fr" if case_id == "unsupported-language" else "en")
            consented = flow.invoke("consent", granted=True)
            result = flow.invoke("assess")
            details["api_states_edit_consent_assess"] = [v["state"] for v in (initial, consented, result)]
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


class SideEffects:
    """Observe real Python entry points across import aliases and worker threads."""

    def __init__(self, app):
        self.counts = Counter()
        self.lock = Lock()
        sys.addaudithook(self.guard)
        # Load the legacy travel package's app.ranking absolute imports from
        # the staged tree. The patient service uses the deployment-root imports.
        sys.path.insert(0, str(app.parent))
        from app.travel import tomtom
        from app.travel.finder import find_campuses
        from app.data_access.warehouse import search_warehouse
        from app.ranking.search import search_from_source, search_facilities
        from app.ranking.urgency import rank_campuses

        sys.path.insert(0, str(app))
        from patient_intake.providers import transport

        self.points = {}
        for group, functions in {
            "finder_calls": (rank_campuses, find_campuses, search_warehouse, search_from_source, search_facilities),
            "route_adapter_entries": (tomtom.TomTomRoutes.routes,),
            "route_attempts": (tomtom.http_transport,),
            "provider_https_entries": (transport._https,),
        }.items():
            for function in functions:
                code = function.__code__
                if app not in Path(code.co_filename).resolve().parents:
                    raise RuntimeError("Counter outside candidate tree")
                self.points[(code.co_filename, code.co_firstlineno)] = group
        exchange = ProviderScript.exchange.__code__
        self.points[(exchange.co_filename, exchange.co_firstlineno)] = "mock_exchange_starts"
        if self.counts:
            raise RuntimeError("Unexpected startup effects")
        sys.setprofile(self.profile)
        threading.setprofile(self.profile)
        # Calibration is separate from every case. Use only empty/disabled
        # local inputs and replace the HTTPS connection with an in-memory reply.
        rank_campuses("dialysis", "routine", [], as_of="2026-11-22",
                      travel_metric="distance_km", travel_budget=1)
        router = tomtom.TomTomRoutes()
        try:
            router.routes((0, 0), [])
            with patch.object(tomtom.http.client, "HTTPSConnection") as connection:
                response = connection.return_value.getresponse.return_value
                response.status, response.read.return_value = 200, b"{}"
                tomtom.http_transport((0, 0), (0, 0), router.config)
        finally:
            router.close()
        try:
            with socket.socket():
                pass
        except PermissionError:
            pass
        with patch.object(transport, "HTTPSConnection") as local_connection:
            response = local_connection.return_value.getresponse.return_value
            response.status, response.read.return_value = 200, b"{}"
            response.getheader.return_value = "application/json"
            worker = Thread(target=transport._https, args=("audit.invalid", "GET", "/", {}, None, 1))
            worker.start()
            worker.join()
        control = ProviderScript([question()], None)
        if control.assess({"source": "calibration"})["state"] != "awaiting_clarification":
            raise AssertionError("mock exchange control failed")
        self.calibration = dict(self.counts)
        if self.calibration != dict(finder_calls=1, route_adapter_entries=1, route_attempts=1, live_network_attempts=1,
                                    provider_https_entries=1, mock_exchange_starts=1):
            raise AssertionError("Counter calibration failed")
        self.counts.clear()

    def profile(self, frame, event, unused):
        if event != "call":
            return
        code = frame.f_code
        group = self.points.get((code.co_filename, code.co_firstlineno))
        if group:
            # A single finder dispatch can call other search/ranking functions.
            if group == "finder_calls":
                parent = frame.f_back
                while parent is not None:
                    code = parent.f_code
                    if self.points.get((code.co_filename, code.co_firstlineno)) == group:
                        return
                    parent = parent.f_back
            with self.lock:
                self.counts[group] += 1

    def guard(self, event, unused):
        if event.startswith("socket."):
            with self.lock:
                self.counts["live_network_attempts"] += 1
            raise PermissionError("offline observer")
        if event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.fork", "os.exec"}:
            with self.lock:
                self.counts["blocked_process_starts"] += 1
            raise PermissionError("offline observer")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, type=Path, help="Staged app/ from the recorded component SHAs")
    cases = json.loads(Path(__file__).with_name("cases.v1.json").read_bytes())["cases"]
    parser.add_argument("--case", choices=[case["id"] for case in cases], help="Replay one frozen case")
    args = parser.parse_args()
    effects = SideEffects(args.app.resolve())
    if args.case:
        cases = [case for case in cases if case["id"] == args.case]
    rows = {}
    per_case_counts = {}
    supplemental = {}
    for case in cases:
        key = case["id"]
        before = effects.counts.copy()
        try:
            details = {}
            measured = runtime_case(key, details)
            if details:
                supplemental[key] = details
            if measured is None:
                rows[key] = {"blocker": "observer_missing"}
                continue
            changes = effects.counts - before
            for counter in ("finder_calls", "route_attempts", "live_network_attempts"):
                if counter in case["expect"]:
                    measured[counter] = changes[counter]
            if key in {"consent", "missing-origin-permission"}:
                measured["unapproved_transmissions"] = measured.get("unapproved_transmissions", 0) + changes["live_network_attempts"]
            rows[key] = {"measured": measured}
            if key in {"no-eligible-campus", "provider-instruction-text"}:
                # Frozen event requires an explicit route permission or a rendered label.
                rows[key]["blocker"] = "unsupported_surface"
            per_case_counts[key] = {name: changes[name] for name in (
                "mock_exchange_starts", "finder_calls", "route_adapter_entries", "route_attempts",
                "provider_https_entries", "live_network_attempts", "blocked_process_starts",
            )}
        except Exception:
            rows[key] = {"error": True, "measured": {"live_network_attempts":
                         effects.counts["live_network_attempts"] - before["live_network_attempts"]}}
    print(json.dumps({"stage": "offline_backend", "observations": rows,
                      "supplemental": supplemental, "calibration": effects.calibration, "side_effects": per_case_counts,
                      "provider_https_entries": effects.counts["provider_https_entries"],
                      "blocked_process_starts": effects.counts["blocked_process_starts"]}, indent=2))
    return int(bool(effects.counts["live_network_attempts"] or effects.counts["blocked_process_starts"]
                    or effects.counts["provider_https_entries"] or any(row.get("error") for row in rows.values())))


if __name__ == "__main__":
    raise SystemExit(main())
