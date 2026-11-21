"""Well-Architected style design checks. Deterministic on purpose: the model reports findings, it does not
invent them. confidence is 'stated' (the engineer said so) or 'assumed' (not stated, so ask)."""
from __future__ import annotations

from dataclasses import dataclass, field

from .model import Design

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class Finding:
    id: str
    rule: str
    pillar: str
    severity: str
    components: list[str]
    message: str
    why: str
    fix: str
    confidence: str  # stated | assumed
    keywords: list[str] = field(default_factory=list)  # words a spoken mention should contain (for scoring)

    def to_dict(self) -> dict:
        return {"id": self.id, "rule": self.rule, "pillar": self.pillar, "severity": self.severity,
                "components": self.components, "message": self.message, "why": self.why, "fix": self.fix,
                "confidence": self.confidence}


def _is(v, want: bool):
    return v is want


def analyze(d: Design) -> list[Finding]:
    out: list[Finding] = []
    comps = d.components
    names = {c.id: c.name for c in comps.values()}
    inbound: dict[str, list] = {}
    outbound: dict[str, list] = {}
    for x in d.connections:
        inbound.setdefault(x.dst, []).append(x)
        outbound.setdefault(x.src, []).append(x)

    def add(rule, comp, pillar, sev, msg, why, fix, conf, kw):
        out.append(Finding(f"{rule}:{comp.id if comp else 'design'}", rule, pillar, sev,
                           [comp.name] if comp else [], msg, why, fix, conf, kw))

    # R1/R2/R4/R15: databases
    for c in d.of_type("rds", "aurora"):
        multi = c.attrs.get("multi_az") if c.type == "rds" else (
            None if c.attrs.get("instances") is None else c.attrs["instances"] >= 2)
        if multi is not True:
            conf = "stated" if multi is False else "assumed"
            add("db-single-az", c, "Reliability", "high" if conf == "stated" else "medium",
                f"{c.name} runs in a single availability zone, so one zone failure takes the database down."
                if conf == "stated" else f"It is not clear whether {c.name} is multi-AZ.",
                "A single-AZ database has no automatic failover.", "Enable Multi-AZ (or add a second Aurora instance).",
                conf, ["availability zone", "multi-az", "single az", "failover", "single-az"])
        if c.attrs.get("backups") is not True:
            conf = "stated" if c.attrs.get("backups") is False else "assumed"
            add("db-no-backups", c, "Reliability", "high" if conf == "stated" else "medium",
                f"{c.name} has no backups." if conf == "stated" else f"It is not clear {c.name} has backups.",
                "Without backups, data loss or corruption is unrecoverable.",
                "Turn on automated backups with a retention period and test a restore.", conf,
                ["backup", "restore", "recover"])
        if c.attrs.get("encrypted") is False:
            add("storage-unencrypted", c, "Security", "high", f"{c.name} is not encrypted at rest.",
                "Unencrypted storage breaks most compliance baselines.", "Enable encryption with KMS.", "stated",
                ["encrypt"])
        if c.attrs.get("public") is True:
            add("db-public", c, "Security", "high", f"{c.name} is publicly accessible.",
                "A public database is exposed to the internet.", "Put it in private subnets and allow only the app tier.",
                "stated", ["public", "internet", "private"])

    # R3/R4: S3
    for c in d.of_type("s3"):
        if c.attrs.get("public") is True:
            add("s3-public", c, "Security", "high", f"{c.name} is public.",
                "Public buckets are a leading cause of data leaks.",
                "Block public access and serve content through CloudFront with origin access control.", "stated",
                ["public", "block", "leak"])
        if c.attrs.get("encrypted") is False:
            add("storage-unencrypted", c, "Security", "high", f"{c.name} is not encrypted.",
                "Unencrypted storage breaks most compliance baselines.", "Enable default encryption.", "stated",
                ["encrypt"])

    for c in d.of_type("dynamodb"):
        if c.attrs.get("pitr") is not True:
            conf = "stated" if c.attrs.get("pitr") is False else "assumed"
            add("dynamodb-no-pitr", c, "Reliability", "medium" if conf == "stated" else "low",
                f"{c.name} has no point-in-time recovery." if conf == "stated"
                else f"It is not clear {c.name} has point-in-time recovery.",
                "A bad write or delete cannot be rolled back.", "Enable point-in-time recovery.", conf,
                ["point-in-time", "point in time", "recovery", "backup", "pitr"])
        if c.attrs.get("encrypted") is False:
            add("storage-unencrypted", c, "Security", "high", f"{c.name} is not encrypted.",
                "Unencrypted storage breaks most compliance baselines.", "Enable encryption.", "stated", ["encrypt"])

    # R5: API without auth
    for c in d.of_type("apigw"):
        if c.attrs.get("auth") is not True:
            conf = "stated" if c.attrs.get("auth") is False else "assumed"
            add("api-no-auth", c, "Security", "high" if conf == "stated" else "low",
                f"{c.name} has no authentication." if conf == "stated"
                else f"It is not clear how {c.name} authenticates callers.",
                "An open API can be called and abused by anyone.",
                "Add Cognito, a JWT authorizer or IAM auth, plus throttling.", conf,
                ["authenticat", "authoriz", "auth", "open api", "anyone"])

    # R6: internet-facing ALB without WAF anywhere
    has_waf = bool(d.of_type("waf")) or any(c.attrs.get("waf") is True for c in d.of_type("cdn", "alb"))
    for c in d.of_type("alb"):
        if c.attrs.get("internet_facing") is not False and not has_waf:
            add("no-waf", c, "Security", "low", f"{c.name} is internet-facing with no web application firewall.",
                "Common attacks like injection and bot floods reach the application directly.",
                "Attach AWS WAF to the load balancer or CloudFront.", "assumed", ["waf", "firewall"])

    # R7: queues
    for c in d.of_type("sqs"):
        if c.attrs.get("dlq") is not True and outbound.get(c.id):
            conf = "stated" if c.attrs.get("dlq") is False else "assumed"
            add("queue-no-dlq", c, "Reliability", "medium" if conf == "stated" else "low",
                f"{c.name} has no dead-letter queue." if conf == "stated"
                else f"It is not clear {c.name} has a dead-letter queue.",
                "A poison message is retried forever and blocks or silently loses work.",
                "Add a dead-letter queue with a redrive policy and an alarm.", conf,
                ["dead letter", "dead-letter", "dlq", "poison"])

    # R8: single instance
    for c in d.of_type("ec2"):
        count = c.attrs.get("count")
        if (count is None or count < 2) and c.attrs.get("autoscaling") is not True:
            conf = "stated" if count is not None else "assumed"
            add("single-instance", c, "Reliability", "medium" if conf == "stated" else "low",
                f"{c.name} is a single instance with no auto scaling." if conf == "stated"
                else f"It is not clear how many {c.name} instances there are or whether they auto scale.",
                "One instance is a single point of failure and cannot absorb spikes.",
                "Run at least two instances across zones in an Auto Scaling group.", conf,
                ["single instance", "single point", "auto scaling", "autoscaling", "two instances", "one instance"])

    # R14: lambda behind async sources without DLQ
    for c in d.of_type("lambda"):
        async_in = [x for x in inbound.get(c.id, []) if comps[x.src].type in ("sns", "eventbridge")]
        if async_in and c.attrs.get("dlq") is not True:
            add("lambda-async-no-dlq", c, "Reliability", "medium",
                f"{c.name} is invoked asynchronously with no failure destination.",
                "Failed async invocations are dropped after retries.",
                "Configure an on-failure destination or dead-letter queue.", "assumed",
                ["dead letter", "dead-letter", "failure destination", "dlq", "dropped"])

    # R16: database reachable straight from the edge
    for c in d.of_type("rds", "aurora", "dynamodb", "cache"):
        for x in inbound.get(c.id, []):
            if comps[x.src].type in ("users", "cdn", "alb", "apigw"):
                add("db-from-edge", c, "Security", "high" if comps[x.src].type == "users" else "medium",
                    f"{names[x.src]} connects directly to {c.name}.",
                    "Data stores should sit behind an application tier, not face the edge.",
                    "Put a compute tier between the edge and the data store.", "stated",
                    ["directly", "straight", "exposed", "behind"])

    # R9: long synchronous chain
    memo: dict[str, int] = {}

    def depth(cid: str, seen: frozenset) -> int:
        if cid in seen:
            return 0
        best = 0
        for x in outbound.get(cid, []):
            if x.kind == "sync":
                best = max(best, 1 + depth(x.dst, seen | {cid}))
        return best

    longest = max((depth(cid, frozenset()) for cid in comps), default=0)
    if longest >= 5:
        add("deep-sync-chain", None, "Performance Efficiency", "low",
            f"A request passes through {longest} synchronous hops.",
            "Every hop adds latency and a way to fail, and the slowest one sets the pace.",
            "Cut the chain with a queue or event for anything that does not need an immediate answer.", "stated",
            ["hops", "chain", "synchronous", "latency"])

    # R10: monitoring
    if len(comps) >= 3 and not d.of_type("monitoring"):
        add("no-monitoring", None, "Operational Excellence", "low", "The design has no monitoring or alarms.",
            "You will learn about failures from customers.", "Add CloudWatch metrics, logs, dashboards and alarms.",
            "assumed", ["monitor", "alarm", "cloudwatch", "observab"])

    # R12: NAT with S3/DynamoDB
    if d.of_type("nat") and d.of_type("s3", "dynamodb"):
        add("nat-for-aws-traffic", d.of_type("nat")[0], "Cost Optimization", "low",
            "A NAT gateway is paying data-processing fees for S3 or DynamoDB traffic.",
            "NAT charges per GB, and S3 and DynamoDB can be reached privately for free.",
            "Use gateway VPC endpoints for S3 and DynamoDB.", "assumed", ["nat", "endpoint"])

    # R13: cache
    for c in d.of_type("cache"):
        n = c.attrs.get("nodes")
        if (n is None or n < 2) and c.attrs.get("multi_az") is not True:
            conf = "stated" if n is not None else "assumed"
            add("cache-single-node", c, "Reliability", "low",
                f"{c.name} is a single node." if conf == "stated" else f"It is not clear {c.name} has replicas.",
                "A single cache node loses all entries on failure and hits the database with the full load.",
                "Add a replica in another zone.", conf, ["single node", "replica", "failover"])

    # R17: read-heavy traffic straight to a database, no cache
    rps = d.traffic.get("avg_rps") or 0
    if rps >= 300 and d.of_type("rds", "aurora", "dynamodb") and not d.of_type("cache"):
        db = d.of_type("rds", "aurora", "dynamodb")[0]
        add("no-cache", db, "Performance Efficiency", "low",
            f"At about {int(rps)} requests per second there is no cache in front of {db.name}.",
            "Repeated reads hit the database and drive up cost and latency.",
            "Add ElastiCache or DynamoDB Accelerator for hot reads.", "assumed", ["cache", "caching"])

    out.sort(key=lambda f: (SEVERITY_ORDER[f.severity], 0 if f.confidence == "stated" else 1, f.id))
    return out
