"""DNS validation and IP-pinned HTTP transport for approved public sources."""

import ipaddress
import socket
from typing import Callable, Iterable, Optional, Sequence, Tuple, Union

import httpcore
import httpx

Resolver = Callable[[str, int], Sequence[str]]


class DNSResolutionError(OSError):
    """The approved hostname could not be resolved safely."""


class UnsafeResolvedAddress(ValueError):
    """At least one DNS answer is not globally routable."""


def is_safe_public_address(
    address: Union[ipaddress.IPv4Address, ipaddress.IPv6Address]
) -> bool:
    """Require globally routable unicast rather than relying on is_global alone."""
    return bool(
        address.is_global
        and not address.is_loopback
        and not address.is_private
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_unspecified
        and not address.is_reserved
    )


def system_resolver(host: str, port: int) -> Sequence[str]:
    """Resolve TCP addresses without retaining socket-family details."""
    answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(answer[4][0]) for answer in answers]


def resolve_public_addresses(
    host: str,
    port: int,
    *,
    resolver: Resolver = system_resolver,
) -> Tuple[str, ...]:
    """Return unique public IPs only; reject the whole answer set otherwise."""
    try:
        answers = resolver(host, port)
    except (socket.gaierror, OSError) as exc:
        raise DNSResolutionError("approved source DNS resolution failed") from exc
    if not answers:
        raise DNSResolutionError("approved source DNS returned no addresses")

    normalized = []
    for value in answers:
        try:
            address = ipaddress.ip_address(str(value).split("%", 1)[0])
        except ValueError as exc:
            raise DNSResolutionError("approved source DNS returned an invalid address") from exc
        if not is_safe_public_address(address):
            raise UnsafeResolvedAddress("approved source DNS returned a non-global address")
        normalized.append(address.compressed)
    return tuple(sorted(set(normalized)))


class PinnedNetworkBackend(httpcore.NetworkBackend):
    """Connect to one checked IP while preserving the request hostname for TLS."""

    def __init__(
        self,
        *,
        approved_host: str,
        approved_port: int,
        pinned_ip: str,
        backend: Optional[httpcore.NetworkBackend] = None,
    ) -> None:
        self._approved_host = approved_host.lower().rstrip(".")
        self._approved_port = approved_port
        self._pinned_ip = ipaddress.ip_address(pinned_ip).compressed
        if not is_safe_public_address(ipaddress.ip_address(self._pinned_ip)):
            raise UnsafeResolvedAddress("pinned address must be globally routable")
        self._backend = backend or httpcore.SyncBackend()

    def connect_tcp(
        self,
        host,
        port,
        timeout=None,
        local_address=None,
        socket_options=None,
    ):
        requested_host = host.decode("ascii") if isinstance(host, bytes) else str(host)
        if (
            requested_host.lower().rstrip(".") != self._approved_host
            or port != self._approved_port
        ):
            raise httpcore.ConnectError("connection endpoint does not match the approved origin")
        return self._backend.connect_tcp(
            self._pinned_ip,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )


class _CoreResponseStream(httpx.SyncByteStream):
    def __init__(self, stream: Iterable[bytes]) -> None:
        self._stream = stream

    def __iter__(self):
        yield from self._stream

    def close(self) -> None:
        close = getattr(self._stream, "close", None)
        if close is not None:
            close()


class PinnedHTTPTransport(httpx.BaseTransport):
    """HTTPX transport backed by a one-IP HTTPCore connection pool."""

    def __init__(
        self,
        *,
        approved_host: str,
        pinned_ip: str,
        approved_port: int = 443,
        ssl_context,
        network_backend: Optional[httpcore.NetworkBackend] = None,
    ) -> None:
        backend = PinnedNetworkBackend(
            approved_host=approved_host,
            approved_port=approved_port,
            pinned_ip=pinned_ip,
            backend=network_backend,
        )
        self._pool = httpcore.ConnectionPool(
            ssl_context=ssl_context,
            max_connections=1,
            max_keepalive_connections=0,
            http1=True,
            http2=False,
            retries=0,
            network_backend=backend,
        )
        self._approved_host = approved_host.lower().rstrip(".")
        self._approved_port = approved_port

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if (
            request.url.scheme != "https"
            or (request.url.host or "").lower().rstrip(".") != self._approved_host
            or (request.url.port or 443) != self._approved_port
        ):
            raise httpx.UnsupportedProtocol("request does not match the pinned HTTPS origin")
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        response = self._pool.handle_request(core_request)
        return httpx.Response(
            status_code=response.status,
            headers=response.headers,
            stream=_CoreResponseStream(response.stream),
            extensions=response.extensions,
        )

    def close(self) -> None:
        self._pool.close()
