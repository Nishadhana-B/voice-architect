"""Pick the next probing question deterministically.

Why this exists: when the model had to invent a question itself, it deliberated out loud ("Okay, the user has added
... the instructions say to ask one question ..."). A tool that chooses the question removes the deliberation."""
from __future__ import annotations

from .model import Design
from .rules import analyze

# rule -> question template for facts the engineer has not stated yet
OPEN_QUESTION = {
    "db-single-az": "Is {c} set up across more than one availability zone?",
    "db-no-backups": "Are automated backups turned on for {c}?",
    "api-no-auth": "How are callers of {c} authenticated?",
    "queue-no-dlq": "Does {c} have a dead-letter queue for messages that keep failing?",
    "dynamodb-no-pitr": "Is point-in-time recovery switched on for {c}?",
    "single-instance": "How many {c} instances run, and do they scale automatically?",
    "lambda-async-no-dlq": "Where do failed invocations of {c} go?",
    "cache-single-node": "Does {c} have a replica in another availability zone?",
    "no-waf": "Is a web application firewall in front of {c}?",
    "no-monitoring": "How will you monitor this and get alerted when something breaks?",
}


def next_question(d: Design) -> dict:
    def ask(key: str, text: str, why: str) -> dict | None:
        if key in d.asked:
            return None
        d.asked.add(key)
        return {"question": text, "why": why,
                "instruction_for_assistant": "Ask exactly this question in these words. Do not add your own question, "
                                             "and do not explain why you are asking."}

    if not d.components:
        return ask("purpose", "What is the system for, and who uses it?", "nothing described yet") or _done()
    for f in analyze(d):
        if f.confidence == "assumed" and f.rule in OPEN_QUESTION:
            name = f.components[0] if f.components else "the design"
            q = ask(f"{f.rule}:{name}", OPEN_QUESTION[f.rule].format(c=name), f"open question from rule {f.rule}")
            if q:
                return q
    if d.traffic.get("avg_rps") is None:
        q = ask("traffic", "How many requests per second do you expect at peak?", "no traffic stated")
        if q:
            return q
    if not d.of_type("rds", "aurora", "dynamodb", "s3"):
        q = ask("data", "Where does your data live?", "no data store in the design")
        if q:
            return q
    compute = d.of_type("ec2", "ecs", "lambda")
    if compute:
        q = ask(f"failure:{compute[0].id}", f"What happens to your users if {compute[0].name} fails?", "failure mode")
        if q:
            return q
    if len(compute) >= 2 and not d.of_type("sqs", "sns", "eventbridge"):
        q = ask("async", "Which of that work could happen in the background instead of inside the request?",
                "all synchronous")
        if q:
            return q
    return _done()


def _done() -> dict:
    return {"question": None, "why": "main areas covered",
            "instruction_for_assistant": "Say the main areas are covered and offer a recap or the design document."}
