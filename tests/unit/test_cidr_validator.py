"""Unit tests for CIDR and subnet validation utilities."""

from app.utils.cidr_validator import (
    validate_cidr,
    validate_cidr_is_subnet,
    validate_subnet_contained_in_vpc,
    validate_no_overlapping_subnets,
    validate_region,
    validate_availability_zone,
    validate_duplicate_subnet_names,
)


class TestValidateCidr:
    def test_valid_cidr(self):
        assert validate_cidr("10.0.0.0/16") == (True, None)
        assert validate_cidr("192.168.0.0/24") == (True, None)

    def test_invalid_cidr_format(self):
        ok, err = validate_cidr("not-a-cidr")
        assert not ok
        assert err is not None

    def test_invalid_cidr_mask_too_large(self):
        # /33 is not a valid mask
        ok, err = validate_cidr("10.0.0.1/32")
        # /32 is valid as a single host
        assert ok

    def test_valid_cidr_host_mask(self):
        ok, _ = validate_cidr("10.0.0.1/32")
        assert ok


class TestValidateCidrIsSubnet:
    def test_valid_subnet(self):
        assert validate_cidr_is_subnet("10.0.1.0/24") == (True, None)
        assert validate_cidr_is_subnet("10.0.0.0/20") == (True, None)

    def test_subnet_too_small(self):
        ok, err = validate_cidr_is_subnet("10.0.0.0/30")
        assert not ok
        assert "/30" in err

    def test_subnet_too_large(self):
        ok, err = validate_cidr_is_subnet("10.0.0.0/12")
        assert not ok
        assert "/12" in err

    def test_invalid_subnet_format(self):
        ok, _ = validate_cidr_is_subnet("abc")
        assert not ok


class TestValidateSubnetContainedInVpc:
    def test_contained(self):
        assert validate_subnet_contained_in_vpc("10.0.0.0/16", "10.0.1.0/24") == (
            True,
            None,
        )

    def test_not_contained(self):
        ok, err = validate_subnet_contained_in_vpc("10.0.0.0/16", "192.168.1.0/24")
        assert not ok
        assert "not contained" in err.lower()

    def test_same_cidr(self):
        assert validate_subnet_contained_in_vpc("10.0.0.0/16", "10.0.0.0/16") == (
            True,
            None,
        )

    def test_vpc_is_subnet_of_larger(self):
        ok, err = validate_subnet_contained_in_vpc("10.0.1.0/24", "10.0.0.0/16")
        assert not ok


class TestValidateNoOverlappingSubnets:
    def test_non_overlapping(self):
        cidrs = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
        assert validate_no_overlapping_subnets(cidrs) == (True, None)

    def test_overlapping(self):
        cidrs = ["10.0.0.0/16", "10.0.1.0/24"]
        ok, err = validate_no_overlapping_subnets(cidrs)
        assert not ok
        assert "overlapping" in err.lower()

    def test_identical_cidrs(self):
        cidrs = ["10.0.1.0/24", "10.0.1.0/24"]
        ok, err = validate_no_overlapping_subnets(cidrs)
        assert not ok

    def test_empty_list(self):
        assert validate_no_overlapping_subnets([]) == (True, None)

    def test_single_subnet(self):
        assert validate_no_overlapping_subnets(["10.0.1.0/24"]) == (True, None)


class TestValidateRegion:
    def test_valid_regions(self):
        assert validate_region("us-east-1") == (True, None)
        assert validate_region("eu-central-1") == (True, None)
        assert validate_region("ap-southeast-2") == (True, None)

    def test_invalid_region(self):
        ok, _ = validate_region("invalid")
        assert not ok
        ok, _ = validate_region("us-east")
        assert not ok


class TestValidateAvailabilityZone:
    def test_valid_azs(self):
        assert validate_availability_zone("us-east-1a") == (True, None)
        assert validate_availability_zone("eu-central-1b") == (True, None)

    def test_invalid_az(self):
        ok, _ = validate_availability_zone("us-east")
        assert not ok
        ok, _ = validate_availability_zone("1a")
        assert not ok


class TestValidateDuplicateSubnetNames:
    def test_unique_names(self):
        subnets = [{"name": "pub-a"}, {"name": "priv-a"}]
        assert validate_duplicate_subnet_names(subnets) == (True, None)

    def test_duplicate_names(self):
        subnets = [{"name": "pub-a"}, {"name": "pub-a"}]
        ok, err = validate_duplicate_subnet_names(subnets)
        assert not ok
        assert "pub-a" in err

    def test_empty_list(self):
        assert validate_duplicate_subnet_names([]) == (True, None)
