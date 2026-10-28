"""Outbound-request safety (SSRF) for publisher postback URLs and webhooks.

validate_outbound_url() only sees the URL text, which is not enough: a hostname can resolve to a
private/loopback/link-local/metadata address (or be written as 2130706433, 0x7f.1, ::ffff:127.0.0.1 ...).
`assert_public_destination()` therefore resolves the host and requires EVERY resulting address to be a global
(public) address; call it immediately before each request. Residual risk (documented): DNS rebinding between this
check and the connect - mitigated by the short window and by never following redirects.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeDestination(ValueError):
    pass


def _is_public(ip) -> bool:
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def check_literal_host(host: str) -> None:
    """Static check used at save time. Rejects non-global IP literals and legacy numeric spellings."""
    host = host.strip("[]").lower()
    try:
        if not _is_public(ipaddress.ip_address(host)):
            raise UnsafeDestination("host is not a public address")
        return
    except ValueError:
        pass
    try:  # decimal / octal / hex / short forms that resolvers still accept (e.g. 2130706433, 0x7f.1)
        socket.inet_aton(host)
    except OSError:
        return  # an ordinary hostname
    raise UnsafeDestination("numeric host spelling is not allowed")


async def assert_public_destination(url: str) -> None:
    parts = urlsplit(url)
    host = (parts.hostname or "").strip("[]")
    if not host:
        raise UnsafeDestination("no host")
    check_literal_host(host)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise UnsafeDestination("host does not resolve") from exc
    if not infos:
        raise UnsafeDestination("host does not resolve")
    for info in infos:
        if not _is_public(ipaddress.ip_address(info[4][0].split("%")[0])):
            raise UnsafeDestination("host resolves to a non-public address")
