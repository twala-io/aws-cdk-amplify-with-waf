import os
from urllib.parse import quote

import aws_cdk.aws_cloudfront as cloudfront
import aws_cdk.aws_cloudfront_origins as origins
from aws_cdk import Aws, CfnOutput, CustomResource, Duration, Stack
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import custom_resources as custom
from aws_cdk.aws_lambda import Code, Function, Runtime, Tracing
from aws_cdk.aws_logs import RetentionDays
from cdk_nag import NagSuppressions
from constructs import Construct

dirname = os.path.dirname(__file__)


class CustomAmplifyDistributionStack(Stack):
    def __init__(
        self,
        scope: Construct,
        id: str,
        web_acl_arn: str,
        app_id: str,
        branch_name: str,
        username: str,
        password: str,
        credentials: str,
        cloudfront_id: str,
        **kwargs,
    ):
        super().__init__(scope, id, **kwargs)

        # Lambda Baic Execution Permissions
        lambda_exec_policy = iam.ManagedPolicy.from_managed_policy_arn(
            self,
            "lambda-exec-policy-00",
            managed_policy_arn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
        )

        amplify_auth = username + ':' + password
        amplify_auth_credentials = credentials

        app_branch_update = custom.AwsCustomResource(
            self,
            "rAmplifyAppBranchUpdate",
            policy=custom.AwsCustomResourcePolicy.from_sdk_calls(
                resources=[
                    f"arn:aws:amplify:{Aws.REGION}:{Aws.ACCOUNT_ID}:apps/{app_id}/branches/{quote(branch_name, safe='')}",
                ]
            ),
            on_create=custom.AwsSdkCall(
                service="Amplify",
                action="updateBranch",
                parameters={
                    "appId": app_id,
                    "branchName": branch_name,
                    "enableBasicAuth": True,
                    "basicAuthCredentials": amplify_auth_credentials,
                },
                physical_resource_id=custom.PhysicalResourceId.of(
                    "amplify-branch-update"
                ),
            ),
            on_update=custom.AwsSdkCall(
                service="Amplify",
                action="updateBranch",
                parameters={
                    "appId": app_id,
                    "branchName": branch_name,
                    "enableBasicAuth": True,
                    "basicAuthCredentials": amplify_auth_credentials,
                },
                physical_resource_id=custom.PhysicalResourceId.of(
                    "amplify-branch-update"
                ),
            ),
        )

        # Format amplify branch
        formatted_amplify_branch = branch_name.replace("/", "-")

        # Define cloudfront distribution
        amplify_app_distribution = cloudfront.Distribution(
            self,
            "rCustomCloudFrontDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.HttpOrigin(
                    domain_name=f"{formatted_amplify_branch}.{app_id}.amplifyapp.com",
                    custom_headers={
                        "Authorization": "Basic " + amplify_auth_credentials
                    },
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            price_class=cloudfront.PriceClass.PRICE_CLASS_ALL,
            web_acl_id=web_acl_arn,
            comment=cloudfront_id,
        )

        self.amplify_app_distribution = amplify_app_distribution

        # CloudFront cache invalidation Lambda Execution Role
        cache_invalidation_function_role = iam.Role(
            self,
            "rCacheInvalidationFunctionCustomRole",
            description="Role used by cache_invalidation lambda function",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        )

        cache_invalidation_function_role.add_managed_policy(lambda_exec_policy)

        cache_invalidation_function_custom_policy = iam.ManagedPolicy(
            self,
            "rCacheInvalidationFunctionCustomPolicy",
            statements=[
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=[
                        "cloudfront:CreateInvalidation",
                    ],
                    resources=[
                        f"arn:aws:cloudfront::{Aws.ACCOUNT_ID}:distribution/{amplify_app_distribution.distribution_id}"
                    ],
                ),
            ],
        )

        cache_invalidation_function_role.add_managed_policy(
            cache_invalidation_function_custom_policy
        )

        # Function to trigger CloudFront invalidation
        cache_invalidation_function = Function(
            self,
            "rCacheInvalidationFunction",
            description="custom function to trigger cloudfront cache invalidation",  # noqa 501
            runtime=Runtime.PYTHON_3_9,
            handler="lambda_function.lambda_handler",
            code=Code.from_asset(
                path=os.path.join(dirname, "functions/cache_invalidation")
            ),
            timeout=Duration.seconds(30),
            memory_size=128,
            role=cache_invalidation_function_role,
            tracing=Tracing.ACTIVE,
            log_retention=RetentionDays.SIX_MONTHS,
            environment={
                "DISTRIBUTION_ID": amplify_app_distribution.distribution_id,
            },
        )

        events.Rule(
            self,
            "rInvokeCacheInvalidation",
            description="Rule is triggered when the Amplify app is redeployed, which creates a CloudFront cache invalidation request",  # noqa E501
            event_pattern=events.EventPattern(
                source=["aws.amplify"],
                detail_type=["Amplify Deployment Status Change"],
                detail={
                    "appId": [app_id],
                    "branchName": [branch_name],
                    "jobStatus": ["SUCCEED"],
                },
            ),
            targets=[
                targets.LambdaFunction(cache_invalidation_function, retry_attempts=2)
            ],
        )

        CfnOutput(
            self,
            "oCloudFrontDistributionDomain",
            value=amplify_app_distribution.distribution_domain_name,
        )

        NagSuppressions.add_resource_suppressions(
            amplify_app_distribution,
            suppressions=[
                {
                    "id": "AwsSolutions-CFR1",
                    "reason": "geo restictions to be enabled using WAF by user",
                },
                {
                    "id": "AwsSolutions-CFR3",
                    "reason": "user to override the logging property as required",
                },
                {
                    "id": "AwsSolutions-CFR4",
                    "reason": "user to override when using a custom domain and certificate",
                },
            ],
        )

        NagSuppressions.add_resource_suppressions(
            cache_invalidation_function_role,
            suppressions=[
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": "CDK generated service role and policy",
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "CDK generated service role and policy",
                },
                {
                    "id": "AwsSolutions-L1",
                    "reason": "CDK generated custom resource",
                },
            ],
            apply_to_children=True,
        )

        NagSuppressions.add_resource_suppressions_by_path(
            self,
            path=f"/{self.stack_name}/LogRetentionaae0aa3c5b4d4f87b02d85b201efdd8a/ServiceRole/Resource",
            suppressions=[
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": "CDK generated service role and policy",
                },
            ],
        )

        NagSuppressions.add_resource_suppressions_by_path(
            self,
            path=f"/{self.stack_name}/LogRetentionaae0aa3c5b4d4f87b02d85b201efdd8a/ServiceRole/DefaultPolicy/Resource",
            suppressions=[
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "CDK generated service role and policy",
                },
            ],
        )

        NagSuppressions.add_resource_suppressions_by_path(
            self,
            path=f"/{self.stack_name}/AWS679f53fac002430cb0da5b7982bd2287/ServiceRole/Resource",
            suppressions=[
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": "CDK generated service role and policy",
                },
            ],
        )

        NagSuppressions.add_resource_suppressions_by_path(
            self,
            path=f"/{self.stack_name}/AWS679f53fac002430cb0da5b7982bd2287/Resource",
            suppressions=[
                {
                    "id": "AwsSolutions-L1",
                    "reason": "CDK generated custom resource",
                },
            ],
        )
