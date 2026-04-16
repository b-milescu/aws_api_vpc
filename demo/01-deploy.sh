#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# 01-deploy.sh — Bootstrap and deploy the VPC Provisioning API stack
#
# Usage:
#   ./demo/01-deploy.sh [AWS_REGION]
#
# Outputs:
#   .env.demo   — CDK output values exported for use by subsequent scripts
###############################################################################

REGION="${1:-us-east-1}"
STACK="VpcProvisioningStack"

echo "============================================"
echo " Deploying $STACK in $REGION"
echo "============================================"

# 1. Bootstrap (idempotent — safe to re-run)
echo ""
echo "[1/2] Bootstrapping CDK…"
cdk bootstrap "aws://$(aws sts get-caller-identity --query Account --output text)/${REGION}"

# 2. Deploy
echo ""
echo "[2/2] Deploying CDK stack…"
# --outputs-file writes JSON we can jq-parse later
DEPLOY_OUT="demo/cdk-output.json"
cdk deploy "$STACK" \
  --region "$REGION" \
  --require-approval never \
  --outputs-file "$DEPLOY_OUT"

# 3. Export outputs into a shell-friendly .env.demo file
echo ""
echo "Exporting outputs to demo/.env.demo…"
python3 -c "
import json
with open('demo/cdk-output.json') as f:
    data = json.load(f)
stack = '${STACK}'
out = data.get(stack, data.get(stack.replace(' ', ''), {}))
lines = []
for k, v in out.items():
    env_key = k.upper().replace('.', '_').replace(' ', '_')
    lines.append(f'{env_key}={v}')
with open('demo/.env.demo', 'w') as f:
    f.write('\n'.join(lines) + '\n')
"

echo ""
echo "============================================"
echo " ✅ Deploy complete"
echo "============================================"
echo ""
echo "Saved outputs to demo/.env.demo:"
cat demo/.env.demo
echo ""
echo "Run: source demo/.env.demo"
echo "     ./demo/02-create-vpc.sh"
