"""Lambda handler for GET /vpcs/{request_id} endpoint.

Returns stored status and created resources for a specific VPC request.
"""

from __future__ import annotations

import json
from http import HTTPStatus

from aws_lambda_powertools import Logger

from app.models.schemas import VpcRecordResponse
from app.services.request_store import RequestStore, RequestNotFoundError

logger = Logger(service="get-vpc")


def _build_response(body: dict, status_code: HTTPStatus) -> dict:
    return {
        "statusCode": status_code.value,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def handler(event, context):
    """Handle GET /vpcs/{request_id} — return stored request data."""
    try:
        request_id = _extract_request_id(event)
        if not request_id:
            return _build_response(
                {"error": "Missing request_id path parameter"},
                HTTPStatus.BAD_REQUEST,
            )

        store = RequestStore()
        record = store.get_record(request_id)

        resp = VpcRecordResponse(
            request_id=record.request_id,
            status=record.status.value,
            name=record.name,
            region=record.region,
            cidr_block=record.cidr_block,
            subnets_requested=record.subnets_requested,
            tags=record.tags,
            requested_by=record.requested_by,
            vpc_id=record.vpc_id,
            subnet_ids=record.subnet_ids,
            error_message=record.error_message,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        return _build_response(resp.model_dump(), HTTPStatus.OK)

    except RequestNotFoundError as e:
        return _build_response({"error": str(e)}, HTTPStatus.NOT_FOUND)

    except Exception:
        logger.exception("Unexpected error in GET /vpcs/{request_id} handler")
        return _build_response(
            {"error": "Internal server error"},
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )


def _extract_request_id(event: dict | None) -> str | None:
    """Extract the request_id from path parameters."""
    if event is None:
        return None
    params = event.get("pathParameters", {})
    if params:
        return params.get("request_id")
    # Also check rawPath for extraction
    raw_path = event.get("rawPath", "")
    if raw_path and raw_path.startswith("/vpcs/"):
        return raw_path.split("/vpcs/")[1].split("/")[0]
    return None
