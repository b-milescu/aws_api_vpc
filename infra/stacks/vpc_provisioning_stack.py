"""Main CDK stack for the VPC Provisioning API.

Deploys:
- Cognito User Pool and App Client
- DynamoDB table for request records
- Lambda functions (create, get, list, health, provision task)
- Step Functions state machine
- API Gateway HTTP API with JWT authorizer
- IAM roles with least-privilege permissions
"""

from __future__ import annotations

from pathlib import Path
from aws_cdk import (
    Stack,
    CfnOutput,
    Duration,
    RemovalPolicy,
    BundlingOptions,
    aws_cognito as cognito,
    aws_dynamodb as dynamodb,
    aws_lambda as _lambda,
    aws_apigatewayv2 as apigw,
    aws_apigatewayv2_authorizers as authorizers,
    aws_apigatewayv2_integrations as integrations,
    aws_iam as iam,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
)
from constructs import Construct


class VpcProvisioningStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── Cognito User Pool ────────────────────────────────────────────────
        self.user_pool = cognito.UserPool(
            self,
            "UserPool",
            user_pool_name="vpc-provisioning-users",
            self_sign_up_enabled=True,
            sign_in_aliases=cognito.SignInAliases(username=True, email=True),
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_uppercase=True,
                require_lowercase=True,
                require_digits=True,
                require_symbols=True,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

        user_pool_client = self.user_pool.add_client(
            "ApiClient",
            user_pool_client_name="vpc-api-client",
            generate_secret=False,
            auth_flows=cognito.AuthFlow(admin_user_password=True),
            access_token_validity=Duration.hours(1),
            id_token_validity=Duration.hours(1),
        )

        # ── DynamoDB Table ───────────────────────────────────────────────────
        self.table = dynamodb.Table(
            self,
            "VpcRequestsTable",
            partition_key=dynamodb.Attribute(
                name="request_id", type=dynamodb.AttributeType.STRING
            ),
            removal_policy=RemovalPolicy.DESTROY,
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
        )

        # ── Lambda Functions ─────────────────────────────────────────────────
        self.lambda_functions = self._create_lambda_functions()

        # ── Step Functions State Machine ──────────────────────────────────────
        state_machine = self._create_state_machine()

        # ── Grant DynamoDB permissions to all Lambdas ─────────────────────────
        self.table.grant_read_write_data(self.lambda_functions["create_vpc"])
        self.table.grant_read_data(self.lambda_functions["get_vpc"])
        self.table.grant_read_data(self.lambda_functions["list_vpcs"])
        self.table.grant_read_write_data(self.lambda_functions["provision_task"])
        self.table.grant_read_write_data(self.lambda_functions["delete_vpc"])
        self.table.grant_read_write_data(self.lambda_functions["sfn_failure"])

        # ── Grant Step Functions permissions ──────────────────────────────────
        state_machine.grant_start_execution(self.lambda_functions["create_vpc"])

        # ── Grant Step Functions role to invoke the provision task Lambda ─────
        self.lambda_functions["provision_task"].grant_invoke(state_machine.role)

        # ── API Gateway HTTP API ──────────────────────────────────────────────
        self.api = self._create_api_gateway(state_machine.state_machine_arn)

        # ── Update create_vpc Lambda with the actual SM ARN ───────────────────
        self.lambda_functions["create_vpc"].add_environment(
            "STATE_MACHINE_ARN", state_machine.state_machine_arn
        )

        # ── Outputs ──────────────────────────────────────────────────────────
        CfnOutput(
            self, "ApiUrl", value=self.api.api_endpoint, description="API base URL"
        )
        CfnOutput(
            self,
            "CognitoUserPoolId",
            value=self.user_pool.user_pool_id,
            description="Cognito User Pool ID",
        )
        CfnOutput(
            self,
            "CognitoUserPoolClientId",
            value=user_pool_client.user_pool_client_id,
            description="Cognito App Client ID",
        )
        CfnOutput(
            self,
            "CognitoUserPoolIssuer",
            value=f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool.user_pool_id}",
            description="Cognito JWT issuer",
        )
        CfnOutput(
            self,
            "TableName",
            value=self.table.table_name,
            description="DynamoDB table name",
        )
        CfnOutput(
            self,
            "StateMachineArn",
            value=state_machine.state_machine_arn,
            description="Step Functions state machine ARN",
        )

    def _create_lambda_functions(self) -> dict[str, _lambda.Function]:
        """Create all Lambda functions with shared configuration."""
        project_root = str(Path(__file__).parent.parent.parent)

        # Bundle the full project so dependencies from requirements.txt
        # are available AND the `app` package is importable by its own name.
        bundled_code = _lambda.Code.from_asset(
            project_root,
            bundling=BundlingOptions(
                image=_lambda.Runtime.PYTHON_3_12.bundling_image,
                command=[
                    "bash",
                    "-c",
                    "pip install -r /asset-input/requirements.txt -t /asset-output "
                    "--platform manylinux2014_x86_64 --implementation cp "
                    "--python-version 312 --only-binary=:all: "
                    "&& cp -r /asset-input/app /asset-output/",
                ],
            ),
        )

        _handler = {
            "runtime": _lambda.Runtime.PYTHON_3_12,
            "code": bundled_code,
        }

        return {
            "create_vpc": _lambda.Function(
                self,
                "CreateVpcFunction",
                handler="app.handlers.create_vpc.handler",
                function_name="vpc-api-create-vpc",
                memory_size=256,
                timeout=Duration.seconds(60),
                environment={
                    "TABLE_NAME": self.table.table_name,
                    "STATE_MACHINE_ARN": "PLACEHOLDER",  # replaced after SM creation
                },
                **_handler,
            ),
            "get_vpc": _lambda.Function(
                self,
                "GetVpcFunction",
                handler="app.handlers.get_vpc.handler",
                function_name="vpc-api-get-vpc",
                memory_size=256,
                timeout=Duration.seconds(60),
                environment={"TABLE_NAME": self.table.table_name},
                **_handler,
            ),
            "list_vpcs": _lambda.Function(
                self,
                "ListVpcsFunction",
                handler="app.handlers.list_vpcs.handler",
                function_name="vpc-api-list-vpcs",
                memory_size=256,
                timeout=Duration.seconds(60),
                environment={"TABLE_NAME": self.table.table_name},
                **_handler,
            ),
            "health": _lambda.Function(
                self,
                "HealthFunction",
                handler="app.handlers.health.handler",
                function_name="vpc-api-health",
                memory_size=256,
                timeout=Duration.seconds(60),
                **_handler,
            ),
            "provision_task": _lambda.Function(
                self,
                "ProvisionTaskFunction",
                handler="app.handlers.provision_vpc_task.handler",
                function_name="vpc-provision-task",
                memory_size=512,
                timeout=Duration.minutes(5),
                environment={
                    "TABLE_NAME": self.table.table_name,
                },
                **_handler,
            ),
            "delete_vpc": _lambda.Function(
                self,
                "DeleteVpcFunction",
                handler="app.handlers.delete_vpc.handler",
                function_name="vpc-api-delete-vpc",
                memory_size=256,
                timeout=Duration.seconds(60),
                environment={"TABLE_NAME": self.table.table_name},
                **_handler,
            ),
            "sfn_failure": _lambda.Function(
                self,
                "SfnFailureFunction",
                handler="app.handlers.sfn_failure_handler.handler",
                function_name="vpc-sfn-failure-handler",
                memory_size=128,
                timeout=Duration.seconds(15),
                environment={"TABLE_NAME": self.table.table_name},
                **_handler,
            ),
        }

    def _create_state_machine(self) -> sfn.StateMachine:
        """Create a Step Functions state machine for VPC provisioning."""
        invoke_task = tasks.LambdaInvoke(
            self,
            "Provision VPC and Subnets",
            lambda_function=self.lambda_functions["provision_task"],
            payload=sfn.TaskInput.from_object(
                {
                    "request_id.$": "$.request_id",
                }
            ),
            retry_on_service_exceptions=True,
            result_path=sfn.JsonPath.DISCARD,
        )

        # Catch unhandled runtime failures and mark the record as FAILED
        sfn_failure_task = tasks.LambdaInvoke(
            self,
            "Handle Provision Failure",
            lambda_function=self.lambda_functions["sfn_failure"],
            payload=sfn.TaskInput.from_object(
                {
                    "error.$": "$.Error",
                    "cause.$": "$.Cause",
                    "input.$": "$$.Execution.Input",
                }
            ),
            retry_on_service_exceptions=True,
            result_path=sfn.JsonPath.DISCARD,
        )

        invoke_task.add_catch(
            sfn_failure_task,
            errors=["States.ALL"],
        )

        return sfn.StateMachine(
            self,
            "ProvisionVpcStateMachine",
            state_machine_name="vpc-provisioning-workflow",
            definition_body=sfn.DefinitionBody.from_chainable(invoke_task),
            timeout=Duration.minutes(10),
            tracing_enabled=True,
        )

    def _create_api_gateway(self, state_machine_arn: str) -> apigw.HttpApi:
        """Create the HTTP API with JWT authorizer and routes."""
        http_api = apigw.HttpApi(self, "VpcApi", api_name="vpc-provisioning-api")

        # JWT authorizer using Cognito User Pool
        authorizer = authorizers.HttpUserPoolAuthorizer(
            "CognitoAuthorizer",
            pool=self.user_pool,
            user_pool_clients=[self.user_pool.node.find_child("ApiClient")],
        )

        # ── Create Lambda integrations ──────────────────────────────────────
        create_integration = integrations.HttpLambdaIntegration(
            "CreateVpcIntegration", self.lambda_functions["create_vpc"]
        )
        get_integration = integrations.HttpLambdaIntegration(
            "GetVpcIntegration", self.lambda_functions["get_vpc"]
        )
        list_integration = integrations.HttpLambdaIntegration(
            "ListVpcsIntegration", self.lambda_functions["list_vpcs"]
        )
        health_integration = integrations.HttpLambdaIntegration(
            "HealthIntegration", self.lambda_functions["health"]
        )
        delete_integration = integrations.HttpLambdaIntegration(
            "DeleteVpcIntegration", self.lambda_functions["delete_vpc"]
        )

        # POST /vpcs (protected)
        http_api.add_routes(
            path="/vpcs",
            methods=[apigw.HttpMethod.POST],
            integration=create_integration,
            authorizer=authorizer,
        )

        # GET /vpcs/{request_id} (protected)
        http_api.add_routes(
            path="/vpcs/{request_id}",
            methods=[apigw.HttpMethod.GET],
            integration=get_integration,
            authorizer=authorizer,
        )

        # GET /vpcs (protected)
        http_api.add_routes(
            path="/vpcs",
            methods=[apigw.HttpMethod.GET],
            integration=list_integration,
            authorizer=authorizer,
        )

        # GET /health (public)
        http_api.add_routes(
            path="/health",
            methods=[apigw.HttpMethod.GET],
            integration=health_integration,
        )

        # DELETE /vpcs/{request_id} (protected)
        http_api.add_routes(
            path="/vpcs/{request_id}",
            methods=[apigw.HttpMethod.DELETE],
            integration=delete_integration,
            authorizer=authorizer,
        )

        # ── EC2 permissions for provision_task Lambda ─────────────────────────
        self.lambda_functions["provision_task"].add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "ec2:CreateVpc",
                    "ec2:CreateSubnet",
                    "ec2:ModifyVpcAttribute",
                    "ec2:CreateTags",
                    "ec2:DescribeVpcs",
                    "ec2:DescribeSubnets",
                ],
                resources=["*"],
            )
        )

        # ── EC2 permissions for delete_vpc Lambda ─────────────────────────────
        self.lambda_functions["delete_vpc"].add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "ec2:DeleteSubnet",
                    "ec2:DeleteVpc",
                    "ec2:DescribeSubnets",
                    "ec2:DescribeVpcs",
                ],
                resources=["*"],
            )
        )

        # ── Step Functions permissions for create_vpc Lambda ──────────────────
        self.lambda_functions["create_vpc"].add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "states:StartExecution",
                    "states:DescribeStateMachine",
                ],
                resources=[state_machine_arn],
            )
        )

        return http_api
