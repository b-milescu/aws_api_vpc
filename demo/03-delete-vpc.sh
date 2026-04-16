#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# 03-delete-vpc.sh — Delete a provisioned VPC via the API
#
# Usage:
#   source demo/.env.demo
#   ./demo/03-delete-vpc.sh [REQUEST_ID]
#
# If REQUEST_ID is omitted, it reads demo/request_id.txt (created by
# 02-create-vpc.sh).
#
# Prerequisites:
#   - demo/.env.demo must be sourced
#   - demo/request_id.txt exists (or pass REQUEST_ID as argument)
###############################################################################

REQUEST_ID="${1:-}"
ENV_FILE="demo/.env.demo"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: $ENV_FILE not found. Run ./demo/01-deploy.sh first."
  exit 1
fi
source "$ENV_FILE"

if [ -z "$REQUEST_ID" ]; then
  if [ -f "demo/request_id.txt" ]; then
    REQUEST_ID=$(cat demo/request_id.txt)
    echo "  Using request ID from demo/request_id.txt: ${REQUEST_ID}"
  else
    echo "ERROR: no REQUEST_ID provided and demo/request_id.txt not found."
    echo "Usage: ./demo/03-delete-vpc.sh <REQUEST_ID>"
    exit 1
  fi
fi

API_URL="${APIURL:-}"
USER_POOL_ID="${COGNITOUSERPOOLID:-}"
CLIENT_ID="${COGNITOUSERPOOLCLIENTID:-}"

if [ -z "$USER_POOL_ID" ] || [ -z "$CLIENT_ID" ] || [ -z "$API_URL" ]; then
  echo "ERROR: demo/.env.demo is missing key values."
  exit 1
fi

echo "============================================"
echo " 1/3 — Obtaining access token"
echo "============================================"

# ── Create an ephemeral user for this demo run
# NOTE: This creates a *different* user than the one in 02-create-vpc.sh.
# The delete will succeed on the other user's VPC because of the intentional
# M4 gap (no tenant isolation). This demonstrates that any authenticated
# user can delete any request — a known limitation for the demo scope.
USERNAME="demo-del-$(date +%s)-${RANDOM}"
PASSWORD="DemoDel1!$(date +%s)"

aws cognito-idp admin-create-user \
  --user-pool-id "$USER_POOL_ID" \
  --username "$USERNAME" \
  --user-attributes Name=email,Value="${USERNAME}@example.com" \
  --region "${AWS_REGION:-us-east-1}" 2>/dev/null \
  || true

aws cognito-idp admin-set-user-password \
  --user-pool-id "$USER_POOL_ID" \
  --username "$USERNAME" \
  --password "$PASSWORD" \
  --permanent \
  --region "${AWS_REGION:-us-east-1}" 2>/dev/null \
  || true

TOKEN=$(aws cognito-idp admin-initiate-auth \
  --user-pool-id "$USER_POOL_ID" \
  --client-id "$CLIENT_ID" \
  --auth-flow ADMIN_USER_PASSWORD_AUTH \
  --auth-parameters "USERNAME=${USERNAME},PASSWORD=${PASSWORD}" \
  --query "AuthenticationResult.AccessToken" \
  --output text \
  --region "${AWS_REGION:-us-east-1}")

echo "  Token obtained ✓"

echo ""
echo "============================================"
echo " 2/3 — Deleting VPC (DELETE /vpcs/${REQUEST_ID})"
echo "============================================"

HTTP_CODE=$(curl -s -o /tmp/delete_resp.json -w "%{http_code}" \
  -X DELETE "${API_URL}/vpcs/${REQUEST_ID}" \
  -H "Authorization: Bearer ${TOKEN}")

echo "  HTTP Status: ${HTTP_CODE}"
echo ""
cat /tmp/delete_resp.json | jq .

echo ""
echo "============================================"
echo " 3/3 — Verifying record status (GET /vpcs/${REQUEST_ID})"
echo "============================================"

GET_CODE=$(curl -s -o /tmp/get_verify.json -w "%{http_code}" \
  "${API_URL}/vpcs/${REQUEST_ID}" \
  -H "Authorization: Bearer ${TOKEN}")

if [ "$GET_CODE" -lt 200 ] || [ "$GET_CODE" -ge 300 ]; then
  echo "  ERROR: HTTP ${GET_CODE}"
  cat /tmp/get_verify.json | jq .
  exit 1
fi

FINAL_STATUS=$(jq -r '.status' /tmp/get_verify.json)
echo "  Final status: ${FINAL_STATUS}"
echo ""
cat /tmp/get_verify.json | jq .

echo ""
echo "============================================"
echo " ✅ VPC deletion demo complete"
echo "============================================"
