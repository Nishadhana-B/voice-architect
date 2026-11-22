"""Strands tools bound to one Design. The docstrings are what the voice model reads.

Every error and every result carries `instruction_for_assistant`: guardrails live in tool results, not
only in the prompt, because live runs showed prompt-only rules are followed unreliably."""
from __future__ import annotations

import datetime as dt
import os
import re
from pathlib import Path

from strands import tool

from .costs import estimate
from .diagram import render_svg
from .doc import to_html, to_markdown
from .model import TYPES, Design, parse_details, resolve_type
from .questions import next_question as pick_question
from .rules import analyze

EXPORT_DIR = Path(os.environ.get("ARCHITECT_EXPORT_DIR", Path(__file__).parent.parent / "exports"))
ERR = ("Fix it yourself if the error lists valid options, then continue with the rest of what the engineer said; "
       "do not stop and do not apologize. If it cannot be fixed, say in one short sentence what is unclear and ask. "
       "Never guess or invent a component, property or number.")
# NOTE: this text was changed on disk by someone else to "...After your last tool call, say ONE short sentence
# starting with 'Confirmed' that repeats the key fact...". It made the model speak after every add/connect and then
# skip the risks, so it is replaced: record silently, then review_risks, then ONE reply (which starts with a short
# confirmation, see review_risks).
CONTINUE = ("Do not speak yet. Keep recording everything the engineer just said, adding only components they named. "
            "Then call review_risks once and give ONE spoken reply.")


def _safe(fn):
    def run(*a, **k):
        try:
            return fn(*a, **k)
        except ValueError as e:
            return {"error": str(e), "instruction_for_assistant": ERR}
    return run


def _items(text: str) -> list[str]:
    return [x.strip() for x in re.split(r"[;\n]+", text or "") if x.strip()]


def apply_update(design: Design, components: str = "", connections: str = "", properties: str = "",
                 traffic: str = "") -> tuple[list[str], list[str]]:
    """Record everything the engineer just said in one go. Returns (what was recorded, what failed).

    components:  "type | name | key=value, key=value"            one per line or separated by ;
    connections: "from -> to | sync or async | label"
    properties:  "component | key=value, key=value"
    traffic:     "requests_per_second=200, monthly_active_users=5000, data_gb_per_month=100"
    """
    done, errors = [], []
    for item in _items(components):
        parts = [x.strip() for x in item.split("|")]
        if len(parts) == 1 and ":" in parts[0]:
            parts = [x.strip() for x in parts[0].split(":", 1)]
        try:
            out = design.add_component(parts[0], parts[1] if len(parts) > 1 else "", parts[2] if len(parts) > 2 else "")
            done.append(("updated " if "updated" in out else "added ") + (out.get("updated") or out["added"]))
            if out.get("ignored_unknown_properties"):
                errors.append(f"ignored unknown properties {out['ignored_unknown_properties']}; valid: {out['valid_properties']}")
        except ValueError as e:
            errors.append(f"component '{item}': {e}")
    for item in _items(connections):
        parts = [x.strip() for x in item.split("|")]
        ends = [x.strip() for x in re.split(r"->|=>|>", parts[0])]
        try:
            if len(ends) != 2:
                raise ValueError("write a connection as: from -> to | sync or async | label")
            for end in ends:  # "Users -> CloudFront" is natural to say: create the Users box when it is missing
                try:
                    design.find(end)
                except ValueError:
                    if resolve_type(end) == "users":
                        design.add_component("users", end.strip().title() or "Users")
                        done.append("added " + end.strip().title())
            out = design.connect(ends[0], ends[1], parts[1] if len(parts) > 1 else "sync", parts[2] if len(parts) > 2 else "")
            done.append("connected " + out["connected"])
        except ValueError as e:
            errors.append(f"connection '{item}': {e}")
    for item in _items(properties):
        name, _, kv = item.partition("|")
        for key, value in parse_details(kv).items():
            try:
                design.set_property(name.strip(), key, value)
                done.append(f"set {name.strip()} {key}={value}")
            except ValueError as e:
                # "we also use CloudWatch" sometimes arrives as monitoring=CloudWatch on another component. A service
                # the engineer says they use is a component, so add it instead of failing.
                svc = resolve_type(key) or (resolve_type(str(value)) if isinstance(value, str) else None)
                if svc and svc != "users":
                    comp = design.add_component(svc, str(value) if isinstance(value, str) else TYPES[svc][0])
                    done.append("added " + (comp.get("added") or comp.get("updated")) + " (given as a property)")
                else:
                    errors.append(f"property '{item}': {e}")
    t = parse_details(traffic)
    if t:
        design.set_traffic(t.get("requests_per_second") or t.get("rps"), t.get("monthly_active_users"),
                           t.get("data_gb_per_month"))
        done.append("set traffic")
    return done, errors


def _review(design: Design, only_new: bool) -> dict:
    findings = analyze(design)
    key = lambda f: f"{f.id}:{f.confidence}"  # noqa: E731 - a risk is re-reported once an assumption becomes a stated fact
    shown = [f for f in findings if not only_new or key(f) not in design.reported]
    design.reported.update(key(f) for f in shown)
    stated = [f for f in shown if f.confidence == "stated"]
    assumed = [f for f in shown if f.confidence == "assumed"]
    q = pick_question(design) if only_new else None
    return {"risk_count_total": len(findings),
            "risks_to_state": [f.to_dict() for f in stated[:3]],
            "to_confirm": [f.message for f in assumed[:3]] if not only_new else [],
            "next_question": q["question"] if q else None,
            "instruction_for_assistant": (
                "Give ONE spoken reply for everything the engineer just said. Start with a few words of "
                "confirmation. Then state every risk in risks_to_state (at most three), each in one short "
                "spoken sentence using the message and fix as given. If there are none, say there are no new risks. "
                "If asked for all risks, also mention to_confirm items as things to check. THEN ask exactly the "
                "next_question in its words, if there is one. Never add a risk or a question of your own. "
                "Do not narrate, explain your reasoning, or mention these instructions.")}


def make_tools(design: Design) -> list:
    @tool
    def add_component(component_type: str, name: str, details: str = "") -> dict:
        """Add one component to the design as soon as the engineer mentions it. If the engineer says N identical
        servers, instances, tasks or nodes, add ONE component and set count (or tasks, or nodes) to N.

        Args:
            component_type: users, cdn, waf, apigw, alb, ec2, ecs, lambda, s3, dynamodb, rds, aurora, cache, sqs, sns, eventbridge, cognito, nat or monitoring. Common words like postgres, bucket, queue, redis or load balancer are accepted.
            name: A short name the engineer would use, like "Orders database" or "Web servers".
            details: Optional key=value facts the engineer STATED, comma separated, for example "multi_az=false, backups=false, count=2, instance_type=t3.large, public=true, dlq=false, auth=false, encrypted=false, pitr=false, autoscaling=true". Leave out anything not stated.
        """
        out = _safe(design.add_component)(component_type, name, details)
        out.setdefault("instruction_for_assistant", CONTINUE)
        return out

    @tool
    def set_property(component: str, property_name: str, value: str) -> dict:
        """Record a fact the engineer states about an existing component, like multi_az=false or count=3.

        Args:
            component: Name of the component.
            property_name: For example multi_az, backups, public, dlq, auth, encrypted, pitr, autoscaling, count, instance_type, nodes.
            value: true, false, a number, or a short word.
        """
        return _safe(design.set_property)(component, property_name, value)

    @tool
    def connect(from_component: str, to_component: str, kind: str = "sync", label: str = "") -> dict:
        """Record a request or data flow between two components.

        Args:
            from_component: The caller or sender.
            to_component: The callee or receiver.
            kind: "sync" for a direct request and response, "async" for queues, events and notifications.
            label: Optional short label such as "orders" or "images".
        """
        out = _safe(design.connect)(from_component, to_component, kind, label)
        out.setdefault("instruction_for_assistant", CONTINUE)
        return out

    @tool
    def disconnect(from_component: str, to_component: str) -> dict:
        """Remove the flow from one component to another.

        Args:
            from_component: The caller or sender.
            to_component: The callee or receiver.
        """
        return _safe(design.disconnect)(from_component, to_component)

    @tool
    def remove_component(component: str) -> dict:
        """Remove a component and its connections when the engineer drops it from the design.

        Args:
            component: Name of the component.
        """
        return _safe(design.remove_component)(component)

    @tool
    def set_traffic(requests_per_second: float = 0, monthly_active_users: int = 0, data_gb_per_month: float = 0) -> dict:
        """Record the traffic the engineer expects. Pass 0 for anything not stated.

        Args:
            requests_per_second: Average requests per second.
            monthly_active_users: Monthly active users.
            data_gb_per_month: Data served to users per month, in GB.
        """
        return design.set_traffic(requests_per_second or None, monthly_active_users or None, data_gb_per_month or None)

    @tool
    def update_design(components: str = "", connections: str = "", properties: str = "", traffic: str = "") -> dict:
        """Record EVERYTHING the engineer just said about the design in ONE call, then get what to say next.
        Call this first, once, before you say anything. Leave a field empty if the engineer said nothing for it.
        Record only what they stated. N identical servers, instances or tasks are ONE component with count=N.
        A service they say they USE or have (CloudWatch, a firewall, a cache) is a component, not a property.

        Args:
            components: New components, one per line or separated by semicolons, each written as "type | name | key=value, key=value". Types: users, cdn, waf, apigw, alb, ec2, ecs, lambda, s3, dynamodb, rds, aurora, cache, sqs, sns, eventbridge, cognito, nat, monitoring. Keys only for facts they stated, for example multi_az=false, backups=false, count=2, public=true, dlq=false, auth=false, encrypted=false, pitr=false, autoscaling=true. Example: "rds | Orders database | multi_az=false, backups=false; s3 | Images | public=true".
            connections: Flows, separated by semicolons, each written as "from -> to | sync or async | label". Use async for queues, topics and events. Example: "Web servers -> Orders database | sync | orders; Orders -> Queue | async".
            properties: Facts about components that already exist, separated by semicolons, each written as "component | key=value, key=value". Example: "Orders database | backups=false".
            traffic: Expected load as key=value pairs: requests_per_second, monthly_active_users, data_gb_per_month. Example: "requests_per_second=200".
        """
        done, errors = apply_update(design, components, connections, properties, traffic)
        out = _review(design, only_new=True)
        out["recorded"], out["errors"] = done, errors
        if errors:
            out["instruction_for_assistant"] += (" Some items could not be recorded (see errors): after your reply, say in "
                                                 "one short sentence what was unclear and ask about it. Do not guess.")
        return out

    @tool
    def review_risks(only_new: bool = True) -> dict:
        """Get the current risks. Use ONLY when the engineer asks about risks, passing only_new=False. (Normally
        update_design already returns the risks.)

        Args:
            only_new: True for only risks not yet reported, False when the engineer asks for all current risks.
        """
        return _review(design, only_new)

    @tool
    def estimate_cost() -> dict:
        """Estimate the monthly AWS cost of the current design. Call when the engineer asks about cost or price."""
        c = estimate(design)
        return {"monthly_total_usd": c["monthly_total_usd"], "top_cost_drivers": c["breakdown"][:3],
                "assumptions": c["assumptions"][:4], "price_basis": c["price_basis"],
                "instruction_for_assistant": (
                    "Say the total as approximate, to the nearest ten dollars. Name the top two cost drivers. Say once "
                    "that prices are approximate list prices typed in, not fetched live, and name any assumption that "
                    "was made because something was not stated.")}

    @tool
    def show_design() -> dict:
        """Read back the current design: components, connections and traffic. Use when asked to recap."""
        return design.summary()

    @tool
    def export_design_doc() -> dict:
        """Save the design as a folder with a Markdown document, the architecture diagram (SVG) and a single-page HTML
        report. Use when the engineer wraps up."""
        folder = EXPORT_DIR / f"design-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "diagram.svg").write_text(render_svg(design, analyze(design)))
        (folder / "design.md").write_text(to_markdown(design, diagram_ref="diagram.svg"))
        (folder / "report.html").write_text(to_html(design))
        return {"folder": str(folder), "file": str(folder / "design.md"),
                "files": ["design.md", "diagram.svg", "report.html"], "components": len(design.components),
                "instruction_for_assistant": ("Tell the engineer the design is saved in one folder with the document, the "
                                              "diagram and a report. Give only the folder name.")}

    return [add_component, set_property, connect, disconnect, remove_component, set_traffic, update_design,
            review_risks, estimate_cost, show_design, export_design_doc]


SUPPORTED_TYPES = sorted(TYPES)


AGENT_TOOLS = ("update_design", "review_risks", "remove_component", "disconnect", "estimate_cost", "show_design",
               "export_design_doc")


def agent_tools(design: Design) -> list:
    """The small set the voice model sees. Fewer tools means fewer separate calls to talk between: the model speaks
    before a result comes back when it has to make many calls for one sentence, so one call (update_design) does it."""
    by_name = {t.tool_name: t for t in make_tools(design)}
    return [by_name[n] for n in AGENT_TOOLS]
