"""F5: repo-wide test network guard.

Every test in this suite is expected to mock its network calls -- provider
SDK clients, `requests.get`, etc (see the file-level docstrings in
test_market_data.py, test_structured_requests.py, test_model_registry.py
for the established patterns). Nothing enforced that suite-wide until now:
a test that FORGOT to mock a network call would just... make it, silently,
possibly burning real API credits or hanging on a live socket in CI.

The T12 implementer's reflection flagged a near-miss of the opposite kind:
its own autouse stub fixture (test_market_data.py's `_stub_cmc_social_fetches`)
silently neutralized functions that OTHER tests in the same file needed to
exercise directly, and only careful scoping (each test that needs the real
function restores it explicitly, see `_REAL_FETCH_CMC_STATUS` /
`_REAL_FETCH_SOCIAL_STATUS`) avoided a false sense of coverage. The lesson
carried forward here: an autouse fixture that blocks something must FAIL
LOUDLY and NAME THE OFFENDING TEST when its target is hit, never silently
swallow the call -- so a forgotten mock shows up as an obvious, readable
test failure instead of a hung/slow/flaky one, and never as a false pass.

This fixture patches at the socket level (below `requests`, below every
provider SDK's HTTP client) so it catches ANY real network attempt
regardless of which library made it, not just the ones this repo happens
to import today:
    - socket.socket.connect / connect_ex  (a raw connect() attempt)
    - socket.create_connection            (what urllib3/requests uses)
    - socket.getaddrinfo                  (DNS resolution -- catches an
                                             attempt before the connect())

Opt-out: `@pytest.mark.allow_network` on a test (or a whole class/module)
skips the guard for that scope. Nothing in the suite needs it today --
it's reserved for a future deliberate integration test that hits a real
endpoint on purpose (the kind of test this repo's process lessons call
"probe before you migrate" scripts, run by hand, not part of `pytest tests/`).

Verified network-free: `pytest tests/ -q` passes unchanged with this guard
active (see AGENTS.md "Verify before and after" -- the full suite runs in
a couple of seconds, consistent with zero real network round-trips).
"""
import socket

import pytest

ALLOW_NETWORK_MARKER = "allow_network"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        f"{ALLOW_NETWORK_MARKER}: opt this test out of the repo-wide "
        "network guard (tests/conftest.py) for a deliberate integration "
        "test that hits a real network endpoint. Nothing in the suite "
        "needs this today.",
    )


class NetworkBlocked(RuntimeError):
    """Raised in place of a real network call from inside the test suite.

    Seeing this means a test tried to reach the network without mocking
    the call first. Either mock it (requests.get, the relevant
    llm_utils.<Provider>Client / SDK client, coinmarketcaputil, ...) or, if
    this is a deliberate live-integration test, mark it
    @pytest.mark.allow_network.
    """


def _blocked(test_id, what):
    def _raise(*args, **kwargs):
        raise NetworkBlocked(
            f"tests/conftest.py network guard: {test_id} attempted a real "
            f"network call via {what}. Mock the network boundary instead "
            "(see test_market_data.py / test_model_registry.py for the "
            "established patterns), or mark the test "
            "@pytest.mark.allow_network if it deliberately needs a live "
            "connection."
        )
    return _raise


@pytest.fixture(autouse=True)
def _isolated_rate_limit_state_dir(tmp_path, monkeypatch):
    """WS-7: marketdata.py's LunarCrush throttle/cache (ratelimit.py) share
    a state dir across processes, resolved from TRADBOT_STATE_DIR (falling
    back to ~/.cache/tradbot). Without this, the suite would default to
    that fallback -- besides touching a real path on the dev machine,
    tests running in the same session would leak rate-limit timestamps and
    cached responses into each other via that shared file. Redirect every
    test to its own tmp_path so state never crosses test boundaries and
    never touches the real cache dir.
    """
    monkeypatch.setenv('TRADBOT_STATE_DIR', str(tmp_path / 'tradbot_state'))


@pytest.fixture(autouse=True)
def _block_real_network(request, monkeypatch):
    """Autouse for every test collected under tests/ -- see module
    docstring. Function-scoped: monkeypatch reverts these patches after
    each test regardless of pass/fail, so the guard can never leak into
    (or be weakened by) a later test."""
    if request.node.get_closest_marker(ALLOW_NETWORK_MARKER):
        return
    test_id = request.node.nodeid
    monkeypatch.setattr(socket.socket, "connect", _blocked(test_id, "socket.socket.connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked(test_id, "socket.socket.connect_ex"))
    monkeypatch.setattr(socket, "create_connection", _blocked(test_id, "socket.create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", _blocked(test_id, "socket.getaddrinfo"))
