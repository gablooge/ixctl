import re

import ipaddress

from django.core.exceptions import ValidationError


def validate_ip4(value):
    try:
        ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError:
        raise ValidationError("Invalid IPv4 Address")


def validate_ip6(value):
    try:
        ipaddress.IPv6Address(value)
    except ipaddress.AddessValueError:
        raise ValidationError("Invalid IPv6 Address")


def validate_prefix(value):
    try:
        ipaddress.ip_network(value)
    except (ipaddress.AddressValueError, ValueError):
        raise ValidationError("Invalid prefix address")
    except ipaddress.NetmaskValueError:
        raise ValidationError("Invalid prefix netmask")


def validate_masklength_range(value):
    if not re.match("^([0-9+\.\.[0-9]+|exact)$", value):
        raise ValidationError("Needs to be [0-9]+..[0-9]+ or 'exact'")
