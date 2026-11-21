"""The architecture being designed: components, connections and traffic assumptions.

Attributes use None for "not stated yet". Rules treat None as an open question, False as a stated problem.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# type -> (display name, category, default attributes)
TYPES: dict[str, tuple[str, str, dict]] = {
    "users": ("Users", "edge", {}),
    "cdn": ("CloudFront", "edge", {"waf": None}),
    "waf": ("AWS WAF", "security", {}),
    "apigw": ("API Gateway", "edge", {"auth": None, "api_kind": "rest"}),
    "alb": ("Load Balancer", "network", {"internet_facing": True, "waf": None}),
    "ec2": ("EC2", "compute", {"instance_type": "t3.medium", "count": None, "autoscaling": None}),
    "ecs": ("ECS Fargate", "compute", {"vcpu": 0.5, "memory_gb": 1.0, "tasks": None, "autoscaling": None}),
    "lambda": ("Lambda", "compute", {"memory_mb": 512, "avg_ms": 200, "dlq": None}),
    "s3": ("S3", "storage", {"public": None, "encrypted": None, "size_gb": 100}),
    "dynamodb": ("DynamoDB", "database", {"pitr": None, "encrypted": None, "size_gb": 10}),
    "rds": ("RDS", "database", {"instance_class": "db.t3.medium", "multi_az": None, "backups": None,
                                "encrypted": None, "public": None, "storage_gb": 100}),
    "aurora": ("Aurora", "database", {"instances": None, "backups": None, "encrypted": None, "storage_gb": 100}),
    "cache": ("ElastiCache", "database", {"node_type": "cache.t3.medium", "nodes": None, "multi_az": None}),
    "sqs": ("SQS", "integration", {"dlq": None}),
    "sns": ("SNS", "integration", {}),
    "eventbridge": ("EventBridge", "integration", {}),
    "cognito": ("Cognito", "security", {}),
    "nat": ("NAT Gateway", "network", {}),
    "monitoring": ("CloudWatch", "operations", {}),
}

ALIASES = {
    "cloudfront": "cdn", "cdn": "cdn", "content delivery network": "cdn",
    "api gateway": "apigw", "apigateway": "apigw", "api-gateway": "apigw", "gateway": "apigw",
    "load balancer": "alb", "application load balancer": "alb", "elb": "alb", "loadbalancer": "alb",
    "ec2 instance": "ec2", "server": "ec2", "virtual machine": "ec2", "vm": "ec2", "instance": "ec2",
    "fargate": "ecs", "container": "ecs", "containers": "ecs", "eks": "ecs",
    "lambda function": "lambda", "function": "lambda", "serverless function": "lambda",
    "bucket": "s3", "s3 bucket": "s3", "object storage": "s3",
    "dynamo": "dynamodb", "dynamo db": "dynamodb", "nosql": "dynamodb",
    "postgres": "rds", "postgresql": "rds", "mysql": "rds", "database": "rds", "sql database": "rds",
    "relational database": "rds",
    "redis": "cache", "elasticache": "cache", "memcached": "cache", "valkey": "cache",
    "queue": "sqs", "message queue": "sqs",
    "topic": "sns", "event bus": "eventbridge", "events": "eventbridge",
    "firewall": "waf", "web application firewall": "waf",
    "auth": "cognito", "user pool": "cognito", "nat gateway": "nat",
    "cloudwatch": "monitoring", "logging": "monitoring", "observability": "monitoring",
    "client": "users", "clients": "users", "customers": "users", "browser": "users", "mobile app": "users",
}


_STOP = {"the", "a", "an", "our", "my", "this", "that"}
_EXPAND = {"db": "database", "dbs": "databases", "lb": "load", "gw": "gateway"}


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [_EXPAND.get(w, w) for w in words if w not in _STOP]


# Names the model (or a person) may use for a property, mapped to the real one, per component type.
PROP_ALIASES = {
    "aurora": {"nodes": "instances", "count": "instances", "replicas": "instances", "instance_count": "instances",
               "backup": "backups", "automated_backups": "backups", "encryption": "encrypted"},
    "ecs": {"count": "tasks", "instances": "tasks", "replicas": "tasks", "task_count": "tasks", "auto_scaling": "autoscaling"},
    "ec2": {"instances": "count", "servers": "count", "instance_count": "count", "replicas": "count",
            "auto_scaling": "autoscaling"},
    "cache": {"count": "nodes", "replicas": "nodes", "instances": "nodes", "multiaz": "multi_az"},
    "rds": {"multiaz": "multi_az", "backup": "backups", "automated_backups": "backups", "encryption": "encrypted",
            "publicly_accessible": "public", "public_access": "public"},
    "dynamodb": {"point_in_time_recovery": "pitr", "point_in_time": "pitr", "encryption": "encrypted"},
    "sqs": {"dead_letter_queue": "dlq", "dead_letter": "dlq"},
    "lambda": {"dead_letter_queue": "dlq", "dead_letter": "dlq"},
    "apigw": {"authentication": "auth", "authorizer": "auth"},
    "s3": {"publicly_accessible": "public", "public_access": "public", "encryption": "encrypted"},
    "alb": {"web_application_firewall": "waf", "public": "internet_facing"},
    "cdn": {"web_application_firewall": "waf"},
}


def canon_prop(component_type: str, key: str) -> str:
    k = key.strip().lower().replace("-", "_").replace(" ", "_")
    return PROP_ALIASES.get(component_type, {}).get(k, k)


_COUNT_ATTR = {"ec2": "count", "ecs": "tasks", "cache": "nodes", "aurora": "instances"}


def _numbered_family(name: str) -> str | None:
    """"Web Server 2" -> "web server"; None when the name does not end in a number."""
    n = name.strip()
    return re.sub(r"[\s\-_]*\d+$", "", n).lower() if re.search(r"\d+$", n) else None


_FAMILY = {"rds": "db", "aurora": "db", "dynamodb": "db", "cache": "db", "ec2": "compute", "ecs": "compute", "lambda": "compute"}
_NAME_HINTS = {"aurora": "aurora", "dynamodb": "dynamodb", "dynamo db": "dynamodb", "elasticache": "cache", "redis": "cache",
               "fargate": "ecs", "lambda": "lambda"}


def infer_type(given: str, name: str) -> str:
    """The model sometimes types "Aurora database" as plain rds. If the name clearly names a more specific service of
    the same family (database or compute), use that."""
    low = name.lower()
    for hint, typ in _NAME_HINTS.items():
        if hint in low and typ != given and _FAMILY.get(typ) and _FAMILY.get(typ) == _FAMILY.get(given):
            return typ
    return given


def resolve_type(text: str) -> str | None:
    t = text.strip().lower().replace("_", " ")
    if t in TYPES:
        return t
    return ALIASES.get(t) or ALIASES.get(t.replace(" ", ""))


def coerce(value):
    """'false' -> False, '2' -> 2, '1.5' -> 1.5, anything else stays a string."""
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    v = str(value).strip()
    low = v.lower()
    if low in ("true", "yes", "on", "enabled"):
        return True
    if low in ("false", "no", "off", "disabled", "none configured"):
        return False
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


def parse_details(details: str) -> dict:
    """'multi_az=false, instance_type=t3.large' -> {'multi_az': False, 'instance_type': 't3.large'}"""
    out = {}
    for part in re.split(r"[,;\n]+", details or ""):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip().lower().replace(" ", "_")] = coerce(v)
    return out


@dataclass
class Component:
    id: str
    type: str
    name: str
    attrs: dict = field(default_factory=dict)


@dataclass
class Connection:
    src: str
    dst: str
    kind: str = "sync"  # sync or async
    label: str = ""


class Design:
    def __init__(self):
        self.components: dict[str, Component] = {}
        self.connections: list[Connection] = []
        self.traffic: dict = {"avg_rps": None, "monthly_active_users": None, "data_gb_month": None}
        self.reported: set[str] = set()  # finding ids the agent has already told the engineer about
        self.asked: set[str] = set()     # probing questions already asked
        self.version = 0

    # --- helpers -------------------------------------------------------------------------------
    @staticmethod
    def _slug(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "component"

    def of_type(self, *types: str) -> list[Component]:
        return [c for c in self.components.values() if c.type in types]

    def find(self, ref: str) -> Component:
        key = ref.strip().lower()
        if not key:
            raise ValueError("Name a component.")
        if key in self.components:
            return self.components[key]
        slug = self._slug(ref)
        if slug in self.components:
            return self.components[slug]
        for c in self.components.values():
            if c.name.lower() == key:
                return c
        hits = [c for c in self.components.values() if key in c.name.lower() or key in c.id or c.id in slug]
        if not hits:  # spoken style: "the orders DB" should find "Orders database"
            q = _tokens(ref)
            hits = [c for c in self.components.values()
                    if q and all(any(t.startswith(w) for t in _tokens(c.name)) for w in q)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise ValueError(f"'{ref}' matches several components: {[c.name for c in hits]}. Which one?")
        by_type = resolve_type(ref)
        typed = self.of_type(by_type) if by_type else []
        if len(typed) == 1:
            return typed[0]
        raise ValueError(f"No component matches '{ref}'. Current components: {[c.name for c in self.components.values()]}")

    def _touch(self):
        self.version += 1

    # --- edits ---------------------------------------------------------------------------------
    def add_component(self, component_type: str, name: str, details: str = "") -> dict:
        t = resolve_type(component_type)
        if not t:
            raise ValueError(f"Unsupported component type '{component_type}'. Supported: {sorted(TYPES)}")
        t = infer_type(t, name)
        attr = _COUNT_ATTR.get(t)
        fam = _numbered_family(name) if attr else None
        if fam:  # "Web Server 1" then "Web Server 2" are ONE component with count=2, not two boxes
            for c in self.components.values():
                if c.type == t and (_numbered_family(c.name) or c.name.strip().lower()) == fam:
                    c.attrs[attr] = (c.attrs.get(attr) or 1) + 1
                    c.name = re.sub(r"[\s\-_]*\d+$", "", c.name.strip()) or c.name
                    self._touch()
                    return {"updated": c.name, "type": TYPES[t][0], "id": c.id,
                            "note": f"counted as another identical one, now {c.attrs[attr]}"}
        base = self._slug(name or TYPES[t][0])
        same = self.components.get(base)
        if same is not None and same.type == t:  # the model repeated itself: update, never duplicate
            for k, v in parse_details(details).items():
                k = canon_prop(t, k)
                if k in same.attrs:
                    same.attrs[k] = v
            self._touch()
            return {"updated": same.name, "type": TYPES[t][0], "id": same.id, "note": "already in the design"}
        cid, n = base, 2
        while cid in self.components:
            cid, n = f"{base}-{n}", n + 1
        attrs = dict(TYPES[t][2])
        ignored = []
        for k, v in parse_details(details).items():
            k = canon_prop(t, k)
            if k in attrs:
                attrs[k] = v
            else:
                ignored.append(k)
        comp = Component(cid, t, name.strip() or TYPES[t][0], attrs)
        self.components[cid] = comp
        self._touch()
        out = {"added": comp.name, "type": TYPES[t][0], "id": cid}
        if ignored:
            out["ignored_unknown_properties"] = ignored
            out["valid_properties"] = sorted(TYPES[t][2])
        return out

    def set_property(self, ref: str, key: str, value) -> dict:
        c = self.find(ref)
        k = canon_prop(c.type, key)
        if k not in TYPES[c.type][2]:
            raise ValueError(f"{TYPES[c.type][0]} has no property '{key}'. Valid: {sorted(TYPES[c.type][2])}")
        c.attrs[k] = coerce(value)
        self._touch()
        return {"component": c.name, k: c.attrs[k]}

    def connect(self, src: str, dst: str, kind: str = "sync", label: str = "") -> dict:
        a, b = self.find(src), self.find(dst)
        if a.id == b.id:
            raise ValueError("A component cannot connect to itself.")
        kind = "async" if kind.strip().lower().startswith("a") else "sync"
        for c in self.connections:
            if c.src == a.id and c.dst == b.id:
                c.kind, c.label = kind, label or c.label
                self._touch()
                return {"connected": f"{a.name} -> {b.name}", "kind": kind, "note": "updated existing connection"}
        self.connections.append(Connection(a.id, b.id, kind, label.strip()))
        self._touch()
        return {"connected": f"{a.name} -> {b.name}", "kind": kind}

    def disconnect(self, src: str, dst: str) -> dict:
        a, b = self.find(src), self.find(dst)
        before = len(self.connections)
        self.connections = [c for c in self.connections if not (c.src == a.id and c.dst == b.id)]
        self._touch()
        return {"removed_connections": before - len(self.connections)}

    def remove_component(self, ref: str) -> dict:
        c = self.find(ref)
        del self.components[c.id]
        self.connections = [x for x in self.connections if c.id not in (x.src, x.dst)]
        self._touch()
        return {"removed": c.name}

    def set_traffic(self, avg_rps: float | None = None, monthly_active_users: int | None = None,
                    data_gb_month: float | None = None) -> dict:
        for k, v in (("avg_rps", avg_rps), ("monthly_active_users", monthly_active_users),
                     ("data_gb_month", data_gb_month)):
            if v is not None and float(v) > 0:
                self.traffic[k] = float(v)
        self._touch()
        return dict(self.traffic)

    # --- views ---------------------------------------------------------------------------------
    def summary(self) -> dict:
        names = {c.id: c.name for c in self.components.values()}
        return {
            "components": [{"name": c.name, "type": TYPES[c.type][0],
                            "properties": {k: v for k, v in c.attrs.items() if v is not None}}
                           for c in self.components.values()],
            "connections": [f"{names[x.src]} -> {names[x.dst]} ({x.kind}{', ' + x.label if x.label else ''})"
                            for x in self.connections],
            "traffic": {k: v for k, v in self.traffic.items() if v is not None},
        }
