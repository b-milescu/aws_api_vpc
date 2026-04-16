"""Unit tests for request store (with mocked DynamoDB)."""

import pytest
from moto import mock_aws
import boto3

from app.models.schemas import VpcCreateRequest, VpcRecord, RequestStatus
from app.services.request_store import RequestStore, RequestNotFoundError

REGION = "us-east-1"


def _create_table(table_name: str = "test-vpc-requests"):
    """Set up the DynamoDB table in mock AWS."""
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


SAMPLE_CREATE = {
    "name": "test-vpc",
    "region": "us-east-1",
    "cidr_block": "10.0.0.0/16",
    "subnets": [
        {
            "name": "public-a",
            "cidr_block": "10.0.1.0/24",
            "availability_zone": "us-east-1a",
        }
    ],
    "tags": {"env": "test"},
}


class TestRequestStore:
    @pytest.fixture(autouse=True)
    def setup_region(self, monkeypatch):
        monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)

    def test_put_and_get_record(self):
        with mock_aws():
            _create_table()
            store = _make_store()

            req = VpcCreateRequest(**SAMPLE_CREATE)
            record = VpcRecord.from_create_request(req, requested_by="test@example.com")

            stored = store.put_record(record)
            assert stored.request_id == record.request_id
            assert stored.status == RequestStatus.PENDING

            fetched = store.get_record(record.request_id)
            assert fetched.request_id == record.request_id
            assert fetched.vpc_id is None

    def test_get_nonexistent_raises(self):
        with mock_aws():
            _create_table()
            store = _make_store()

            with pytest.raises(RequestNotFoundError):
                store.get_record("does-not-exist")

    def test_list_records(self):
        with mock_aws():
            _create_table()
            store = _make_store()

            r1 = VpcRecord(name="vpc-1", cidr_block="10.0.0.0/16", region="us-east-1")
            r2 = VpcRecord(name="vpc-2", cidr_block="10.1.0.0/16", region="us-east-1")

            store.put_record(r1)
            store.put_record(r2)

            result = store.list_records()
            assert result.count == 2
            assert len(result.items) == 2

    def test_update_record(self):
        with mock_aws():
            _create_table()
            store = _make_store()

            req = VpcCreateRequest(**SAMPLE_CREATE)
            record = VpcRecord.from_create_request(req, requested_by="test@example.com")
            record.vpc_id = "vpc-12345"
            record.status = RequestStatus.SUCCEEDED

            store.update_record(record)
            fetched = store.get_record(record.request_id)

            assert fetched.vpc_id == "vpc-12345"
            assert fetched.status == RequestStatus.SUCCEEDED
