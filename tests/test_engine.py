import json
import urllib.request

import pytest

from architect.costs import estimate
from architect.diagram import render_mermaid, render_svg
from architect.doc import to_markdown
from architect.model import Design, coerce, parse_details, resolve_type
from architect.rules import analyze
from architect.session import Session


def store():
    d = Design()
    d.add_component("cloudfront", "CDN")
    d.add_component("load balancer", "Load balancer")
    d.add_component("ec2", "Web servers", "count=2")
    d.add_component("postgres", "Orders database", "multi_az=false, backups=false")
    d.add_component("bucket", "Images", "public=true")
    d.connect("CDN", "Load balancer")
    d.connect("Load balancer", "Web servers")
    d.connect("Web servers", "Orders database")
    d.connect("Web servers", "Images")
    d.set_traffic(200)
    return d


def rules(d):
    return {f.rule for f in analyze(d)}


# --- model -----------------------------------------------------------------------------------------
def test_aliases_and_coercion():
    assert resolve_type("Postgres") == "rds" and resolve_type("load balancer") == "alb"
    assert resolve_type("redis") == "cache" and resolve_type("spaceship") is None
    assert coerce("false") is False and coerce("3") == 3 and coerce("1.5") == 1.5 and coerce("t3.large") == "t3.large"
    assert parse_details("multi_az=false, instance_type=t3.large; count=2") == \
        {"multi_az": False, "instance_type": "t3.large", "count": 2}


def test_unknown_type_and_unknown_property_are_reported_not_invented():
    d = Design()
    with pytest.raises(ValueError, match="Unsupported component type"):
        d.add_component("spaceship", "X")
    out = d.add_component("rds", "DB", "turbo=true, multi_az=true")
    assert out["ignored_unknown_properties"] == ["turbo"]
    assert d.find("DB").attrs["multi_az"] is True


def test_voice_style_lookup_is_forgiving_but_not_ambiguous():
    d = store()
    assert d.find("orders db").name == "Orders database"  # a spoken fragment finds the full name
    assert d.find("web servers").id == "web-servers"
    assert d.find("images").type == "s3"
    d.add_component("rds", "Reporting database")
    with pytest.raises(ValueError, match="several components"):
        d.find("database")
    with pytest.raises(ValueError, match="No component matches"):
        d.find("kafka")


def test_connect_dedupes_and_remove_cleans_edges():
    d = store()
    n = len(d.connections)
    d.connect("CDN", "Load balancer", "async")
    assert len(d.connections) == n and d.connections[0].kind == "async"
    d.remove_component("Images")
    assert all("images" not in (c.src, c.dst) for c in d.connections)
    with pytest.raises(ValueError):
        d.connect("CDN", "CDN")


# --- rules -----------------------------------------------------------------------------------------
def test_seeded_flaws_are_found():
    r = rules(store())
    assert {"db-single-az", "db-no-backups", "s3-public"} <= r


def test_stated_vs_assumed_and_severity():
    d = Design()
    d.add_component("rds", "DB")
    f = {x.rule: x for x in analyze(d)}
    assert f["db-single-az"].confidence == "assumed" and f["db-single-az"].severity == "medium"
    d.set_property("DB", "multi_az", "false")
    assert {x.rule: x for x in analyze(d)}["db-single-az"].confidence == "stated"
    assert {x.rule: x for x in analyze(d)}["db-single-az"].severity == "high"


def test_good_design_has_no_high_findings():
    d = Design()
    d.add_component("cdn", "CDN", "waf=true")
    d.add_component("alb", "ALB")
    d.add_component("ecs", "Service", "tasks=3, autoscaling=true")
    d.add_component("aurora", "DB", "instances=2, backups=true, encrypted=true")
    d.add_component("monitoring", "CloudWatch")
    for a, b in (("CDN", "ALB"), ("ALB", "Service"), ("Service", "DB")):
        d.connect(a, b)
    assert [f for f in analyze(d) if f.severity == "high"] == []


def test_edge_to_database_and_async_lambda_and_dlq_rules():
    d = Design()
    d.add_component("users", "Users")
    d.add_component("rds", "DB", "multi_az=true, backups=true")
    d.connect("Users", "DB")
    d.add_component("sns", "Topic")
    d.add_component("lambda", "Handler")
    d.connect("Topic", "Handler", "async")
    d.add_component("sqs", "Jobs", "dlq=false")
    d.add_component("lambda", "Worker")
    d.connect("Jobs", "Worker", "async")
    assert {"db-from-edge", "lambda-async-no-dlq", "queue-no-dlq"} <= rules(d)


def test_deep_sync_chain_and_no_cache_at_scale():
    d = Design()
    prev = None
    for i in range(7):
        d.add_component("lambda", f"Svc {i}")
        if prev:
            d.connect(prev, f"Svc {i}")
        prev = f"Svc {i}"
    d.add_component("rds", "DB", "multi_az=true, backups=true")
    d.connect("Svc 6", "DB")
    d.set_traffic(500)
    assert {"deep-sync-chain", "no-cache"} <= rules(d)


# --- cost ------------------------------------------------------------------------------------------
def test_cost_is_positive_labelled_and_states_assumptions():
    c = estimate(Design())
    assert c["monthly_total_usd"] == 0 and "traffic not stated" in c["assumptions"][0]
    c = estimate(store())
    assert c["monthly_total_usd"] > 100 and "not fetched live" in c["price_basis"]
    assert c["breakdown"][0]["monthly_usd"] >= c["breakdown"][-1]["monthly_usd"]


def test_multi_az_doubles_the_database_instance_cost():
    a, b = Design(), Design()
    a.add_component("rds", "DB", "multi_az=false, storage_gb=0")
    b.add_component("rds", "DB", "multi_az=true, storage_gb=0")
    assert estimate(b)["monthly_total_usd"] == pytest.approx(2 * estimate(a)["monthly_total_usd"], rel=0.01)


def test_unpriced_instance_type_is_not_silently_priced():
    d = Design()
    d.add_component("ec2", "Big", "instance_type=x99.mega")
    row = estimate(d)["breakdown"][0]
    assert row["monthly_usd"] == 0 and "not priced" in row["note"]


# --- diagram, doc, live ----------------------------------------------------------------------------
def test_diagram_shows_components_edges_and_risk_badges():
    d = store()
    svg = render_svg(d, analyze(d))
    assert svg.startswith("<svg") and "Orders database" in svg and "marker-end" in svg
    assert "#ef4444" in svg  # a high-severity badge colour is present
    assert "Start talking" in render_svg(Design())
    assert "flowchart LR" in render_mermaid(d)


def test_document_contains_design_risks_and_cost():
    md = to_markdown(store())
    for needle in ("```mermaid", "Orders database", "[HIGH]", "per month", "not fetched live"):
        assert needle in md


def test_live_view_serves_state_and_svg():
    s = Session(port=0)  # 0 = any free port
    s.live.port = 0
    url = s.live.start()
    port = s.live._server.server_address[1]
    s.design.add_component("rds", "DB", "multi_az=false")
    st = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/state.json", timeout=5).read())
    assert st["components"] == 1 and st["findings"][0]["rule"] == "db-single-az" and st["version"] == 1
    assert b"<svg" in urllib.request.urlopen(f"http://127.0.0.1:{port}/design.svg", timeout=5).read()
    assert b"Voice Architect" in urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read()
    s.live.stop()
    assert url.startswith("http://127.0.0.1")
