"""CIDR and subnet validation utilities."""

from __future__ import annotations

import ipaddress
import re
from typing import Optional


# Regex for basic AWS region format: e.g. us-east-1, eu-central-1, ap-southeast-2
_REGION_RE = re.compile(r"^[a-z]+-[a-z]+-\d+$")

# Regex for basic AWS AZ format: e.g. us-east-1a, eu-central-1b
_AZ_RE = re.compile(r"^[a-z]+-[a-z]+-\d+[a-z]$")


def validate_cidr(cidr: str, is_vpc: bool = False) -> tuple[bool, Optional[str]]:
    """Validate that a string is a valid IPv4 CIDR block.

    If `is_vpc` is True, enforce AWS VPC restrictions: prefix length
    must be between /16 and /28.

    Returns (True, None) if valid, or (False, error_message) if invalid.
    """
    try:
        net = ipaddress.IPv4Network(cidr, strict=True)
    except ValueError as exc:
        return False, f"Invalid CIDR block: {exc}"
    if is_vpc:
        if net.prefixlen < 16 or net.prefixlen > 28:
            return False, (
                f"VPC CIDR prefix length must be between /16 and /28, "
                f"got /{net.prefixlen}"
            )
    return True, None


def validate_cidr_is_subnet(cidr: str) -> tuple[bool, Optional[str]]:
    """Validate a CIDR is a valid subnet prefix (not a single IP, mask >= /28)."""
    valid, err = validate_cidr(cidr)
    if not valid:
        return valid, err
    net = ipaddress.IPv4Network(cidr, strict=True)
    if net.prefixlen < 16 or net.prefixlen > 28:
        return (
            False,
            f"Subnet prefix length must be between /16 and /28, got /{net.prefixlen}",
        )
    return True, None


def validate_subnet_contained_in_vpc(
    vpc_cidr: str, subnet_cidr: str
) -> tuple[bool, Optional[str]]:
    """Check whether subnet_cidr is fully contained within vpc_cidr."""
    vpc_valid, err = validate_cidr(vpc_cidr)
    if not vpc_valid:
        return False, err
    subnet_valid, err = validate_cidr(subnet_cidr)
    if not subnet_valid:
        return False, err

    vpc_net = ipaddress.IPv4Network(vpc_cidr, strict=False)
    subnet_net = ipaddress.IPv4Network(subnet_cidr, strict=False)

    if subnet_net.subnet_of(vpc_net):
        return True, None
    return False, f"{subnet_cidr} is not contained within {vpc_cidr}"


def validate_no_overlapping_subnets(cidrs: list[str]) -> tuple[bool, Optional[str]]:
    """Check that no two CIDRs in the list overlap."""
    networks = []
    for cidr in cidrs:
        valid, err = validate_cidr(cidr)
        if not valid:
            return False, err
        networks.append(ipaddress.IPv4Network(cidr, strict=False))

    for i in range(len(networks)):
        for j in range(i + 1, len(networks)):
            if networks[i].overlaps(networks[j]):
                return (
                    False,
                    f"Overlapping subnets detected: {networks[i]} and {networks[j]}",
                )
    return True, None


def validate_region(region: str) -> tuple[bool, Optional[str]]:
    """Validate a basic AWS region string."""
    if not _REGION_RE.match(region):
        return (
            False,
            f"Invalid region format: {region}. Expected format like 'us-east-1'",
        )
    return True, None


def validate_availability_zone(az: str) -> tuple[bool, Optional[str]]:
    """Validate a basic AWS availability zone string."""
    if not _AZ_RE.match(az):
        return False, f"Invalid AZ format: {az}. Expected format like 'us-east-1a'"
    return True, None


def validate_duplicate_subnet_names(subnets: list[dict]) -> tuple[bool, Optional[str]]:
    """Check that no two subnets share the same name."""
    names = [s["name"] for s in subnets]
    seen: set[str] = set()
    for name in names:
        if name in seen:
            return False, f"Duplicate subnet name: {name}"
        seen.add(name)
    return True, None
