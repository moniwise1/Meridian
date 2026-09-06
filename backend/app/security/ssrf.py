"""
Outbound-connection host guard (SSRF).

A data-source connection's `host` and `port` are supplied by a tenant admin
and then dialed *from the backend's own network*. Without a guard, an
authenticated (paying, admin) user can point a connection at
`169.254.169.254`, `127.0.0.1`, or an internal `10.x` address and use
Meridian as a foothold: a working internal port scanner (does something
DB-protocol-ish answer on host:port?) and, if an internal database has weak
or no auth, a way to actually read it.

This blocks connections whose host resolves to a private, loopback,
link-local, CGNAT, multicast, or otherwise non-public address. For a
SaaS deployment that's the right default - a customer's real database has
to be reachable from the backend's cloud egress, i.e. publicly routable.
A self-hosted deployment that genuinely needs to reach a database on a
private network sets ALLOW_PRIVATE_CONNECTION_HOSTS=true to opt out.

Checked both when a connection is created (routes_connections.py) and when
a connector is built to run a query (planner.build_connector) - the second
check narrows the DNS-rebinding window where a name resolves to a public
address at creation time and a private one later.
"""
import ipaddress
import socket

from app.config import settings

# 100.64.0.0/10 (RFC 6598 carrier-grade NAT) is NOT flagged by
# ipaddress.is_private, but it's used for provider-internal addressing
# (and Alibaba Cloud's metadata endpoint 100.100.100.100 lives in it),
# so block it explicitly.
_CGNAT_V4 = ipaddress.ip_network("100.64.0.0/10")


class BlockedHostError(Exception):
    pass


def _addr_is_blocked(ip: ipaddress._BaseAddress) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (ip.version == 4 and ip in _CGNAT_V4)
    )


def check_connection_host(host: str) -> None:
    """Raise BlockedHostError if `host` is empty, unresolvable, or resolves
    to any non-public address. No-op when ALLOW_PRIVATE_CONNECTION_HOSTS is
    set."""
    if settings.allow_private_connection_hosts:
        return
    host = (host or "").strip()
    if not host:
        raise BlockedHostError("A connection host is required.")

    # A literal IP still goes through getaddrinfo (which just returns it),
    # so both the hostname and the literal-IP cases are covered here.
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise BlockedHostError(
            f"Could not resolve '{host}'. Use a hostname or public IP that this service can reach."
        )

    resolved = {info[4][0] for info in infos}
    if not resolved:
        raise BlockedHostError(f"Could not resolve '{host}'.")

    for raw in resolved:
        try:
            ip = ipaddress.ip_address(raw.split("%")[0])  # strip any zone id
        except ValueError:
            raise BlockedHostError(f"'{host}' resolved to an address that can't be parsed ({raw}).")
        if _addr_is_blocked(ip):
            raise BlockedHostError(
                f"'{host}' resolves to a non-public address ({ip}). Connect a database that is "
                f"reachable over the public internet, or set ALLOW_PRIVATE_CONNECTION_HOSTS on a "
                f"self-hosted deployment that needs private-network access."
            )
