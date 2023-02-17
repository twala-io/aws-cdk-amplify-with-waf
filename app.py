#!/usr/bin/env python3
from aws_cdk import App, Aspects
from cdk_nag import AwsSolutionsChecks

from src.amplify_add_on_stack import CustomAmplifyDistributionStack
from src.web_acl_stack import CustomWebAclStack

app = App()

def get_config():
    environment_id = app.node.try_get_context(
        key="config"
    )

    if not environment_id: 
        raise LookupError(
            "Context variable is missing on CDK command. See cdk.json for available values, eg: twala-<env>-ds-<project-name> Pass in as `-c config=twala-<env>-ds-<project-name>`"
        )

    unparsed_environment_parameters = app.node.try_get_context(
        key=environment_id
    )

    app_id = unparsed_environment_parameters["app_id"]
    branch_name = unparsed_environment_parameters["branch_name"]
    username = unparsed_environment_parameters["username"]
    password = unparsed_environment_parameters["password"]
    credentials = unparsed_environment_parameters["credentials"]
    cloudfront_id = unparsed_environment_parameters["cloudfront_id"]
    distribution_stack_name = unparsed_environment_parameters["distribution_stack_name"]

    return distribution_stack_name, branch_name, username, password, credentials, cloudfront_id, app_id

distribution_stack_name, branch_name, username, password, credentials, cloudfront_id, app_id = get_config()

CustomWebAclStack(
    app,
    "CustomWebAclStack",
    description="This stack creates WebACL to be attached to a CloudFront distribution \
        for a Web App hosted with Amplify",
    env={"region": "us-east-1"},
)

CustomAmplifyDistributionStack(
    app,
    distribution_stack_name,
    description="This stack creates a custom CloudFront distribution pointing to \
        Amplify app's default CloudFront distribution. \
        It also enables Basic Auth protection on specified branch. \
        Creates event based setup for invalidating custom CloudFront distribution when \
        a new version of Amplify App is deployed.",
    web_acl_arn=app.node.try_get_context("web_acl_arn"),
    app_id=app_id,
    branch_name=branch_name,
    username=username,
    password=password,
    credentials=credentials,
    cloudfront_id=cloudfront_id
)

Aspects.of(app).add(AwsSolutionsChecks())
app.synth()
