"""The tests must pass with no network at all, so they are not allowed one.

Rather than trusting that every test remembered to fake the upstream, the socket
is taken away for the whole suite: anything but loopback raises. A test that
starts needing the internet fails immediately and says why, instead of passing
on the machine that wrote it and failing on the machine that reviews it.
"""

import socket

import pytest

LOOPBACK = {"127.0.0.1", "::1", "localhost"}


class NetworkUsed(BaseException):
    """Deliberately not an Exception: no `except Exception` may swallow this."""


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def host_of(address) -> str:
        return address[0] if isinstance(address, tuple) else str(address)

    def guard(name, address):
        raise NetworkUsed(
            f"a test tried to reach {host_of(address)} through {name}(); "
            "the upstream must be faked"
        )

    def connect(self, address):
        if host_of(address) not in LOOPBACK:
            guard("connect", address)
        return real_connect(self, address)

    def connect_ex(self, address):
        if host_of(address) not in LOOPBACK:
            guard("connect_ex", address)
        return real_connect_ex(self, address)

    def getaddrinfo(host, *args, **kwargs):
        if host not in LOOPBACK:
            guard("getaddrinfo", host)
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
