"""Lambda handler for GET /health endpoint.

No authentication required — used for monitoring and deployment verification.
"""

from __future__ import annotations

import json
from http import HTTPStatus


def handler(event, context):
    """Handle GET /health — healthcheck endpoint."""
    body = {
        "status": "healthy",
        "service": "vpc-provisioning-api",
    }
    return {
        "statusCode": HTTPStatus.OK.value,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }
