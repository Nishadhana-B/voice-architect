"""Scripted design reviews with ground truth, so accuracy can be measured instead of eyeballed.

Each scenario lists what the caller says, which component types must end up in the design, and which rules
must fire. The 'clean' scenario is a negative control: a sound design that must not raise high-severity risks."""
from __future__ import annotations

from dataclasses import dataclass, field

from .audio_io import Say


@dataclass
class Scenario:
    name: str
    lines: list
    expect_types: dict          # component type -> minimum count
    expect_rules: set           # rules that must be present in the final design analysis
    forbid_high: bool = False   # negative control: no high-severity finding allowed
    expect_cost_question: bool = False
    allow_types: set = field(default_factory=set)   # extra component types that are a fair reading of the speech
    notes: str = ""


SCENARIOS: dict[str, Scenario] = {
    "store": Scenario(
        "store",
        [Say("Hi. I am designing an online store. Customers reach it through CloudFront, which forwards to an "
             "Application Load Balancer."),
         Say("The load balancer sends traffic to two EC2 web servers."),
         Say("The web servers read and write a Postgres database for orders. It runs in a single availability zone "
             "and no backups are configured."),
         Say("Product images are in a public S3 bucket. We expect about two hundred requests per second."),
         Say("What are the biggest risks?"),
         Say("What would this cost per month?"),
         Say("Please export the design document.")],
        {"cdn": 1, "alb": 1, "ec2": 1, "rds": 1, "s3": 1},
        {"db-single-az", "db-no-backups", "s3-public"}, expect_cost_question=True),
    "pipeline": Scenario(
        "pipeline",
        [Say("Hi. I am building an order intake pipeline. An API Gateway with no authentication invokes a Lambda "
             "function."),
         Say("The Lambda writes orders to a DynamoDB table that has no point in time recovery, and it also sends "
             "each order to an SQS queue."),
         Say("A second Lambda function consumes the queue. The queue has no dead letter queue."),
         Say("We expect fifty requests per second. What are the risks?"),
         Say("What does it cost per month?")],
        {"apigw": 1, "lambda": 2, "dynamodb": 1, "sqs": 1},
        {"api-no-auth", "dynamodb-no-pitr", "queue-no-dlq"}, expect_cost_question=True),
    "clean": Scenario(
        "clean",
        [Say("Hi. I am designing a web application. Users come through CloudFront with a web application firewall "
             "attached, to a load balancer."),
         Say("The load balancer sends traffic to an ECS Fargate service with three tasks and auto scaling."),
         Say("The service uses an Aurora database with two instances, with backups and encryption enabled. We also "
             "use CloudWatch for monitoring."),
         Say("Are there any risks?")],
        {"cdn": 1, "alb": 1, "ecs": 1, "aurora": 1, "monitoring": 1}, set(), forbid_high=True,
        allow_types={"waf"}, notes="'CloudFront with a web application firewall attached' may be one box or two."),
    # Held-out: written AFTER the fixes were tuned on the three scenarios above. Different services and flaws.
    "notify": Scenario(
        "notify",
        [Say("Hi. I am designing a notification service. A mobile app calls an API Gateway that uses Cognito for "
             "authentication, and the gateway invokes a Lambda function."),
         Say("The Lambda publishes events to an SNS topic, and a second Lambda function subscribes to the topic. "
             "That subscriber has no failure destination."),
         Say("The subscriber writes to a DynamoDB table that has encryption disabled. We also keep sessions in a "
             "Redis cache with a single node."),
         Say("Is there anything risky?")],
        {"apigw": 1, "lambda": 2, "sns": 1, "dynamodb": 1, "cache": 1},
        {"lambda-async-no-dlq", "storage-unencrypted", "cache-single-node"},
        allow_types={"users", "cognito"}, notes="held-out scenario, not used while tuning"),
    # Showcase for screenshots: a large, deliberately flawed design. Not used for the quality numbers.
    "marketplace": Scenario(
        "marketplace",
        [Say("Hi. I am designing an online marketplace. Customers come through CloudFront with a web application "
             "firewall to an Application Load Balancer."),
         Say("The load balancer sends traffic to an ECS Fargate web service with four tasks and auto scaling."),
         Say("The web service calls an API Gateway that has no authentication, and the gateway invokes an orders "
             "Lambda function."),
         Say("The orders Lambda writes to a Postgres database. It runs in a single availability zone and there are "
             "no backups. The orders Lambda also publishes order events to an SNS topic."),
         Say("A payments Lambda function and an email Lambda function both subscribe to the topic. Neither has a "
             "failure destination."),
         Say("The payments Lambda writes to a DynamoDB table that has point in time recovery disabled."),
         Say("Order events also go to an SQS queue with no dead letter queue, and a fulfilment Lambda function "
             "consumes that queue."),
         Say("Product images are in a public S3 bucket, served through CloudFront."),
         Say("We keep sessions in a Redis cache with a single node. The web service uses it."),
         Say("A NAT gateway lets the services reach the internet. We expect about one hundred requests per second."),
         Say("What are the biggest risks?"),
         Say("What does this cost per month?"),
         Say("Please export the design document.")],
        {"cdn": 1, "alb": 1, "ecs": 1, "apigw": 1, "lambda": 4, "rds": 1, "sns": 1, "dynamodb": 1, "sqs": 1,
         "s3": 1, "cache": 1, "nat": 1},
        {"db-single-az", "db-no-backups", "api-no-auth", "s3-public", "dynamodb-no-pitr", "queue-no-dlq",
         "cache-single-node"},
        allow_types={"users", "waf"}, expect_cost_question=True, notes="large showcase design for screenshots"),
}
