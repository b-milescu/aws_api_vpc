"""VPC provisioning service using boto3 for AWS operations."""

from __future__ import annotations

import os

import boto3

from app.utils.logger import logger

REGION = os.environ.get("AWS_REGION", "us-east-1")


class VpcProvisioner:
    """Responsible for creating VPC, subnets, and tagging on AWS."""

    def __init__(self, region: str | None = None, ec2_client=None):
        self.region = region or REGION
        if ec2_client:
            self._ec2 = ec2_client
        else:
            self._ec2 = boto3.client("ec2", region_name=self.region)

    def create_vpc(self, cidr_block: str, name: str, tags: dict[str, str]) -> str:
        """Create a VPC and return its VPC ID."""
        logger.info(f"Creating VPC '{name}' with CIDR {cidr_block}")
        resp = self._ec2.create_vpc(
            CidrBlock=cidr_block,
            TagSpecifications=[
                {
                    "ResourceType": "vpc",
                    "Tags": [
                        {"Key": "Name", "Value": name},
                        *({"Key": k, "Value": v} for k, v in (tags or {}).items()),
                    ],
                }
            ],
        )
        vpc_id = resp["Vpc"]["VpcId"]
        logger.info(f"VPC created: {vpc_id}")
        return vpc_id

    def enable_dns_support(self, vpc_id: str) -> None:
        """Enable DNS support and hostnames on the VPC."""
        logger.info(f"Enabling DNS hostnames on {vpc_id}")
        self._ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsSupport={"Value": True})
        self._ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsHostnames={"Value": True})

    def create_subnets(self, vpc_id: str, subnets: list[dict]) -> list[dict]:
        """Create subnets within the VPC and return their IDs."""
        results = []
        for subnet_def in subnets:
            name = subnet_def["name"]
            cidr = subnet_def["cidr_block"]
            az = subnet_def["availability_zone"]

            logger.info(f"Creating subnet '{name}' ({cidr}) in {az}")
            resp = self._ec2.create_subnet(
                VpcId=vpc_id,
                CidrBlock=cidr,
                AvailabilityZone=az,
                TagSpecifications=[
                    {
                        "ResourceType": "subnet",
                        "Tags": [{"Key": "Name", "Value": name}],
                    }
                ],
            )
            results.append(
                {
                    "name": name,
                    "subnet_id": resp["Subnet"]["SubnetId"],
                    "cidr_block": cidr,
                    "availability_zone": az,
                }
            )
            logger.info(f"Subnet created: {results[-1]['subnet_id']}")
        return results

    def delete_subnets(self, vpc_id: str, subnet_ids: list[dict]) -> list[dict]:
        """Delete subnets in the VPC. Subnets must be deleted before the VPC.

        Each subnet deletion is best-effort: failures per subnet are logged but
        do not abort the overall delete loop, so we can clean up as much as
        possible even if some resources have already been removed.
        """
        results = []
        for subnet_def in subnet_ids:
            sid = subnet_def.get("subnet_id")
            if not sid:
                logger.warning(
                    f"No subnet_id in record for {subnet_def.get('name', 'unknown')} — skipping"
                )
                results.append(
                    {
                        "name": subnet_def.get("name", "unknown"),
                        "status": "skipped",
                        "reason": "no subnet_id",
                    }
                )
                continue
            try:
                logger.info(f"Deleting subnet {sid}")
                self._ec2.delete_subnet(SubnetId=sid)
                results.append(
                    {
                        "name": subnet_def.get("name", "unknown"),
                        "subnet_id": sid,
                        "status": "deleted",
                    }
                )
            except Exception as exc:
                logger.warning(f"Failed to delete subnet {sid}: {exc}")
                results.append(
                    {
                        "name": subnet_def.get("name", "unknown"),
                        "subnet_id": sid,
                        "status": "error",
                        "reason": str(exc),
                    }
                )
        return results

    def delete_vpc(self, vpc_id: str) -> None:
        """Delete a VPC. Must be called after subnets are deleted."""
        logger.info(f"Deleting VPC {vpc_id}")
        self._ec2.delete_vpc(VpcId=vpc_id)
        logger.info(f"VPC deleted: {vpc_id}")
