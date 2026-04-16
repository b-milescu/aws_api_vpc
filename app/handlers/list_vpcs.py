"""Lambda handler for GET /vpcs endpoint.

Returns a list of all VPC provisioning requests.
"""

from __future__ import annotations

import json
from http import HTTPStatus

from aws_lambda_powertools import Logger

from app.services.request_store import RequestStore

logger = Logger(service="list-vpcs")


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
    """Handle GET /vpcs — list all requests."""
    try:
        store = RequestStore()
        response = store.list_records()
        return _build_response(response.model_dump(), HTTPStatus.OK)

    except Exception:
        logger.exception("Unexpected error in GET /vpcs handler")
        return _build_response(
            {"error": "Internal server error"},
            HTTPStatus.INTERNAL_SERVER_ERROR,
        )
