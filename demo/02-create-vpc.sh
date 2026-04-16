#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# 02-create-vpc.sh — Create a VPC via the Provisioning API
#
# Usage:
#   source demo/.env.demo
#   ./demo/02-create-vpc.sh [NAME]
#
# Prerequisites:
#   - demo/.env.demo must be sourced (real newlines, not literal \n)
#   - Python 3, jq, aws CLI, curl
###############################################################################

NAME="${1:-demo-vpc}"
REQUEST_ID_FILE="demo/request_id.txt"

# ── Read config ──────────────────────────────────────────────────────────────
ENV_FILE="demo/.env.demo"
if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: $ENV_FILE not found. Run: ./demo/01-deploy.sh first."
  exit 1
fi
source "$ENV_FILE"

API_URL="${APIURL:-}"
USER_POOL_ID="${COGNITOUSERPOOLID:-}"
CLIENT_ID="${COGNITOUSERPOOLCLIENTID:-}"
AWS_REGION="${AWS_REGION:-us-east-1}"

if [ -z "$USER_POOL_ID" ] || [ -z "$CLIENT_ID" ] || [ -z "$API_URL" ]; then
  echo "ERROR: demo/.env.demo is missing key values."
  echo "Re-run: ./demo/01-deploy.sh"
  exit 1
fi

echo "============================================"
echo " 1/4 — Creating Cognito user"
echo "============================================"
USERNAME="demo-$(date +%s)-${RANDOM}"
PASSWORD="DemoPass1!$(date +%s)"

echo "  User: $USERNAME"

# Create the user admin-side (no email verification needed)
aws cognito-idp admin-create-user \
  --user-pool-id "$USER_POOL_ID" \
  --username "$USERNAME" \
  --user-attributes Name=email,Value="${USERNAME}@example.com" \
  --region "$AWS_REGION" 2>/dev/null \
  || echo "  (user may already exist, continuing…)"

# Set a permanent password (overwrites the temporary one)
aws cognito-idp admin-set-user-password \
  --user-pool-id "$USER_POOL_ID" \
  --username "$USERNAME" \
  --password "$PASSWORD" \
  --permanent \
  --region "$AWS_REGION" 2>/dev/null \
  || true

echo ""
echo "============================================"
echo " 2/4 — Obtaining access token"
echo "============================================"
TOKEN=$(aws cognito-idp admin-initiate-auth \
  --user-pool-id "$USER_POOL_ID" \
  --client-id "$CLIENT_ID" \
  --auth-flow ADMIN_USER_PASSWORD_AUTH \
  --auth-parameters "USERNAME=${USERNAME},PASSWORD=${PASSWORD}" \
  --query "AuthenticationResult.AccessToken" \
  --output text \
  --region "$AWS_REGION")

echo "  Token obtained"

echo ""
echo "============================================"
echo " 3/4 — Creating VPC (POST /vpcs)"
echo "============================================"

HTTP_CODE=$(curl -s -o /tmp/create_resp.json -w "%{http_code}" \
  -X POST "${API_URL}/vpcs" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"${NAME}\",
    \"region\": \"${AWS_REGION}\",
    \"cidr_block\": \"10.0.0.0/16\",
    \"subnets\": [
      {\"name\": \"public-a\", \"cidr_block\": \"10.0.1.0/24\", \"availability_zone\": \"${AWS_REGION}a\"},
      {\"name\": \"private-a\", \"cidr_block\": \"10.0.2.0/24\", \"availability_zone\": \"${AWS_REGION}a\"}
    ],
    \"tags\": {\"environment\": \"demo\"}
  }")

if [ "$HTTP_CODE" -lt 200 ] || [ "$HTTP_CODE" -ge 300 ]; then
  echo "  ERROR: HTTP ${HTTP_CODE}"
  cat /tmp/create_resp.json | jq .
  exit 1
fi

RESP=$(cat /tmp/create_resp.json)
REQUEST_ID=$(echo "$RESP" | jq -r '.request_id')
STATUS=$(echo "$RESP" | jq -r '.status')

echo "  Request ID: ${REQUEST_ID}"
echo "  Status:     ${STATUS}"
echo "$REQUEST_ID" > "$REQUEST_ID_FILE"

echo ""
echo "============================================"
echo " 4/4 — Polling until provisioning completes"
echo "============================================"

MAX=60
i=0
while [ "$i" -lt "$MAX" ]; do
  sleep 5
  GET_RESP=$(curl -s -o /tmp/get_resp.json -w "%{http_code}" \
    "${API_URL}/vpcs/${REQUEST_ID}" \
    -H "Authorization: Bearer ${TOKEN}")

  GET_STATUS=$(jq -r '.status // "unknown"' /tmp/get_resp.json)
  echo "  [$(date '+%H:%M:%S')]  Status: ${GET_STATUS}"

  if [ "$GET_STATUS" = "SUCCEEDED" ] || [ "$GET_STATUS" = "FAILED" ]; then
    break
  fi
  i=$((i + 1))
done

echo ""
cat /tmp/get_resp.json | jq .

echo ""
echo "============================================"
echo " VPC creation complete"
echo "============================================"
echo "  Request ID saved to: ${REQUEST_ID_FILE}"
echo "  Run: ./demo/03-delete-vpc.sh"
