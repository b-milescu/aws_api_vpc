#!/usr/bin/env python3
"""CDK app entry point."""

import os
import sys

# Allow CDK (which runs python3 infra/app.py from the project root)
# to find the `infra` package by adding the project root to sys.path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aws_cdk import App, Environment
from infra.stacks.vpc_provisioning_stack import VpcProvisioningStack

app = App()

account = os.environ.get("CDK_DEFAULT_ACCOUNT")
region = os.environ.get("CDK_DEFAULT_REGION", "us-east-1")

env = Environment(account=account, region=region)

VpcProvisioningStack(
    app,
    "VpcProvisioningStack",
    env=env,
)

app.synth()
