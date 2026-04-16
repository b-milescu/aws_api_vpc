"""Lambda handler for the POST /vpcs endpoint.

Creates a new VPC provisioning request entry and triggers
the Step Functions workflow.
"""

from __future__ import annotations

import json
import os
from http import HTTPStatus

import boto3
from aws_lambda_powertools import Logger

from app.models.schemas import (
    VpcCreateRequest,
    VpcRecord,
    VpcCreateResponse,
    RequestStatus,
)
from app.services.request_store import RequestStore
from app.utils.cidr_validator import (
    validate_cidr,
    validate_cidr_is_subnet,
    validate_subnet_contained_in_vpc,
    validate_no_overlapping_subnets,
    validate_region,
    validate_availability_zone,
    validate_duplicate_subnet_names,
)

logger = Logger(service="create-vpc")

STATE_MACHINE_ARN = os.environ.get("STATE_MACHINE_ARN", "")


def _build_response(body: dict, status_code: HTTPStatus) -> dict:
    return {
        "statusCode": status_code.value,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def _parse_body(event: dict | None) -> dict | None:
    """Extract the JSON body from Lambda event."""
    if event is None:
        return None
    raw_body = event.get("body", "")
    if raw_body is None:
        return None
    if isinstance(raw_body, str):
        try:
            return json.loads(raw_body)
        except (json.JSONDecodeError, TypeError):
            return None
    return raw_body


def _extract_principal(event: dict | None) -> str | None:
    """Extract the caller principal from the API Gateway request context."""
    if event is None:
        return None
    req_ctx = event.get("requestContext", {})
    authorizer = req_ctx.get("authorizer")
    if authorizer:
        jwt_claims = authorizer.get("jwt", {}).get("claims")  # HTTP API format
        if jwt_claims:
            return (
                jwt_claims.get("email")
                or jwt_claims.get("sub")
                or jwt_claims.get("username")
            )
        return authorizer.get("principalId")
    return None


def handler(event, context):
    """Handle POST /vpcs — create a VPC provisioning request."""
    try:
        body = _parse_body(event)
        if body is None:
            return _build_response(
                {"error": "Invalid or missing request body"},
                HTTPStatus.BAD_REQUEST,
            )

        # Validate request
        try:
            req = VpcCreateRequest.model_validate(body)
        except Exception as exc:
            return _build_response(
                {"error": f"Invalid request body: {exc}"}, HTTPStatus.BAD_REQUEST
            )

        # Validate region
        ok, err = validate_region(req.region)
        if not ok:
            return _build_response({"error": err}, HTTPStatus.BAD_REQUEST)

        # Validate VPC CIDR (with AWS /16-/28 range check)
        ok, err = validate_cidr(req.cidr_block, is_vpc=True)
        if not ok:
            return _build_response({"error": err}, HTTPStatus.BAD_REQUEST)

        # Duplicate subnet names
        subnet_dicts = [s.model_dump() for s in req.subnets]
        ok, err = validate_duplicate_subnet_names(subnet_dicts)
        if not ok:
            return _build_response({"error": err}, HTTPStatus.BAD_REQUEST)

        # Validate subnet CIDRs, containment, AZs
        subnet_cidrs = []
        for s in req.subnets:
            ok, err = validate_cidr_is_subnet(s.cidr_block)
            if not ok:
                return _build_response(
                    {"error": f"Subnet '{s.name}': {err}"}, HTTPStatus.BAD_REQUEST
                )
            subnet_cidrs.append(s.cidr_block)

            ok, err = validate_subnet_contained_in_vpc(req.cidr_block, s.cidr_block)
            if not ok:
                return _build_response(
                    {"error": f"Subnet '{s.name}': {err}"}, HTTPStatus.BAD_REQUEST
                )

            ok, err = validate_availability_zone(s.availability_zone)
            if not ok:
                return _build_response(
                    {"error": f"Subnet '{s.name}': {err}"}, HTTPStatus.BAD_REQUEST
                )

        # No overlapping subnets
        ok, err = validate_no_overlapping_subnets(subnet_cidrs)
        if not ok:
            return _build_response({"error": err}, HTTPStatus.BAD_REQUEST)

        requested_by = _extract_principal(event)

        # Create and persist record
        record = VpcRecord.from_create_request(req, requested_by=requested_by)
        store = RequestStore()
        store.put_record(record)

        # Trigger Step Functions workflow
        if STATE_MACHINE_ARN:
            try:
                sfn = boto3.client(
                    "stepfunctions", region_name=os.environ.get("AWS_DEFAULT_REGION")
                )
                sfn.start_execution(
                    stateMachineArn=STATE_MACHINE_ARN,
                    input=json.dumps({"request_id": record.request_id}),
                )
                logger.info(f"Started Step Functions workflow for {record.request_id}")
            except Exception as exc:
                logger.error(f"Failed to start workflow: {exc}")
                # Mark record as FAILED so the client can see what happened
                record.error_message = f"Failed to start provisioning workflow: {exc}"
                record.status = RequestStatus.FAILED
                store.update_record(record)
                return _build_response(
                    {
                        "error": "Failed to start provisioning workflow",
                        "request_id": record.request_id,
                    },
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        resp = VpcCreateResponse(
            request_id=record.request_id,
            status=record.status.value,
        )
        return _build_response(resp.model_dump(), HTTPStatus.ACCEPTED)

    except Exception:
        logger.exception("Unexpected error in POST /vpcs handler")
        return _build_response(
            {"error": "Internal server error"},
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )
