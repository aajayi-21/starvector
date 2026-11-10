"""The suite-wide guard of tests/conftest.py: no connection out of this machine."""

import socket

import pytest


def test_a_remote_connection_is_refused() -> None:
    # 192.0.2.1 is a documentation address (RFC 5737): no host answers it.
    with socket.socket() as remote:
        with pytest.raises(RuntimeError, match="no network"):
            remote.connect(("192.0.2.1", 80))
        with pytest.raises(RuntimeError, match="no network"):
            remote.connect_ex(("192.0.2.1", 80))


def test_a_local_connection_is_not_refused() -> None:
    with socket.socket() as server, socket.socket() as client:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        client.connect(server.getsockname())
