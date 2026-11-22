"""Summarize captures of synthetic markers without retaining any captured payload."""

# Browser storage and URLs are checked independently to avoid an empty capture
# of one surface being credited as a clean observation of another.
SURFACES = frozenset({
    "app_log", "traceback", "telemetry", "url_history", "rendered_error",
    "local_storage", "session_storage", "indexed_db", "cache_storage", "client_assets",
})


class CanaryProbe:
    def __init__(self, *, markers, capture_marker):
        tokens = (*markers, capture_marker)
        if len(tokens) < 2 or any(type(token) is not bytes or not token for token in tokens):
            raise ValueError("Expected nonempty synthetic byte markers")
        if any(a in b for i, a in enumerate(tokens) for j, b in enumerate(tokens) if i != j):
            raise ValueError("Markers must be distinct and nonoverlapping")
        self.markers = tokens[:-1]
        self.capture_marker = capture_marker
        self.observed = set()
        self.matches = 0

    def capture(self, surface, decoded_bytes):
        """Feed complete decoded records from the isolated test sinks."""
        if surface not in SURFACES or type(decoded_bytes) is not bytes:
            raise ValueError("Unknown surface or undecoded capture")
        if self.capture_marker in decoded_bytes:
            self.observed.add(surface)
        self.matches += sum(decoded_bytes.count(token) for token in self.markers)

    def measurements(self):
        return {"canary_matches": self.matches, "required_sinks_observed": self.observed == SURFACES}

    def missing_surfaces(self):
        return sorted(SURFACES - self.observed)
