"""Server composition for the experimental provider. Configuration is fixed per worker."""

from threading import Lock
from urllib.parse import urlsplit

from .databricks_interview import DatabricksInterviewProvider, _MODELS
from .transport import Budget, Reply, Transport, _https


class _ConfiguredTransport:
    def __init__(self, shared, limit):
        self._shared = shared
        self._limit = Budget(limit)

    def request(self, method, path, *, encounter, **kwargs):
        if not self._limit.take():
            return Reply("budget_exhausted")
        return self._shared.request(method, path, encounter=encounter, **kwargs)


class _WorkspaceExchange:
    """Resolve the workspace and refresh auth inside the transport's bounded worker."""

    def __init__(self):
        self._lock = Lock()
        self._config = None

    def __call__(self, _, method, path, headers, body, timeout):
        with self._lock:
            if self._config is None:
                from databricks.sdk.core import Config
                self._config = Config()
            config = self._config
        url = urlsplit(config.host)
        if (url.scheme != "https" or url.username or url.password or url.port not in (None, 443)
                or not url.hostname or url.path not in ("", "/") or url.query or url.fragment
                or not url.hostname.endswith((".cloud.databricks.com", ".azuredatabricks.net", ".gcp.databricks.com"))):
            raise ValueError("invalid workspace configuration")
        return _https(url.hostname, method, path, {**headers, **config.authenticate()}, body, timeout)


_lock = Lock()
_configuration = None
_providers = {}


def configured_databricks_provider(*, endpoint=None, enabled=False, lane="demo", demo_attempts=0,
                                   test_attempts=0, timeout=5):
    """Return None when disabled. Pass server-owned values only; do not cache in session state."""
    global _configuration
    if enabled is not True:
        return None
    if (endpoint not in _MODELS or lane not in ("demo", "test")
            or type(demo_attempts) is not int or not 0 <= demo_attempts <= 6
            or type(test_attempts) is not int or not 0 <= test_attempts <= 2
            or type(timeout) not in (float, int) or not 0 < timeout <= 10):
        raise ValueError("invalid experimental provider configuration")
    if (demo_attempts if lane == "demo" else test_attempts) == 0:
        return None
    config = (endpoint, demo_attempts, test_attempts, timeout)
    with _lock:
        if _configuration is None:
            shared = Transport(host=None, headers={}, attempts=demo_attempts + test_attempts,
                               exchange=_WorkspaceExchange())
            for group, cap in (("demo", demo_attempts), ("test", test_attempts)):
                _providers[group] = DatabricksInterviewProvider(
                    endpoint=endpoint, lane=group, enabled=True, timeout=timeout,
                    transport=_ConfiguredTransport(shared, cap),
                )
            _configuration = config
        elif _configuration != config:
            raise ValueError("provider configuration changed; restart the worker")
        return _providers[lane]
