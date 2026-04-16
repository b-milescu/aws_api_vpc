"""Lambda handler for DELETE /vpcs/{request_id} endpoint.

Deletes the provisioned VPC and subnets in AWS, then updates the
record status to DELETED. Subnets are deleted first (required by AWS),
then the VPC itself. Partial failures are recorded so that any
remaining resources can be cleaned up manually.
"""

from __future__ import annotations

import json
from http import HTTPStatus

from aws_lambda_powertools import Logger

from app.models.schemas import RequestStatus
from app.services.request_store import RequestStore, RequestNotFoundError
from app.services.vpc_provisioner import VpcProvisioner

logger = Logger(service="delete-vpc")


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
    """Handle DELETE /vpcs/{request_id} — delete provisioned resources."""
    try:
        request_id = _extract_request_id(event)
        if not request_id:
            return _build_response(
                {"error": "Missing request_id path parameter"},
                HTTPStatus.BAD_REQUEST,
            )

        store = RequestStore()
        record = store.get_record(request_id)

        # Nothing to delete if provisioning never succeeded or never started
        if record.vpc_id is None:
            logger.info(f"No VPC to delete for {request_id} (vpc_id is None)")
            record.status = RequestStatus.DELETED
            store.update_record(record)
            return _build_response(
                {
                    "request_id": request_id,
                    "status": RequestStatus.DELETED.value,
                    "note": "No provisioned resources to delete",
                },
                HTTPStatus.OK,
            )

        provisioner = VpcProvisioner(region=record.region)

        # 1. Delete subnets first (required before VPC deletion)
        if record.subnet_ids:
            subnet_results = provisioner.delete_subnets(
                vpc_id=record.vpc_id, subnet_ids=record.subnet_ids
            )
        else:
            subnet_results = []

        # 2. Delete the VPC
        vpc_delete_error = None
        try:
            provisioner.delete_vpc(record.vpc_id)
        except Exception as exc:
            vpc_delete_error = str(exc)
            logger.error(f"Failed to delete VPC {record.vpc_id}: {exc}")

        # 3. Build response
        errors = [r for r in subnet_results if r.get("status") == "error"]
        if vpc_delete_error:
            errors.append(
                {
                    "resource": "vpc",
                    "name": record.vpc_id,
                    "status": "error",
                    "reason": vpc_delete_error,
                }
            )

        if errors:
            record.status = RequestStatus.PARTIAL_DELETE
            record.error_message = (
                f"Partial cleanup: {len(errors)} resource(s) failed to delete. "
                "Please check AWS console and delete remaining resources manually."
            )
            store.update_record(record)
            return _build_response(
                {
                    "request_id": request_id,
                    "status": "PARTIAL_DELETE",
                    "subnet_results": subnet_results,
                    "vpc_error": vpc_delete_error,
                },
                HTTPStatus.MULTI_STATUS,
            )

        record.status = RequestStatus.DELETED
        store.update_record(record)

        return _build_response(
            {
                "request_id": request_id,
                "status": RequestStatus.DELETED.value,
                "subnet_results": subnet_results,
            },
            HTTPStatus.OK,
        )

    except RequestNotFoundError as e:
        return _build_response({"error": str(e)}, HTTPStatus.NOT_FOUND)

    except Exception:
        logger.exception("Unexpected error in DELETE /vpcs/{request_id} handler")
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
    raw_path = event.get("rawPath", "")
    if raw_path and raw_path.startswith("/vpcs/"):
        return raw_path.split("/vpcs/")[1].split("/")[0]
    return None
