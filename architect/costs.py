"""Rough monthly cost estimate (us-east-1, on-demand list prices, USD).

HONESTY NOTE: the prices below are typed in from public AWS price pages as I know them and are approximate.
They were NOT fetched from the AWS Price List API. Treat the total as a planning number (about +-25%) and
confirm in the AWS Pricing Calculator before committing. PRICE_BASIS is shown to the engineer with every answer.
"""
from __future__ import annotations

from .model import TYPES, Design

PRICE_BASIS = ("approximate us-east-1 on-demand list prices typed in from public AWS price pages, "
               "not fetched live; expect about 25 percent either way; excludes tax, support, free tier and "
               "most data transfer")
HOURS = 730
SECONDS_MONTH = 30 * 24 * 3600

EC2_HOURLY = {"t3.micro": 0.0104, "t3.small": 0.0208, "t3.medium": 0.0416, "t3.large": 0.0832,
              "m5.large": 0.096, "m5.xlarge": 0.192, "c5.large": 0.085, "c5.xlarge": 0.17, "r5.large": 0.126}
RDS_HOURLY = {"db.t3.micro": 0.017, "db.t3.small": 0.034, "db.t3.medium": 0.068, "db.t3.large": 0.136,
              "db.m5.large": 0.171, "db.m5.xlarge": 0.342, "db.r5.large": 0.24, "db.r5.xlarge": 0.48}
CACHE_HOURLY = {"cache.t3.micro": 0.017, "cache.t3.small": 0.034, "cache.t3.medium": 0.068, "cache.m5.large": 0.156}


def _n(v, default):
    return default if v is None else v


def estimate(d: Design) -> dict:
    rps = d.traffic.get("avg_rps")
    assumptions = []
    if rps is None:
        rps = 10.0
        assumptions.append("traffic not stated, assumed 10 requests per second on average")
    gb = d.traffic.get("data_gb_month")
    if gb is None:
        gb = 100.0
        assumptions.append("data out not stated, assumed 100 GB a month")
    mau = d.traffic.get("monthly_active_users")
    reqs = rps * SECONDS_MONTH
    rows, notes = [], []

    def row(c, monthly, note=""):
        rows.append({"component": c.name, "type": TYPES[c.type][0], "monthly_usd": round(monthly, 2), "note": note})

    for c in d.components.values():
        t, a = c.type, c.attrs
        if t == "users":
            continue
        if t == "cdn":
            row(c, gb * 0.085 + reqs / 1e6 * 1.00, f"{gb:.0f} GB out at $0.085/GB plus HTTPS requests at $1/M")
        elif t == "waf":
            row(c, 5 + 3 * 1 + reqs / 1e6 * 0.60, "1 web ACL, 3 rules, requests")
        elif t == "apigw":
            price = 1.00 if str(a.get("api_kind")).lower().startswith("http") else 3.50
            row(c, reqs / 1e6 * price, f"{reqs/1e6:.0f}M requests at ${price}/M ({a.get('api_kind')} API)")
        elif t == "alb":
            lcu = max(1.0, rps / 25)
            row(c, 0.0225 * HOURS + lcu * 0.008 * HOURS, f"base plus about {lcu:.1f} capacity units")
        elif t == "ec2":
            it = str(a.get("instance_type"))
            price = EC2_HOURLY.get(it)
            n = _n(a.get("count"), 1)
            if price is None:
                row(c, 0, f"instance type {it} not in my price table, not priced")
            else:
                row(c, price * HOURS * n, f"{n} x {it}")
                if a.get("count") is None:
                    assumptions.append(f"{c.name}: instance count not stated, assumed 1")
        elif t == "ecs":
            n = _n(a.get("tasks"), 2)
            per_hr = float(a["vcpu"]) * 0.04048 + float(a["memory_gb"]) * 0.004445
            row(c, per_hr * HOURS * n, f"{n} tasks x {a['vcpu']} vCPU, {a['memory_gb']} GB")
            if a.get("tasks") is None:
                assumptions.append(f"{c.name}: task count not stated, assumed 2")
        elif t == "lambda":
            gbs = reqs * (a["avg_ms"] / 1000) * (a["memory_mb"] / 1024)
            row(c, reqs / 1e6 * 0.20 + gbs * 0.0000166667, f"{reqs/1e6:.0f}M invocations, {a['avg_ms']} ms, {a['memory_mb']} MB")
        elif t == "s3":
            row(c, a["size_gb"] * 0.023, f"{a['size_gb']} GB stored")
        elif t == "dynamodb":
            writes, reads = reqs * 0.2, reqs * 0.8
            row(c, writes / 1e6 * 0.625 + reads / 1e6 * 0.125 + max(0, a["size_gb"] - 25) * 0.25,
                "on-demand, assumed 80% reads and 20% writes")
        elif t == "rds":
            price = RDS_HOURLY.get(str(a.get("instance_class")))
            mult = 2 if a.get("multi_az") is True else 1
            if price is None:
                row(c, 0, f"instance class {a.get('instance_class')} not in my price table, not priced")
            else:
                row(c, price * HOURS * mult + a["storage_gb"] * 0.115 * mult,
                    f"{a['instance_class']}{' multi-AZ' if mult == 2 else ''} plus {a['storage_gb']} GB storage")
        elif t == "aurora":
            n = _n(a.get("instances"), 2)
            row(c, 0.29 * HOURS * n + a["storage_gb"] * 0.10, f"{n} x db.r5.large plus {a['storage_gb']} GB")
            if a.get("instances") is None:
                assumptions.append(f"{c.name}: instance count not stated, assumed 2")
        elif t == "cache":
            price = CACHE_HOURLY.get(str(a.get("node_type")))
            n = _n(a.get("nodes"), 1)
            row(c, (price or 0) * HOURS * n, f"{n} x {a.get('node_type')}" + ("" if price else " (not priced)"))
        elif t == "sqs":
            row(c, reqs * 3 / 1e6 * 0.40, "assumes send, receive and delete per message")
        elif t == "sns":
            row(c, reqs / 1e6 * 0.50, "publishes")
        elif t == "eventbridge":
            row(c, reqs / 1e6 * 1.00, "custom events")
        elif t == "cognito":
            billable = max(0, _n(mau, 10000) - 10000)
            row(c, billable * 0.015, "monthly active users beyond the first 10,000")
        elif t == "nat":
            row(c, 0.045 * HOURS + gb * 0.045, f"one gateway plus {gb:.0f} GB processed")
        elif t == "monitoring":
            row(c, 10.0, "flat assumption for logs, metrics and a few alarms")
    total = round(sum(r["monthly_usd"] for r in rows), 2)
    rows.sort(key=lambda r: -r["monthly_usd"])
    return {"monthly_total_usd": total, "breakdown": rows, "assumptions": assumptions, "price_basis": PRICE_BASIS}
