"""Local SQLite protocol simulation. This is NOT live Delta verification."""
import json
import sqlite3

from common import IDS, canonical, digest, empty, require


class SimulatedStore:
    def __init__(self, path):
        self.connection = sqlite3.connect(path)
        with self.connection:
            self.connection.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, revision INTEGER, payload TEXT)")
            self.connection.execute("INSERT OR IGNORE INTO state VALUES (1, 0, ?)",
                                    (canonical({"current_run": None, "runs": {}}),))
            self.connection.execute("CREATE TABLE IF NOT EXISTS stage (table_name TEXT, attempt TEXT, payload TEXT, PRIMARY KEY(table_name, attempt))")

    def close(self):
        self.connection.close()

    def read_state(self):
        revision, payload = self.connection.execute("SELECT revision, payload FROM state WHERE id=1").fetchone()
        return revision, json.loads(payload)

    def write_stage(self, table, attempt, rows):
        with self.connection:
            self.connection.execute("INSERT INTO stage VALUES (?, ?, ?)", (table, attempt, canonical(rows)))
        return 0  # Simulation has isolated immutable rows instead of Delta versions.

    def read_completed(self, manifest):
        result = empty()
        for table in IDS:
            row = self.connection.execute("SELECT payload FROM stage WHERE table_name=? AND attempt=?",
                                          (table, manifest["attempt_id"])).fetchone()
            require(row is not None, "simulation.stage", "missing table")
            result[table] = json.loads(row[0])
        if "batch_sha256" in manifest:
            require(digest(result) == manifest["batch_sha256"], "simulation.stage", "completed hash mismatch")
        return result

    def compare_and_swap(self, revision, state):
        with self.connection:
            cursor = self.connection.execute("UPDATE state SET revision=revision+1, payload=? WHERE id=1 AND revision=?",
                                             (canonical(state), revision))
        return cursor.rowcount == 1
