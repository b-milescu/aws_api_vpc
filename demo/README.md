# Demo scripts

End-to-end scripts that deploy the stack, create a VPC through the API, and
delete it again.  Each script is idempotent and safe to re-run.

## Prerequisites

| Tool | Why |
|------|-----|
| Python 3.9+ | CDK Python runtime, output export helper |
| AWS CLI ≥ 2 | Authenticate Cognito, bootstrap CDK |
| AWS CDK CLI (`npm i -g aws-cdk`) | Deploy infrastructure |
| `jq` | Parse JSON responses |
| `curl` | Call the API |

## Quick start

```bash
# 1. Deploy the stack (exports demo/.env.demo)
./demo/01-deploy.sh us-east-1

# 2. Create a VPC (auto-authenticates, polls until done)
./demo/02-create-vpc.sh my-demo-vpc

# 3. Delete the VPC (reads request_id from previous step)
./demo/03-delete-vpc.sh
```

## Scripts

### `01-deploy.sh` — Deploy infrastructure

Bootstraps CDK (if needed), deploys the `VpcProvisioningStack`, and writes
`demo/.env.demo` with the stack outputs (API URL, Cognito IDs, table name,
state machine ARN).  Subsequent scripts source this file.

```bash
./demo/01-deploy.sh [AWS_REGION]   # default: us-east-1
source demo/.env.demo
```

**Outputs:**

| File | Contents |
|------|----------|
| `demo/.env.demo` | Shell-compatible key=value pairs from CDK outputs |
| `demo/cdk-output.json` | Raw CDK output JSON |

### `02-create-vpc.sh` — Create a VPC via the API

1. Creates an ephemeral Cognito user
2. Obtains a JWT access token
3. POSTs a VPC creation request to the API (`202 Accepted`)
4. Polls `GET /vpcs/{request_id}` every 5 seconds until `SUCCEEDED` or `FAILED`
5. Saves the `request_id` to `demo/request_id.txt` for the delete script

```bash
./demo/02-create-vpc.sh [NAME]     # default: demo-vpc
```

**Arguments:**
- `NAME` — Friendly name for the VPC (optional; default `demo-vpc`)

**Outputs:**
- `demo/request_id.txt` — The request ID to use with the delete script

### `03-delete-vpc.sh` — Delete the provisioned VPC

1. Creates an ephemeral Cognito user and obtains a JWT
2. Sends `DELETE /vpcs/{request_id}` to delete the VPC and subnets
3. Verifies the final record status via `GET /vpcs/{request_id}`

```bash
source demo/.env.demo
./demo/03-delete-vpc.sh [REQUEST_ID]
```

**Arguments:**
- `REQUEST_ID` — The request ID from the create step. If omitted, reads
  `demo/request_id.txt`.

> **Note:** The delete script creates a *different* Cognito user than the
> create script. Because tenant isolation is intentionally absent (M4 in the
> review report), this demonstrates that any authenticated user can list or
> delete any VPC request — a known limitation of the demo scope.

## Teardown

```bash
cdk destroy VpcProvisioningStack --region us-east-1
rm -f demo/.env.demo demo/cdk-output.json demo/request_id.txt
```

> **Warning:** `cdk destroy` removes the platform resources (Cognito, API
> Gateway, Lambda, DynamoDB, Step Functions) but does **not** remove VPCs and
> subnets provisioned at runtime by the API. Make sure to delete the VPC via
> `03-delete-vpc.sh` first, or clean up manually in the AWS console.
