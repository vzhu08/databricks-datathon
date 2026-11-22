"""Launch an isolated Streamlit candidate with the documented synthetic compose seam."""

import argparse
import ipaddress
import json
from pathlib import Path
import sys
import subprocess
import time


def guard(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        destination = args[0] if event == "socket.getaddrinfo" else args[-1]
        host = destination[0] if isinstance(destination, tuple) else destination
        if host == "localhost":
            return
        try:
            if ipaddress.ip_address(host).is_loopback:
                return
        except (ValueError, TypeError):
            pass
        print("AUDIT_EXTERNAL_ATTEMPT", flush=True)
        raise PermissionError("local browser fixture only")


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    parser.add_argument("--port", type=int, default=18523)
    parser.add_argument("--controls", type=Path, required=True, help="New private directory for the test clock and barrier")
    args = parser.parse_args()
    controls = args.controls.resolve()
    controls.mkdir(mode=0o700, exist_ok=False)
    (controls / "clock").write_text("0")
    from runtime_binding import SideEffects

    class BrowserEffects(SideEffects):
        calibrated = False

        def guard(self, event, args):
            if not self.calibrated:
                return super().guard(event, args)
            guard(event, args)

        def profile(self, frame, event, unused):
            if event == "call" and self.calibrated:
                code = frame.f_code
                group = self.points.get((code.co_filename, code.co_firstlineno))
                if group and group != "mock_exchange_starts":
                    print("AUDIT_BOUNDARY", group, flush=True)
            super().profile(frame, event, unused)

    app = args.app.resolve()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=app, text=True).strip()
    subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "."], cwd=app, check=True)
    print("AUDIT_BUILD", sha, f"http://127.0.0.1:{args.port}", flush=True)
    effects = BrowserEffects(app)
    effects.calibrated = True
    print("AUDIT_CALIBRATED", json.dumps(effects.calibration, sort_keys=True), flush=True)
    from streamlit.web import cli
    import streamlit as st
    from runtime_binding import ProviderScript, completion, consultation, evidence, question

    app = args.app.resolve()
    sys.path.insert(0, str(app))
    import patient_ui
    from patient_intake import PatientIntakeService
    from patient_intake.handoff import PatientHandoff
    from patient_intake.interview import PatientInterview

    from patient_intake import session as store
    store.monotonic = lambda: float((controls / "clock").read_text())
    original_reset = store.PatientSession.reset

    def record_reset(owner, handle):
        original_reset(owner, handle)
        if (controls / "held").exists() and not (controls / "release").exists():
            (controls / "reset").touch()

    store.PatientSession.reset = record_reset
    original = patient_ui.compose

    def compose():
        case = st.query_params.get("audit", "no-configuration")
        if case == "no-configuration":
            return original()
        invalid = completion("INVALID")
        del invalid["urgency"]
        stop = {"state": "provider_stop", "guidance": "Synthetic provider stop guidance"}
        urgent = dict(completion("Synthetic emergency guidance"), state="urgent", urgency="emergency")
        structured = dict(question()["question"], schema="patient-question.v2", optional=True)
        scripts = {
            "qualified-completion": [consultation()],
            "unsupported-age": [],
            "provider-emergency": [urgent],
            "malformed-provider": [invalid],
            "outage-after-success": [completion("Earlier synthetic result"), TimeoutError()],
            "budget-exhausted": [completion("Earlier synthetic result")],
            "question-loop": [question(), question()],
            "provider-instruction-text": [question("An ordinary referral is approved.")],
            "contradiction": [evidence(), evidence("absent"), completion("NEW")],
            "provider-stop": [stop],
            "optional-skip": [dict(state="awaiting_clarification", question=structured), completion("Explicit skip received")],
            "same-count-edit": [question(), completion("Earlier synthetic result"), question(), completion("New synthetic result")],
            "privacy-sinks": [evidence(), completion("NEW"), RuntimeError("CANARY-DESCRIPTION-S1")],
            "shared-cache": [completion("Session A synthetic result")],
        }
        if case == "terminated-empty":
            from v2_observer import Wire, prebound
            def empty_question(method, path, payload):
                print("AUDIT_EXCHANGE terminated-empty", flush=True)
                if method != "GET" or not path.endswith("/questions/current") or payload is not None:
                    raise ValueError("unexpected empty-question request")
                return 204, None

            wire = Wire(empty_question)
            from patient_intake.providers.mgp import PROVIDER_ID, PROVIDER_VERSION
            return PatientIntakeService(interview=PatientInterview(), provider=prebound(wire),
                                        provider_identity=(PROVIDER_ID, PROVIDER_VERSION)), "Synthetic test provider"
        def delayed():
            (controls / "held").touch()
            deadline = time.monotonic() + 4
            while not (controls / "release").exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            (controls / "returned").touch()
            return completion("Old delayed result")

        scripts["reset-in-flight"] = [delayed]
        scripts["expired-session"] = [completion("Old expired result")]
        class ObservedProvider(ProviderScript):
            def exchange(self, *exchange_args):
                if case == "optional-skip" and self.requests:
                    row = json.loads(exchange_args[4])["answers"][-1]
                    if row.get("skipped") is not True or row["answer"] is not None:
                        raise ValueError("optional skip not preserved")
                print("AUDIT_EXCHANGE", case, flush=True)
                return super().exchange(*exchange_args)
        if case == "privacy-sinks":
            scripts[case][0]["question"]["evidence"]["label"] = "CANARY-FACT-S2"
        stub = ObservedProvider(scripts[case], {"X-Audit-Key": "CANARY-KEY-S3"} if case == "privacy-sinks" else None)
        budget = {"budget-exhausted": 1, "question-loop": 2}.get(case, 8)
        return PatientIntakeService(
            interview=PatientInterview(supported_age_range=(18, 85), supported_languages=["en"]),
            provider=stub, provider_identity=stub.identity, handoff=PatientHandoff(), max_turns=budget,
        ), "Synthetic test provider"

    patient_ui.compose = compose
    sys.argv = ["streamlit", "run", str(app / "app.py"), "--server.address=127.0.0.1",
                f"--server.port={args.port}", "--server.headless=true", "--server.fileWatcherType=none",
                "--browser.gatherUsageStats=false"]
    cli.main()


if __name__ == "__main__":
    run()
