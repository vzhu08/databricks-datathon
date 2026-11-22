"""One private publication rehearsal; never use against a production schema."""
from copy import deepcopy

from common import IDS, counts, digest, require
from publication import current, publish


def rehearse(store, batches, base, run_id, as_of, source_metadata, versions):
    """Exercise the real store supplied by the caller, preserving orphan attempts.

    `versions` returns the physical table versions, including publication state.
    Initialization is a separate explicit operator step. Both logical run IDs
    must be new; an interrupted rehearsal needs receipt inspection before retry.
    """
    recovery_id = run_id + "-recovery"
    initial_revision, initial_state = store.read_state()
    require(initial_revision == 0 and initial_state == {"current_run": None, "runs": {}},
            "rehearsal", "requires a newly initialized private validation store")
    original_base = deepcopy(base)
    before = versions()
    first = publish(store, batches, base, run_id, as_of, source_metadata=source_metadata)
    manifest, batch = current(store)
    require(manifest == first and counts(batch) == first["counts"] and digest(batch) == first["batch_sha256"],
            "rehearsal", "first completed readback differs")
    after_first = versions()
    replay = publish(store, batches, base, run_id, as_of, source_metadata=source_metadata)
    require(replay == first and versions() == after_first, "rehearsal", "identical replay wrote another version")

    class DeliberateInterruption(RuntimeError):
        pass

    def interrupt(index):
        if index == 3:
            raise DeliberateInterruption("private rehearsal stopped after three staged tables")

    interrupted = False
    try:
        publish(store, batches, base, recovery_id, as_of, source_metadata=source_metadata, after_write=interrupt)
    except DeliberateInterruption:
        interrupted = True
    require(interrupted, "rehearsal", "failure injection was not reached")
    after_failure = versions()
    failed_manifest, failed_batch = current(store)
    require(failed_manifest == first and failed_batch == batch, "rehearsal", "partial attempt became visible")
    require(store.read_state()[0] == first["revision"] and recovery_id not in store.read_state()[1]["runs"],
            "rehearsal", "failure advanced completed state")

    recovered = publish(store, batches, base, recovery_id, as_of, source_metadata=source_metadata)
    recovered_manifest, recovered_batch = current(store)
    require(recovered_manifest == recovered and recovered_batch == batch,
            "rehearsal", "recovery changed accepted payloads")
    require(recovered["parent_run"] == run_id and recovered["revision"] == first["revision"] + 1,
            "rehearsal", "recovery lineage changed")
    after_recovery = versions()
    require(publish(store, batches, base, recovery_id, as_of, source_metadata=source_metadata) == recovered
            and versions() == after_recovery, "rehearsal", "recovered replay wrote another version")
    require(publish(store, batches, base, run_id, as_of, source_metadata=source_metadata) == first
            and current(store)[0] == recovered and versions() == after_recovery,
            "rehearsal", "old replay moved the completed pointer or wrote new data")
    require(base == original_base and digest(base) == first["base_sha256"] == recovered["base_sha256"],
            "rehearsal", "original base payload/order drift")
    return {"first_manifest": first, "recovery_manifest": recovered,
            "versions": {"initialized": before, "first": after_first, "interrupted": after_failure,
                         "recovered": after_recovery},
            "checks": {"five_table_readback": True, "identical_replay_no_writes": True,
                       "partial_attempt_hidden": True, "failure_after_table": list(IDS)[2],
                       "recovery_same_payloads": True, "old_replay_keeps_current_pointer": True,
                       "base_rows": len(base), "original_payload_drift": 0}}
