"""DynamoDB-backed persistence service for VPC request records."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

from app.models.schemas import (
    VpcRecord,
    VpcListResponse,
    VpcListResponseItem,
    RequestStatus,
)
from app.utils.logger import logger


class RequestNotFoundError(Exception):
    """Raised when a record is not found."""

    def __init__(self, request_id: str):
        super().__init__(f"Request {request_id} not found")
        self.request_id = request_id


TABLE_NAME = os.environ.get("TABLE_NAME", "vpc-requests")


class RequestStore:
    """Thin service wrapper around DynamoDB for request records."""

    def __init__(
        self, table_name: str | None = None, dynamodb=None, region: str | None = None
    ):
        self._table_name = table_name or TABLE_NAME
        if dynamodb:
            self._dynamodb = dynamodb
        else:
            self._dynamodb = boto3.resource(
                "dynamodb",
                region_name=region or os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
            )
        self._table = self._dynamodb.Table(self._table_name)

    def put_record(self, record: VpcRecord) -> VpcRecord:
        """Insert a new record."""
        record.created_at = record.created_at or datetime.now(timezone.utc).isoformat()
        record.updated_at = datetime.now(timezone.utc).isoformat()
        self._table.put_item(Item=_to_dynamo(record))
        logger.info(f"Created request record {record.request_id}")
        return record

    def get_record(self, request_id: str) -> VpcRecord:
        """Retrieve a record by request_id."""
        resp = self._table.get_item(Key={"request_id": request_id})
        item = resp.get("Item")
        if item is None:
            raise RequestNotFoundError(request_id)
        return _from_dynamo(item)

    def update_record(self, record: VpcRecord) -> VpcRecord:
        """Persist an updated record (overwrites)."""
        record.updated_at = datetime.now(timezone.utc).isoformat()
        self._table.put_item(Item=_to_dynamo(record))
        logger.info(f"Updated request record {record.request_id}")
        return record

    def list_records(self, limit: int = 50) -> VpcListResponse:
        """Return a paginated list of all request records."""
        items = []
        try:
            resp = self._table.scan(Limit=limit)
            items = [_from_dynamo(i) for i in resp.get("Items", [])]
            while "LastEvaluatedKey" in resp and len(items) < limit:
                resp = self._table.scan(
                    ExclusiveStartKey=resp["LastEvaluatedKey"], Limit=limit
                )
                items.extend(_from_dynamo(i) for i in resp.get("Items", []))
        except ClientError as exc:
            logger.error(f"DynamoDB scan failed: {exc}")
            raise

        items.sort(key=lambda r: r.created_at, reverse=True)
        items = items[:limit]

        list_items = [
            VpcListResponseItem(
                request_id=r.request_id,
                status=r.status.value
                if isinstance(r.status, RequestStatus)
                else r.status,
                name=r.name,
                vpc_id=r.vpc_id,
                created_at=r.created_at,
            )
            for r in items
        ]

        return VpcListResponse(items=list_items, count=len(list_items))

    def update_status(
        self,
        request_id: str,
        status: RequestStatus,
        vpc_id: str | None = None,
        subnet_ids: list[dict] | None = None,
        error_message: str | None = None,
    ) -> VpcRecord:
        """Convenience method to update key fields on an existing record."""
        record = self.get_record(request_id)
        record.status = status
        record.updated_at = datetime.now(timezone.utc).isoformat()
        if vpc_id is not None:
            record.vpc_id = vpc_id
        if subnet_ids is not None:
            record.subnet_ids = subnet_ids
        if error_message is not None:
            record.error_message = error_message
        self.update_record(record)
        return record


# ── DynamoDB serialisation helpers ────────────────────────────────────────────


def _to_dynamo(record: VpcRecord) -> dict:
    """Convert a VpcRecord to a flat dict suitable for DynamoDB."""
    return {
        "request_id": record.request_id,
        "status": record.status.value
        if isinstance(record.status, RequestStatus)
        else record.status,
        "name": record.name,
        "region": record.region,
        "cidr_block": record.cidr_block,
        "subnets_requested": record.subnets_requested,
        "tags": record.tags,
        "requested_by": record.requested_by,
        "vpc_id": record.vpc_id,
        "subnet_ids": record.subnet_ids,
        "error_message": record.error_message,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _from_dynamo(item: dict) -> VpcRecord:
    """Convert a DynamoDB item back to a VpcRecord."""
    status_raw = item.get("status", "PENDING")
    try:
        status = RequestStatus(status_raw)
    except ValueError:
        status = RequestStatus.PENDING

    return VpcRecord(
        request_id=item["request_id"],
        status=status,
        name=item.get("name", ""),
        region=item.get("region", ""),
        cidr_block=item.get("cidr_block", ""),
        subnets_requested=item.get("subnets_requested", []),
        tags=item.get("tags", {}),
        requested_by=item.get("requested_by"),
        vpc_id=item.get("vpc_id"),
        subnet_ids=item.get("subnet_ids", []),
        error_message=item.get("error_message"),
        created_at=item.get("created_at", ""),
        updated_at=item.get("updated_at", ""),
    )
