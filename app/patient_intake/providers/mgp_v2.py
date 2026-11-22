"""Opt-in MGP adapter for Q-validated patient-question.v2 answer records."""

from copy import deepcopy
from math import isfinite
from secrets import token_hex
from threading import Lock

from .mgp import MgpSurveyCandidate, SKIP, _OPTION, _UUID, _early_stop, _failure, _identifier, _reply, _text
from .mgp_lifecycle import AnonymousSurvey
from .transport import Reply


def _finite(value):
    return type(value) is int or (type(value) is float and isfinite(value))


def _rows(rows, label):
    return (type(rows) is list and 1 <= len(rows) <= 16
            and all(type(row) is dict and _identifier(row.get("id"), _OPTION)
                    and _text(row.get(label), 160) for row in rows)
            and len({row["id"] for row in rows}) == len(rows))


class MgpSurveyV2(MgpSurveyCandidate):
    """choices_for returns Q's private current answer row after M's issuance/revision check."""

    def __init__(self, *, units_for=None, stop_guidance=None, **kwargs):
        super().__init__(**kwargs)
        self._units_for = units_for
        self._stop_guidance = stop_guidance

    def _question(self, value):
        if type(value) is not dict or type(value.get("meta")) is not dict:
            return super()._question(value)
        meta = value["meta"]
        if "alerts" in meta:
            stop = _early_stop(meta["alerts"])
            if stop:
                if stop["state"] == "unsupported" and _text(self._stop_guidance, 1000):
                    return _reply("provider_stop", guidance=self._stop_guidance)
                return stop
        wire = value.get("answer_type")
        if wire not in ("age", "duration", "list") and not (
                wire == "symptoms" and meta.get("component") == "group_multiple"):
            result = super()._question(value)
            if result["state"] == "awaiting_clarification":
                optional = self._pending[1]["optional"] or meta.get("component") == "group_single"
                result["question"].update(schema="patient-question.v2", optional=optional)
            return result

        try:
            return self._extended(value, meta, wire)
        except (KeyError, TypeError, ValueError):
            return _reply("unsupported", reason="unsupported")

    def _extended(self, value, meta, wire):
        index = value.get("index")
        prompt = value["question"]["text"]
        required = meta.get("required", True)
        if (not _identifier(value["id"], _OPTION) or not _text(prompt, 500)
                or type(required) is not bool or meta.get("subcomponent") or value.get("user_answer") is not None
                or (index is not None and (type(index) is not int or not 0 <= index < 1024))):
            raise ValueError
        q = dict(schema="patient-question.v2", id=value["id"], prompt=prompt, options=[],
                 optional=wire == "list" and not required)
        private = dict(index=index, wire=wire)
        if wire == "symptoms":
            rows = meta["answers"]
            if not _rows(rows, "name"):
                raise ValueError
            items = []
            for row in rows:
                allowed = row["choices"]
                if not _rows(allowed, "label") or any(c["id"] not in ("present", "absent", "unknown") for c in allowed):
                    raise ValueError
                items.append(dict(id=row["id"], label=row["name"], required=True,
                                  choices=[dict(id=c["id"], label=c["label"]) for c in allowed]))
            q.update(kind="item_presence", items=items)
        elif wire == "list":
            catalog = self._catalog_data(meta["source_list_url"])
            rows = catalog["items"]
            if (catalog.get("complete") is not True or not _rows(rows, "name")
                    or not all(_identifier(catalog[k], _OPTION) for k in ("id", "edition"))):
                raise ValueError
            handles = {token_hex(16): row for row in rows}
            q.update(kind="catalog_selection", selection="multiple",
                     catalog={k: catalog[k] for k in ("id", "edition")},
                     options=[dict(id=h, label=r["name"]) for h, r in handles.items()])
            private["catalog_ids"] = {h: r["id"] for h, r in handles.items()}
        else:
            # Instance configuration attests units, precision and per-unit vendor limits.
            units = self._units_for(self._survey, deepcopy(value)) if self._units_for else None
            valid = ("year", "month") if wire == "age" else ("minute", "hour", "day", "week")
            if not _rows(units, "label"):
                raise ValueError
            for unit in units:
                if (set(unit) != {"id", "label", "min", "max", "integer_only"} or unit["id"] not in valid
                        or not all(_finite(unit[k]) for k in ("min", "max"))
                        or unit["min"] > unit["max"] or type(unit["integer_only"]) is not bool):
                    raise ValueError
                if wire == "age" and (not unit["integer_only"] or type(meta["min_value"]) is not int
                                      or type(meta["max_value"]) is not int or unit["min"] < meta["min_value"]
                                      or unit["max"] > meta["max_value"]):
                    raise ValueError
            if wire == "duration":
                if not _identifier(meta.get("evidence_id"), _OPTION):
                    raise ValueError
                private["evidence_id"] = meta["evidence_id"]
            q.update(kind="quantity", units=units)
        token = token_hex(16)
        self._pending = token, {**deepcopy(q), **private}
        return _reply("awaiting_clarification", question=q, continuation=token)

    def _answer_payload(self, question, row):
        if (type(row) is not dict or row.get("provider_question_id") != question["id"]
                or row.get("kind") != question["kind"] or not _text(row.get("issuance_id"), 128)
                or "answer" not in row or type(row.get("skipped", False)) is not bool):
            return None
        if question["kind"] == "catalog_selection" and row.get("catalog") != question["catalog"]:
            return None
        answer = row["answer"]
        if row.get("skipped"):
            if answer is not None:
                return None
            return super()._answer_payload(question, SKIP)
        if question["kind"] == "item_presence":
            rows = answer.get("items") if type(answer) is dict else None
            if type(rows) is not list or len(rows) != len(question["items"]):
                return None
            payload = []
            for item, selection in zip(question["items"], rows):
                if (type(selection) is not dict or selection.get("id") != item["id"]
                        or selection.get("presence") not in [c["id"] for c in item["choices"]]):
                    return None
                payload.append(dict(id=item["id"], choice_id=selection["presence"]))
            return {"answer": payload}
        if question["kind"] == "quantity":
            if type(answer) is not dict or not _finite(answer.get("value")):
                return None
            n = answer["value"]
            for unit in question["units"]:
                if (unit["id"] == answer.get("unit_id") and unit["min"] <= n <= unit["max"]
                        and (not unit["integer_only"] or type(n) is int)):
                    qty = dict(unit=unit["id"], value=n)
                    return {"answer": qty if question["wire"] == "age" else
                            [dict(id=question["evidence_id"], duration=qty)]}
            return None
        if question["kind"] == "catalog_selection":
            if not self._valid_choices({**question, "kind": "multiple"}, answer):
                return None
            return {"answer": [dict(id=question["catalog_ids"][h]) for h in answer]}
        return super()._answer_payload(question, answer)


class OwnedMgpSurvey:
    """Construct inside M's local factory. O owns the reservation after attachment."""

    def __init__(self, *, mailbox, session, budget, reconciled, prefill_demographics=None,
                 enabled=False, **options):
        self._enabled = enabled is True
        self._reconciled = reconciled
        self._prefill_demographics = prefill_demographics
        self._interview = None
        self._expected_answers = None
        self._turn = Lock()
        self._session = session
        self._candidate = MgpSurveyV2(
            transport=self, budget=budget, survey_for=self._bound_survey,
            choices_for=self._answer_record, enabled=self._enabled, **options)
        self.cleanup_reservation = mailbox.reserve()
        self._survey = AnonymousSurvey(session, budget=budget, reservation=self.cleanup_reservation)

    def _bound_survey(self, data):
        if self.cleanup_reservation.active and data["interview_id"] == self._interview and self._reconciled(data) is True:
            return self._survey.survey_id
        return None

    @staticmethod
    def _answer_record(data, question_id):
        row = data["answers"][-1]
        return row if row.get("provider_question_id") == question_id else None

    def request(self, method, path, *, payload=None, encounter):
        if not self.cleanup_reservation.active:
            return Reply("unavailable")
        return self._session.request(method, path, payload=payload, encounter=encounter)

    def retire(self):
        self.cleanup_reservation.retire()

    def assess(self, interview_data, *, continuation=None):
        if not self._enabled or not self._turn.acquire(blocking=False):
            return _reply("provider_unavailable", reason="unavailable")
        try:
            if not self.cleanup_reservation.active:
                return _reply("provider_unavailable", reason="unavailable")
            if self._interview is None:
                if (continuation is not None or not _text(interview_data.get("interview_id"), 128)
                        or self._reconciled(interview_data) is not True):
                    return _reply("unsupported", reason="unsupported_correction")
                if interview_data.get("answers") != []:
                    return _reply("unsupported", reason="unsupported_correction")
                self._interview = interview_data["interview_id"]
                reviews = interview_data.get("patient_evidence", [])
                demographics = self._prefill_demographics(interview_data) if reviews and self._prefill_demographics else None
                status = self._survey.create(confirmed_initial=reviews, prefill_enabled=demographics is not None,
                                             demographics=demographics)
                if status == "unsupported_correction":
                    self.retire()
                    return _reply("unsupported", reason=status)
                if status != "created":
                    self.retire()
                    return _failure(Reply(status))
            elif len(interview_data.get("answers", ())) != self._expected_answers:
                return _reply("unsupported", reason="unsupported_correction")
            result = self._candidate.assess(interview_data, continuation=continuation)
            if self.cleanup_reservation.active:
                if result["state"] == "awaiting_clarification":
                    self._expected_answers = len(interview_data["answers"]) + 1
                return result
        except Exception:
            self.retire()
        finally:
            self._turn.release()
        return _reply("provider_unavailable", reason="unavailable")


def dispose_claim(mailbox, *, cleanup_session, cleanup_budget):
    """Process one claim with a separately configured cleanup transport and quota."""
    claim = mailbox.claim()
    if claim is None:
        return False
    disposed = []
    try:
        for role, identifier in claim.resources:
            if role not in ("surveys", "patients", "users") or not _identifier(identifier, _UUID):
                break
            reply = cleanup_session.request("DELETE", f"/api/mgp/v1/{role}/{identifier}", encounter=cleanup_budget)
            if reply.status not in ("empty", "not_found"):
                break
            disposed.append(role)
    finally:
        mailbox.finish(claim, disposed=tuple(disposed), retryable=True)
    return True
