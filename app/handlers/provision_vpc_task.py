"""Step Functions workflow task: provision VPC and subnets.

This Lambda is the main orchestrator called by the Step Functions state machine.
It:
1. Reads the request record from DynamoDB
2. Updates status to IN_PROGRESS
3. Creates the VPC
4. Creates subnets
5. Tags resources
6. Persists results to DynamoDB
7. Handles failures with clear error messages
"""

from __future__ import annotations

from datetime import datetime, timezone

from aws_lambda_powertools import Logger

from app.models.schemas import RequestStatus
from app.services.request_store import RequestStore
from app.services.vpc_provisioner import VpcProvisioner

logger = Logger(service="provision-vpc-task")


def handler(event, context):
    """Step Functions task — provisions a VPC and its subnets."""
    request_id = event.get("request_id")
    if not request_id:
        return {"error": "Missing request_id in workflow input", "status": "FAILED"}

    store = RequestStore()

    # Retrieve the request record
    try:
        record = store.get_record(request_id)
    except Exception:
        msg = f"Request {request_id} not found"
        logger.error(msg)
        return {"error": msg, "status": "FAILED"}

    # Mark as in progress
    try:
        record.status = RequestStatus.IN_PROGRESS
        record.updated_at = datetime.now(timezone.utc).isoformat()
        store.update_record(record)
    except Exception as exc:
        logger.error(f"Failed to update status to IN_PROGRESS: {exc}")
        record.error_message = f"Failed to update status: {exc}"
        record.status = RequestStatus.FAILED
        record.updated_at = datetime.now(timezone.utc).isoformat()
        store.update_record(record)
        return {"error": record.error_message, "status": "FAILED"}

    # Provision the VPC — idempotent via DynamoDB guard
    provisioner = VpcProvisioner(region=record.region)

    if not record.vpc_id:
        try:
            vpc_id = provisioner.create_vpc(
                cidr_block=record.cidr_block,
                name=record.name,
                tags=record.tags,
            )
            record.vpc_id = vpc_id

            # Enable DNS support
            provisioner.enable_dns_support(vpc_id)
        except Exception as exc:
            msg = f"VPC creation failed: {exc}"
            logger.error(msg)
            record.status = RequestStatus.FAILED
            record.error_message = msg
            record.updated_at = datetime.now(timezone.utc).isoformat()
            store.update_record(record)
            return {"error": msg, "status": "FAILED"}
    else:
        vpc_id = record.vpc_id
        logger.info(f"VPC {vpc_id} already created (idempotent retry)")

    # Create subnets — idempotent via DynamoDB guard
    if not record.subnet_ids:
        try:
            subnet_results = provisioner.create_subnets(
                vpc_id=vpc_id,
                subnets=record.subnets_requested,
            )
            record.subnet_ids = subnet_results
        except Exception as exc:
            msg = f"Subnet creation failed: {exc}"
            logger.error(msg)
            record.status = RequestStatus.FAILED
            record.error_message = msg
            record.updated_at = datetime.now(timezone.utc).isoformat()
            store.update_record(record)
            return {"error": msg, "status": "FAILED"}
    else:
        subnet_results = record.subnet_ids
        logger.info(
            f"Subnets already created ({len(subnet_results)}), idempotent retry"
        )

    # All done — mark as succeeded
    record.status = RequestStatus.SUCCEEDED
    record.updated_at = datetime.now(timezone.utc).isoformat()
    store.update_record(record)

    logger.info(
        f"Successfully provisioned VPC {vpc_id} with {len(subnet_results)} subnets"
    )

    return {
        "request_id": request_id,
        "status": "SUCCEEDED",
        "vpc_id": vpc_id,
        "subnets": subnet_results,
    }
