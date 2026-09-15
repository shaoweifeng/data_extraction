import ipaddress

from django.conf import settings


def _parse_address(value: str):
    try:
        return ipaddress.ip_address((value or '').strip())
    except ValueError:
        return None


def _trusted_networks():
    networks = []
    for value in getattr(settings, 'TRUSTED_PROXY_IPS', []):
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            continue
    return networks


def _is_trusted(address, networks) -> bool:
    return any(address in network for network in networks)


def get_client_ip(request) -> str:
    """Resolve the closest untrusted client without trusting spoofed headers."""
    remote = _parse_address(request.META.get('REMOTE_ADDR', ''))
    if remote is None:
        return '0.0.0.0'

    trusted = _trusted_networks()
    if not _is_trusted(remote, trusted):
        return str(remote)

    raw_forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if not raw_forwarded:
        return str(remote)

    forwarded = [_parse_address(item) for item in raw_forwarded.split(',')]
    if not forwarded or any(item is None for item in forwarded):
        return str(remote)

    for address in reversed([*forwarded, remote]):
        if not _is_trusted(address, trusted):
            return str(address)
    return str(forwarded[0])
