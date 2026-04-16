"""Step Functions failure catch handler.

Invoked when the provisioning task Lambda throws an unhandled exception.
Marks the request record as FAILED in DynamoDB so that clients polling
the record see a terminal state rather than a stuck IN_PROGRESS.
"""

from __future__ import annotations

import json

from aws_lambda_powertools import Logger

from app.models.schemas import RequestStatus
from app.services.request_store import RequestStore

logger = Logger(service="sfn-failure-handler")


def handler(event, context):
    """Catch handler for Step Functions workflow failures."""
    try:
        # Step Functions passes the original input via $.Cause
        cause = event.get("cause", "")
        error = event.get("error", "Unknown")

        # The original workflow input contains the request_id
        input_json = event.get("input", "{}")
        try:
            input_data = (
                json.loads(input_json) if isinstance(input_json, str) else input_json
            )
        except (json.JSONDecodeError, TypeError):
            input_data = {}

        request_id = input_data.get("request_id")
        if not request_id:
            logger.error(f"No request_id in failure event input: {input_data}")
            return {"error": "No request_id found", "status": "ignored"}

        store = RequestStore()
        record = store.get_record(request_id)
        record.status = RequestStatus.FAILED
        record.error_message = f"Workflow failure ({error}): {cause}"
        store.update_record(record)

        logger.info(f"Marked request {request_id} as FAILED via SFN catch handler")
        return {"request_id": request_id, "status": "FAILED"}

    except Exception as exc:
        logger.exception(f"Unhandled error in SFN failure handler: {exc}")
        return {"error": str(exc), "status": "error"}
