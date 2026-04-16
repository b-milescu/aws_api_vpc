"""Unit tests for Lambda handlers (with mocked AWS services)."""

import json
import pytest
from moto import mock_aws
import boto3
from unittest.mock import patch

from app.handlers.create_vpc import handler as create_vpc_handler
from app.handlers.get_vpc import handler as get_vpc_handler
from app.handlers.list_vpcs import handler as list_vpcs_handler
from app.handlers.health import handler as health_handler
from app.handlers.delete_vpc import handler as delete_vpc_handler
from app.models.schemas import VpcRecord, RequestStatus
from app.services.request_store import RequestStore

REGION = "us-east-1"


def _create_table(table_name: str = "test-vpc-requests"):
    client = boto3.client("dynamodb", region_name=REGION)
    client.create_table(
        TableName=table_name,
        KeySchema=[{"AttributeName": "request_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "request_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )


def _make_store(table_name: str = "test-vpc-requests") -> RequestStore:
    return RequestStore(
        table_name=table_name,
        dynamodb=boto3.resource("dynamodb", region_name=REGION),
        region=REGION,
    )


class MockContext:
    function_name = "test-function"
    memory_limit_in_mb = 128
    invoked_function_arn = ""
    aws_request_id = ""


VALID_BODY = {
    "name": "demo-vpc",
    "region": "us-east-1",
    "cidr_block": "10.0.0.0/16",
    "subnets": [
        {
            "name": "pub-a",
            "cidr_block": "10.0.1.0/24",
            "availability_zone": "us-east-1a",
        }
    ],
    "tags": {"env": "demo"},
}


class TestHealthHandler:
    def test_health_returns_200(self):
        resp = health_handler({}, MockContext())
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["status"] == "healthy"


class TestCreateVpcHandler:
    @pytest.fixture(autouse=True)
    def setup_mocks(self, monkeypatch):
        monkeypatch.setenv("TABLE_NAME", "test-vpc-requests")
        monkeypatch.setenv("STATE_MACHINE_ARN", "")
        monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)

    def test_create_vpc_valid_request(self, monkeypatch):
        with mock_aws():
            _create_table()

            body_str = json.dumps(VALID_BODY)
            event = {
                "body": body_str,
                "rawPath": "/vpcs",
                "requestContext": {},
            }

            store = _make_store()
            with patch("app.handlers.create_vpc.RequestStore", return_value=store):
                resp = create_vpc_handler(event, MockContext())
                assert resp["statusCode"] == 202

                resp_body = json.loads(resp["body"])
                assert "request_id" in resp_body
                assert resp_body["status"] == "PENDING"

    def test_create_vpc_missing_body(self, monkeypatch):
        with mock_aws():
            _create_table()

            event = {"body": None, "rawPath": "/vpcs"}
            resp = create_vpc_handler(event, MockContext())
            assert resp["statusCode"] == 400

    def test_create_vpc_invalid_cidr(self, monkeypatch):
        with mock_aws():
            _create_table()

            body = {
                "name": "demo-vpc",
                "region": "us-east-1",
                "cidr_block": "not-valid",
                "subnets": [
                    {
                        "name": "pub-a",
                        "cidr_block": "not-valid",
                        "availability_zone": "us-east-1a",
                    }
                ],
            }

            event = {"body": json.dumps(body), "rawPath": "/vpcs"}
            resp = create_vpc_handler(event, MockContext())
            assert resp["statusCode"] == 400

    def test_create_vpc_subnet_not_in_vpc(self, monkeypatch):
        with mock_aws():
            _create_table()

            body = {
                "name": "demo-vpc",
                "region": "us-east-1",
                "cidr_block": "10.0.0.0/16",
                "subnets": [
                    {
                        "name": "pub-a",
                        "cidr_block": "192.168.1.0/24",
                        "availability_zone": "us-east-1a",
                    }
                ],
            }

            event = {"body": json.dumps(body), "rawPath": "/vpcs"}
            resp = create_vpc_handler(event, MockContext())
            assert resp["statusCode"] == 400

    def test_create_vpc_overlapping_subnets(self, monkeypatch):
        with mock_aws():
            _create_table()

            body = {
                "name": "demo-vpc",
                "region": "us-east-1",
                "cidr_block": "10.0.0.0/16",
                "subnets": [
                    {
                        "name": "pub-a",
                        "cidr_block": "10.0.1.0/24",
                        "availability_zone": "us-east-1a",
                    },
                    {
                        "name": "pub-b",
                        "cidr_block": "10.0.1.0/25",
                        "availability_zone": "us-east-1b",
                    },
                ],
            }

            event = {"body": json.dumps(body), "rawPath": "/vpcs"}
            resp = create_vpc_handler(event, MockContext())
            assert resp["statusCode"] == 400

    def test_create_vpc_duplicate_subnet_names(self, monkeypatch):
        with mock_aws():
            _create_table()

            body = {
                "name": "demo-vpc",
                "region": "us-east-1",
                "cidr_block": "10.0.0.0/16",
                "subnets": [
                    {
                        "name": "pub-a",
                        "cidr_block": "10.0.1.0/24",
                        "availability_zone": "us-east-1a",
                    },
                    {
                        "name": "pub-a",
                        "cidr_block": "10.0.2.0/24",
                        "availability_zone": "us-east-1b",
                    },
                ],
            }

            event = {"body": json.dumps(body), "rawPath": "/vpcs"}
            resp = create_vpc_handler(event, MockContext())
            assert resp["statusCode"] == 400

    def test_create_vpc_invalid_region(self, monkeypatch):
        with mock_aws():
            _create_table()

            body = {
                "name": "demo-vpc",
                "region": "invalid-region",
                "cidr_block": "10.0.0.0/16",
                "subnets": [
                    {
                        "name": "pub-a",
                        "cidr_block": "10.0.1.0/24",
                        "availability_zone": "us-east-1a",
                    }
                ],
            }

            event = {"body": json.dumps(body), "rawPath": "/vpcs"}
            resp = create_vpc_handler(event, MockContext())
            assert resp["statusCode"] == 400

    def test_400_with_no_subnets(self, monkeypatch):
        with mock_aws():
            _create_table()

            body = {
                "name": "demo-vpc",
                "region": "us-east-1",
                "cidr_block": "10.0.0.0/16",
                "subnets": [],
            }

            event = {"body": json.dumps(body), "rawPath": "/vpcs"}
            resp = create_vpc_handler(event, MockContext())
            assert resp["statusCode"] == 400


class TestGetVpcHandler:
    @pytest.fixture(autouse=True)
    def setup_mocks(self, monkeypatch):
        monkeypatch.setenv("TABLE_NAME", "test-vpc-requests")
        monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)

    def test_get_existing_record(self):
        with mock_aws():
            _create_table()
            store = _make_store()

            record = VpcRecord(
                name="demo-vpc",
                region="us-east-1",
                cidr_block="10.0.0.0/16",
                status=RequestStatus.PENDING,
            )
            store.put_record(record)

            event = {
                "rawPath": f"/vpcs/{record.request_id}",
                "pathParameters": {"request_id": record.request_id},
            }

            with patch("app.handlers.get_vpc.RequestStore", return_value=store):
                resp = get_vpc_handler(event, MockContext())
                assert resp["statusCode"] == 200

                body = json.loads(resp["body"])
                assert body["request_id"] == record.request_id
                assert body["status"] == "PENDING"

    def test_get_nonexistent_record(self):
        with mock_aws():
            _create_table()
            store = _make_store()

            event = {
                "rawPath": "/vpcs/nonexistent",
                "pathParameters": {"request_id": "nonexistent"},
            }

            with patch("app.handlers.get_vpc.RequestStore", return_value=store):
                resp = get_vpc_handler(event, MockContext())
                assert resp["statusCode"] == 404


class TestListVpcsHandler:
    @pytest.fixture(autouse=True)
    def setup_mocks(self, monkeypatch):
        monkeypatch.setenv("TABLE_NAME", "test-vpc-requests")
        monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)

    def test_list_empty(self):
        with mock_aws():
            _create_table()
            store = _make_store()

            event = {"rawPath": "/vpcs"}

            with patch("app.handlers.list_vpcs.RequestStore", return_value=store):
                resp = list_vpcs_handler(event, MockContext())
                assert resp["statusCode"] == 200

                body = json.loads(resp["body"])
                assert body["count"] == 0

    def test_list_with_records(self):
        with mock_aws():
            _create_table()

            records_to_insert = [
                VpcRecord(name="vpc-1", region="us-east-1", cidr_block="10.0.0.0/16"),
                VpcRecord(name="vpc-2", region="us-east-1", cidr_block="10.1.0.0/16"),
            ]

            store = _make_store()
            for r in records_to_insert:
                store.put_record(r)

            event = {"rawPath": "/vpcs"}

            with patch("app.handlers.list_vpcs.RequestStore", return_value=store):
                resp = list_vpcs_handler(event, MockContext())
                assert resp["statusCode"] == 200

                body = json.loads(resp["body"])
                assert body["count"] == 2


class TestDeleteVpcHandler:
    @pytest.fixture(autouse=True)
    def setup_mocks(self, monkeypatch):
        monkeypatch.setenv("TABLE_NAME", "test-vpc-requests")
        monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)

    def test_delete_existing_record_no_resources(self):
        """DELETE for a record that never had resources provisioned (vpc_id=None)."""
        with mock_aws():
            _create_table()
            store = _make_store()

            record = VpcRecord(
                name="demo-vpc",
                region="us-east-1",
                cidr_block="10.0.0.0/16",
                status=RequestStatus.PENDING,
            )
            store.put_record(record)

            event = {
                "rawPath": f"/vpcs/{record.request_id}",
                "pathParameters": {"request_id": record.request_id},
            }

            with patch("app.handlers.delete_vpc.RequestStore", return_value=store):
                with patch("app.handlers.delete_vpc.VpcProvisioner"):
                    resp = delete_vpc_handler(event, MockContext())
                    assert resp["statusCode"] == 200

                    body = json.loads(resp["body"])
                    assert body["status"] == "DELETED"
                    assert "note" in body

    def test_delete_nonexistent_record(self):
        with mock_aws():
            _create_table()
            store = _make_store()

            event = {
                "rawPath": "/vpcs/nonexistent",
                "pathParameters": {"request_id": "nonexistent"},
            }

            with patch("app.handlers.delete_vpc.RequestStore", return_value=store):
                resp = delete_vpc_handler(event, MockContext())
                assert resp["statusCode"] == 404
