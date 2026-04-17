# VPC Provisioning API

An authenticated, serverless Python API on AWS that creates VPCs with multiple subnets, persists resource metadata in DynamoDB, and exposes retrieval endpoints.

---

## Problem statement

Create an authenticated API in Python on AWS that can:
1. Accept a VPC creation request (name, CIDR, subnets, tags)
2. Provision a real VPC and multiple subnets in AWS
3. Persist the created resource metadata
4. Expose endpoints to retrieve the stored data

---

## Architecture

All infrastructure is defined as code using **AWS CDK (Python)** and deployed as a fully serverless stack.

```
                          ┌────────────────────┐
                          │   API Gateway      │
                          │   (HTTP API)       │
                          └───────┬────────────┘
                                  │
              ┌───────────────────┼────────────────────┐
              │                   │                    │
    ┌─────────▼─────────┐ ┌───────▼────────┐ ┌─────────▼─────────┐
    │  POST /vpcs       │ │ GET /vpcs/*    │ │  GET /health      │
    │  (JWT protected)  │ │ (JWT protected)│ │  (public)         │
    │  DELETE /vpcs/{id}│ └───────┬────────┘ └─────────┬─────────┘
    │  (JWT protected)  │         │                    │
    └─────────┬─────────┘ ┌───────▼────────┐ ┌─────────▼─────────┐
              │           │  Lambda: get/  │ │  Lambda: health   │
    ┌─────────▼─────────┐ │  list/delete   │ └───────────────────┘
    │  Lambda: create   │ └───────┬────────┘
    │  vpc handler      │         │   
    └─────────┬─────────┘         │
              │                   │
    ┌─────────▼───────────────────▼────────────────────────┐
    │          DynamoDB (persist PENDING record)           │
    └─────────┬────────────────────────────────────────────┘
              │
    ┌─────────▼───────────────────────────────────┐
    │  Step Functions State Machine               │
    │  ┌───────────────────────────────────────┐  │
    │  │  Lambda: provision_vpc_task           │  │
    │  │   • Create VPC                        │  │
    │  │   • Create subnets                    │  │
    │  │   • Tag resources                     │  │
    │  │   • Persist result to DynamoDB        │  │
    │  └───────────────────────────────────────┘  │
    └─────────────────────────────────────────────┘
```

### AWS services used

| Service | Role |
|---------|------|
| **API Gateway (HTTP API)** | Entry point; JWT authorizer routes |
| **Amazon Cognito** | User pool + app client for JWT auth |
| **AWS Lambda (Python 3.12)** | Compute — one function per route + workflow task |
| **Step Functions** | Async provisioning orchestration |
| **DynamoDB** | Persistence layer — single table keyed by `request_id` |
| **Amazon EC2** | Target service — VPCs and subnets |
| **AWS CDK (Python)** | Infrastructure-as-code |

### Why these choices

- **Serverless by default** — no EC2 servers to manage; scales automatically; pay-per-use.
- **Step Functions** provides built-in retry, visibility, and state tracking for the provisioning workflow.
- **DynamoDB single-table** is sufficient for this key-based record pattern.
- **Cognito JWT authorizer** at API Gateway means no auth logic in application code.

---

## API endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/health` | No | Health check — public |
| `POST` | `/vpcs` | Yes | Create a VPC provisioning request |
| `GET` | `/vpcs/{request_id}` | Yes | Retrieve a specific request |
| `DELETE` | `/vpcs/{request_id}` | Yes | Delete provisioned VPC and subnets |
| `GET` | `/vpcs` | Yes | List all provisioning requests |

### POST /vpcs

**Request body:**
```json
{
  "name": "demo-vpc",
  "region": "eu-central-1",
  "cidr_block": "10.0.0.0/16",
  "subnets": [
    {"name": "public-a", "cidr_block": "10.0.1.0/24", "availability_zone": "eu-central-1a"},
    {"name": "private-a", "cidr_block": "10.0.2.0/24", "availability_zone": "eu-central-1a"}
  ],
  "tags": {
    "environment": "demo"
  }
}
```

**Response (202 Accepted):**
```json
{
  "request_id": "a1b2c3d4-...",
  "status": "PENDING"
}
```

### GET /vpcs/{request_id}

**Response (200 OK):**
```json
{
  "request_id": "a1b2c3d4-...",
  "status": "SUCCEEDED",
  "name": "demo-vpc",
  "region": "eu-central-1",
  "cidr_block": "10.0.0.0/16",
  "subnets_requested": [
    {"name": "public-a", "cidr_block": "10.0.1.0/24", "availability_zone": "eu-central-1a"}
  ],
  "tags": {"environment": "demo"},
  "requested_by": "user@example.com",
  "vpc_id": "vpc-0abc123...",
  "subnet_ids": [
    {"name": "public-a", "subnet_id": "subnet-0def456...", "cidr_block": "10.0.1.0/24", "availability_zone": "eu-central-1a"}
  ],
  "error_message": null,
  "created_at": "2024-01-01T00:00:00+00:00",
  "updated_at": "2024-01-01T00:01:00+00:00"
}
```

### GET /vpcs

**Response (200 OK):**
```json
{
  "items": [
    {"request_id": "a1b2c3d4-...", "status": "SUCCEEDED", "name": "demo-vpc", "vpc_id": "vpc-0abc123...", "created_at": "..."}
  ],
  "count": 1
}
```

### DELETE /vpcs/{request_id}

Deletes the VPC and all its subnets from AWS. Subnets are deleted first (required by AWS), then the VPC itself. If no VPC was provisioned (status `PENDING`), the record is marked `DELETED` and no AWS calls are made. Partial failures are reported so leftover resources can be cleaned up manually.

**Response (200 OK):**
```json
{
  "request_id": "a1b2c3d4-...",
  "status": "DELETED",
  "subnet_results": [
    {"name": "public-a", "subnet_id": "subnet-0def456...", "status": "deleted"}
  ]
}
```

**Response (207 Multi-Status) — partial failure:**
```json
{
  "request_id": "a1b2c3d4-...",
  "status": "PARTIAL_DELETE",
  "subnet_results": [
    {"name": "public-a", "subnet_id": "subnet-0def456...", "status": "deleted"}
  ],
  "vpc_error": "DependencyViolation: ..."
}
```

---

## Deployment

### Prerequisites

1. **Python 3.9+**
2. **AWS CLI** configured with credentials and a target region
3. **Node.js 18+** (required by CDK)
4. **AWS CDK CLI** (`npm install -g aws-cdk` or via pip: `pip install cdk`)
5. **CDK bootstrap** run once per account/region:
   ```bash
   cdk bootstrap aws://<ACCOUNT_ID>/<REGION>
   ```

### Steps

```bash
# 1. Clone the repo
git clone <repo-url>
cd aws_api_vpc

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements-dev.txt

# 4. Deploy the CDK stack
cdk deploy VpcProvisioningStack --region us-east-1
```

The `cdk deploy` command outputs:
- `ApiUrl` — the base URL of your API
- `CognitoUserPoolId` — required for token generation
- `CognitoUserPoolClientId` — required for token generation
- `CognitoUserPoolIssuer` — JWT issuer URL
- `TableName` — DynamoDB table
- `StateMachineArn` — Step Functions workflow ARN

### Destroy

```bash
cdk destroy VpcProvisioningStack
```

> **Warning:** `cdk destroy` removes the Cognito User Pool, API Gateway, Lambda functions, Step Functions state machine, and the DynamoDB table. Any VPCs and subnets already created in AWS are **not** automatically cleaned up — you must delete them manually.

---

## Authentication

The API uses **Amazon Cognito User Pools** with JWT authorizer at API Gateway.

After deploying, source the generated env file to get the stack outputs:

```bash
source demo/.env.demo
```

This exports `COGNITOUSERPOOLID`, `COGNITOUSERPOOLCLIENTID`, and `APIURL`.

### Create a test user

The app client is configured for `ADMIN_USER_PASSWORD_AUTH` only, so users must be created via the admin API (no email confirmation required):

```bash
USERNAME="test-user"
PASSWORD='Test1234!@'

aws cognito-idp admin-create-user \
  --user-pool-id "$COGNITOUSERPOOLID" \
  --username "$USERNAME" \
  --user-attributes Name=email,Value="${USERNAME}@example.com" \
  --region us-east-1

aws cognito-idp admin-set-user-password \
  --user-pool-id "$COGNITOUSERPOOLID" \
  --username "$USERNAME" \
  --password "$PASSWORD" \
  --permanent \
  --region us-east-1
```

### Obtain an access token

```bash
TOKEN=$(aws cognito-idp admin-initiate-auth \
  --user-pool-id "$COGNITOUSERPOOLID" \
  --client-id "$COGNITOUSERPOOLCLIENTID" \
  --auth-flow ADMIN_USER_PASSWORD_AUTH \
  --auth-parameters "USERNAME=${USERNAME},PASSWORD=${PASSWORD}" \
  --query "AuthenticationResult.AccessToken" \
  --output text \
  --region us-east-1)
```

### Use the token in API calls

**Health check (public — no token needed):**

```bash
curl -s "${APIURL}/health"
```

**Create a VPC:**

```bash
REQUEST_ID=$(curl -s -X POST "${APIURL}/vpcs" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "demo-vpc",
    "region": "us-east-1",
    "cidr_block": "10.0.0.0/16",
    "subnets": [
      {"name": "public-a", "cidr_block": "10.0.1.0/24", "availability_zone": "us-east-1a"},
      {"name": "private-a", "cidr_block": "10.0.2.0/24", "availability_zone": "us-east-1a"}
    ],
    "tags": {"environment": "demo"}
  }' | jq -r '.request_id')
echo "Request ID: $REQUEST_ID"
```

**Get a specific request (poll until SUCCEEDED or FAILED):**

```bash
curl -s "${APIURL}/vpcs/${REQUEST_ID}" \
  -H "Authorization: Bearer $TOKEN" | jq .
```

**List all requests:**

```bash
curl -s "${APIURL}/vpcs" \
  -H "Authorization: Bearer $TOKEN" | jq .
```

**Delete a VPC:**

```bash
curl -s -X DELETE "${APIURL}/vpcs/${REQUEST_ID}" \
  -H "Authorization: Bearer $TOKEN" | jq .
```

---

## Input validation

The API validates the following before creating a request:

| Check | Error returned |
|-------|---------------|
| CIDR format is valid IPv4 | `400 Bad Request` |
| Subnet mask between /16 and /28 | `400 Bad Request` |
| All subnets fit within VPC CIDR | `400 Bad Request` |
| No overlapping subnets | `400 Bad Request` |
| At least one subnet provided | `400 Bad Request` |
| Valid region format (e.g. us-east-1) | `400 Bad Request` |
| Valid AZ format (e.g. us-east-1a) | `400 Bad Request` |
| No duplicate subnet names | `400 Bad Request` |
| Valid JSON body | `400 Bad Request` |

---

## Testing

### Run all unit tests

```bash
pip install -r requirements-dev.txt
pytest tests/unit/ -v
```

### Test summary

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_cidr_validator.py` | 24 | CIDR format, subnet containment, overlap, region/AZ format, duplicate names |
| `test_request_store.py` | 4 | DynamoDB CRUD operations (put, get, list, update) |
| `test_handlers.py` | 15 | Valid/invalid requests, health check, retrieval, listing, delete |

### Run linting

```bash
ruff check app/ infra/ tests/
ruff format --check app/ infra/ tests/
```

---

## Request lifecycle

### Create VPC (POST /vpcs)

1. **Client** sends `POST /vpcs` with valid JSON + JWT token
2. **API Gateway** validates JWT via Cognito authorizer
3. **Lambda (create_vpc)** validates the request schema and CIDR rules
4. **Lambda** persists a `PENDING` record in DynamoDB
5. **Lambda** starts the Step Functions workflow and returns `202 Accepted`
6. **Step Functions** invokes the **provision_vpc_task** Lambda
7. **Lambda (provision_task)** creates the VPC, enables DNS, creates subnets, tags resources
8. **Lambda** updates DynamoDB with `SUCCEEDED` or `FAILED` status + resource IDs
9. If the Lambda throws an unhandled exception, Step Functions catches it and invokes **sfn_failure_handler**, which marks the record as `FAILED` so clients never see a stuck `IN_PROGRESS`
10. **Client** polls `GET /vpcs/{request_id}` to check progress

### Delete VPC (DELETE /vpcs/{request_id})

1. **Client** sends `DELETE /vpcs/{request_id}` with JWT token
2. **Lambda (delete_vpc)** retrieves the record from DynamoDB
3. If `vpc_id` is `None`, marks record as `DELETED` (nothing to clean up)
4. Otherwise deletes all subnets first (required by AWS), then the VPC
5. Partial failures are collected — the record is marked `PARTIAL_DELETE` (207) or `FAILED`
6. Full success marks the record as `DELETED`

### Workflow states

| State | Description |
|-------|-------------|
| `PENDING` | Record created, workflow not yet started |
| `IN_PROGRESS` | Workflow is actively provisioning |
| `SUCCEEDED` | VPC and subnets created successfully |
| `PARTIAL_DELETE` | Deletion started but some resources could not be removed — check `error_message` |
| `DELETED` | All provisioned resources have been deleted |
| `FAILED` | Provisioning or deletion failed — `error_message` contains details |
