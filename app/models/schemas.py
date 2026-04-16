"""Pydantic models and schemas for the VPC Provisioning API."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

# ── Request models ────────────────────────────────────────────────────────────


class SubnetRequest(BaseModel):
    """Represents a subnet within a VPC."""

    name: str = Field(min_length=1, max_length=30)
    cidr_block: str = Field(min_length=1, max_length=18)  # e.g. "10.0.1.0/24"
    availability_zone: str = Field(min_length=1, max_length=30)  # e.g. "eu-central-1a"


class VpcCreateRequest(BaseModel):
    """Request body for POST /vpcs."""

    name: str = Field(min_length=1, max_length=50)
    region: str = Field(min_length=1, max_length=30)
    cidr_block: str = Field(min_length=1, max_length=18)
    subnets: list[SubnetRequest] = Field(min_length=1, max_length=50)
    tags: dict[str, str] = Field(default_factory=dict)


class VpcCreateResponse(BaseModel):
    """Response body for POST /vpcs."""

    request_id: str
    status: str
    message: Optional[str] = None


# ── Persistence domain model ─────────────────────────────────────────────────


class RequestStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL_DELETE = "PARTIAL_DELETE"
    FAILED = "FAILED"
    DELETED = "DELETED"


class VpcRecord(BaseModel):
    """Domain model persisted in DynamoDB."""

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: RequestStatus = RequestStatus.PENDING
    name: str = ""
    region: str = ""
    cidr_block: str = ""
    subnets_requested: list[dict] = Field(default_factory=list)
    tags: dict[str, str] = Field(default_factory=dict)
    requested_by: Optional[str] = None
    vpc_id: Optional[str] = None
    subnet_ids: list[dict] = Field(default_factory=list)
    error_message: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_create_request(
        cls, create_req: VpcCreateRequest, requested_by: Optional[str] = None
    ) -> VpcRecord:
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            status=RequestStatus.PENDING,
            name=create_req.name,
            region=create_req.region,
            cidr_block=create_req.cidr_block,
            subnets_requested=[s.model_dump() for s in create_req.subnets],
            tags=create_req.tags,
            requested_by=requested_by,
            created_at=now,
            updated_at=now,
        )


class VpcRecordResponse(BaseModel):
    """Response body for GET /vpcs/{request_id}."""

    request_id: str
    status: str
    name: str
    region: str
    cidr_block: str
    subnets_requested: list[dict]
    tags: dict[str, str]
    requested_by: Optional[str]
    vpc_id: Optional[str]
    subnet_ids: list[dict]
    error_message: Optional[str]
    created_at: str
    updated_at: str


class VpcListResponseItem(BaseModel):
    """Item for GET /vpcs list."""

    request_id: str
    status: str
    name: str
    vpc_id: Optional[str]
    created_at: str


class VpcListResponse(BaseModel):
    items: list[VpcListResponseItem]
    count: int
