# Architecture: VPC Provisioning API

## Overview

A serverless, authenticated API on AWS that provisions VPCs with multiple subnets. All infrastructure is defined in code via AWS CDK (Python).

## Component diagram

```
┌──────────────────────────────────────────────────────────────┐
│                         Client                               │
│                   (browser / curl / SDK)                     │
└────────────────────────┬─────────────────────────────────────┘
                         │ HTTPS
                         ▼
┌──────────────────────────────────────────────────────────────┐
│                    API Gateway (HTTP API)                    │
│                                                              │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐   │
│  │ POST /vpcs  │  │ GET /vpcs/*  │  │ DELETE /vpcs/{id}  │   │
│  │ [JWT Auth]  │  │ [JWT Auth]   │  │     [JWT Auth]     │   │
│  │ DELETE      │  └──────┬───────┘  └──────────┬─────────┘   │
│  └──────┬──────┘         │                     │             │
└─────────┼────────────────┼─────────────────────┼─────────────┘
          │                │                     │
          ▼                ▼                     ▼
┌──────────────────┐ ┌───────────────┐  ┌──────────────────────┐
│ Lambda: create   │ │ Lambda: get/  │  │ Lambda: delete_vpc   │
│ vpc              │ │ list          │  │ (Python 3.12)        │
│ (Python 3.12)    │ │ (Python 3.12) │  │                      │
└────────┬─────────┘ └───────────────┘  └──────────┬───────────┘
         │                                         │
         │ 1. Create PENDING record                │
         ▼                                         ▼
┌──────────────────────────────────────────────────────────┐
│                    DynamoDB                              │
│  Partition key: request_id (string)                      │
│  Stores: status, spec, vpc_id, subnet_ids, timestamps    │
│                                                          │
│  delete_vpc reads record, then:                          │
│   1. delete_subnets (EC2)                                │
│   2. delete_vpc (EC2) — only after subnets are gone      │
│   3. Update record → DELETED / FAILED / PARTIAL_DELETE   │
└──────────────────────────────────────────────────────────┘
         │ 2. Start workflow
         ▼
┌──────────────────────────────────────────────────────────┐
│              Step Functions State Machine                │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Lambda Invoke: provision_vpc_task                 │  │
│  │  ┌──────────────────────────────────────────────┐  │  │
│  │  │  1. Read request record from DynamoDB        │  │  │
│  │  │  2. Update status → IN_PROGRESS              │  │  │
│  │  │  3. CreateVpc (EC2 API)                      │  │  │
│  │  │  4. Enable DNS hostnames                     │  │  │
│  │  │  5. CreateSubnet × N (EC2 API)               │  │  │
│  │  │  6. Tag resources                            │  │  │
│  │  │  7. Update record → SUCCEEDED / FAILED       │  │  │
│  │  └──────────────────────────────────────────────┘  │  │
│  └──────────────────────┬─────────────────────────────┘  │
│       on unhandled error│ (Catch: States.ALL)             │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Lambda Invoke: sfn_failure_handler                │  │
│  │  Updates record → FAILED (prevents stuck states)  │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────┐
│              Amazon Cognito User Pool                    │
│  ┌────────────────────────────────────────────────────┐  │
│  │  JWT Authorizer (API Gateway)                      │  │
│  │  - Issuer: https://cognito-idp.{region}.amazonaws… │  │
│  │  - Audience: User Pool Client ID                   │  │
│  │  - Any authenticated user allowed                  │  │
│  └────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────┘
```

## Data flow

### Create VPC (POST /vpcs)

```
Client ──JWT──▶ API Gateway ──▶ Lambda(create_vpc)
                                      │
                                      ├─ Validate request (Pydantic + CIDR checks)
                                      ├─ Persist PENDING record in DynamoDB
                                      ├─ Start Step Functions workflow
                                      └─ Return 202 {request_id, status: PENDING}
```

### Provisioning (Step Functions)

```
Step Functions ─▶ Lambda(provision_vpc_task)
                        │
                        ├─ Get record from DynamoDB
                        ├─ Update status → IN_PROGRESS
                        ├─ CreateVpc (EC2 API) — skipped if vpc_id already set (DynamoDB guard)
                        ├─ CreateSubnet × N (EC2 API) — skipped if subnet_ids already set
                        ├─ Tag resources
                        ├─ Update record → SUCCEEDED + resource IDs
                        └─ Or: Update record → FAILED + error_message

Step Functions (on unhandled exception) ─▶ Lambda(sfn_failure_handler)
                        │
                        ├─ Parse request_id from original workflow input
                        └─ Update record → FAILED + error detail
```

### Retrieve (GET /vpcs/{request_id})

```
Client ──JWT──▶ API Gateway ──▶ Lambda(get_vpc)
                                      │
                                      ├─ Get record from DynamoDB
                                      └─ Return 200 {full record data}
```

### Delete VPC (DELETE /vpcs/{request_id})

```
Client ──JWT──▶ API Gateway ──▶ Lambda(delete_vpc)
                                      │
                                      ├─ Get record from DynamoDB
                                      ├─ If vpc_id is None → mark DELETED (nothing to delete)
                                      ├─ Delete subnets first (EC2 API) — best-effort per subnet
                                      ├─ Delete VPC (EC2 API) — must succeed after subnets
                                      ├─ If all succeed → status = DELETED
                                      ├─ If partial failure → status = PARTIAL_DELETE (207)
                                      └─ Return {status, subnet_results, any errors}
```

## IAM permissions

| Lambda | Permissions |
|--------|------------|
| create_vpc | DynamoDB put_item, Step Functions StartExecution |
| get_vpc | DynamoDB get_item |
| list_vpcs | DynamoDB scan |
| delete_vpc | DynamoDB get_item/put_item, EC2 DeleteVpc/DeleteSubnet/DescribeSubnets/DescribeVpcs |
| provision_vpc_task | DynamoDB put_item/get_item, EC2 CreateVpc/CreateSubnet/ModifyVpcAttribute/CreateTags/DescribeVpcs/DescribeSubnets |
| sfn_failure_handler | DynamoDB get_item/put_item |

## Security

- API protected by Cognito JWT authorizer at API Gateway level (`POST /vpcs`, `GET /vpcs/*`, `DELETE /vpcs/{request_id}`)
- `GET /health` is public (no auth required)
- No secrets in code or environment variables
- Least-privilege IAM roles per Lambda function
- Pydantic validation prevents injection attacks
