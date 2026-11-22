from architect import tools as tools_module
from architect.model import Design
from architect.scenarios import SCENARIOS
from architect.scoring import aggregate, score_run
from architect.tools import make_tools


def tool_map(design):
    return {t.tool_name: t for t in make_tools(design)}


def test_errors_carry_an_instruction_instead_of_raising():
    t = tool_map(Design())
    out = t["add_component"]("spaceship", "X")
    assert "error" in out and "Never guess" in out["instruction_for_assistant"] and "do not stop" in out["instruction_for_assistant"]
    out = t["connect"]("A", "B")
    assert "error" in out and "instruction_for_assistant" in out


def test_all_tools_exposed_with_unique_names():
    names = [x.tool_name for x in make_tools(Design())]
    assert len(names) == len(set(names)) == 11
    assert {"add_component", "connect", "review_risks", "estimate_cost", "export_design_doc"} <= set(names)


def test_review_risks_gives_one_instruction_risks_then_a_single_question():
    d = Design()
    t = tool_map(d)
    t["add_component"]("rds", "DB", "multi_az=false, backups=false")
    first = t["review_risks"]()
    assert {f["rule"] for f in first["risks_to_state"]} == {"db-single-az", "db-no-backups"}
    assert first["next_question"] and first["next_question"].endswith("?")        # exactly one question, chosen by code
    ins = first["instruction_for_assistant"]
    assert "ONE spoken reply" in ins and "THEN ask exactly" in ins and "Do not narrate" in ins
    again = t["review_risks"]()
    assert again["risks_to_state"] == []                                         # each risk is reported once
    assert len(t["review_risks"](only_new=False)["risks_to_state"]) == 2          # unless asked for all
    assert t["review_risks"](only_new=False)["next_question"] is None             # explicit "list the risks" adds no question


def test_assumed_risk_is_reported_again_when_it_becomes_a_stated_fact():
    d = Design()
    t = tool_map(d)
    t["add_component"]("rds", "DB")                                               # nothing stated: only open questions
    first = t["review_risks"]()
    assert first["risks_to_state"] == []
    t["set_property"]("DB", "multi_az", "false")                                  # the engineer then states a problem
    second = t["review_risks"]()
    assert [f["rule"] for f in second["risks_to_state"]] == ["db-single-az"]


def test_add_and_connect_say_record_silently_add_only_named_components_then_review_risks():
    t = tool_map(Design())
    out = t["add_component"]("lambda", "A")
    t["add_component"]("sqs", "Q")
    for text in (out["instruction_for_assistant"], t["connect"]("A", "Q")["instruction_for_assistant"]):
        assert "Do not speak yet" in text and "only components they named" in text and "review_risks" in text


def test_common_property_names_are_mapped_instead_of_failing():
    # Found in a live run: the model sent "nodes" for Aurora, got an error, apologised and dropped CloudWatch.
    d = Design()
    t = tool_map(d)
    t["add_component"]("aurora", "DB")
    out = t["set_property"]("DB", "nodes", "2")
    assert "error" not in out and d.find("DB").attrs["instances"] == 2
    t["add_component"]("ecs", "S", "count=3, auto_scaling=true")
    assert d.find("S").attrs["tasks"] == 3 and d.find("S").attrs["autoscaling"] is True
    t["add_component"]("sqs", "Q", "dead_letter_queue=false")
    assert d.find("Q").attrs["dlq"] is False
    bad = t["set_property"]("DB", "turbo", "1")
    assert "error" in bad and "Valid" in bad["error"]


def test_estimate_cost_tool_names_drivers_and_basis():
    d = Design()
    t = tool_map(d)
    t["add_component"]("rds", "DB", "multi_az=true")
    out = t["estimate_cost"]()
    assert out["monthly_total_usd"] > 0 and out["top_cost_drivers"][0]["component"] == "DB"
    assert "not fetched live" in out["price_basis"] and "approximate" in out["instruction_for_assistant"]


def test_export_writes_a_document(tmp_path, monkeypatch):
    monkeypatch.setattr(tools_module, "EXPORT_DIR", tmp_path)
    d = Design()
    t = tool_map(d)
    t["add_component"]("s3", "Images", "public=true")
    out = t["export_design_doc"]()
    text = open(out["file"]).read()
    assert "Images" in text and "[HIGH]" in text


def test_set_traffic_ignores_zero_placeholders():
    d = Design()
    t = tool_map(d)
    t["set_traffic"](requests_per_second=200)
    t["set_traffic"](monthly_active_users=5000)
    assert d.traffic["avg_rps"] == 200 and d.traffic["monthly_active_users"] == 5000


def perfect_store():
    d = Design()
    t = tool_map(d)
    t["add_component"]("cdn", "CDN")
    t["add_component"]("alb", "ALB")
    t["add_component"]("ec2", "Web", "count=2")
    t["add_component"]("rds", "DB", "multi_az=false, backups=false")
    t["add_component"]("s3", "Images", "public=true")
    return d


def test_scoring_perfect_run_passes():
    d = perfect_store()
    spoken = [{"role": "assistant", "text": "The database is in a single availability zone, has no backups, and the "
                                            "bucket is public."}]
    r = score_run(SCENARIOS["store"], d, spoken, [{"tool": "estimate_cost"}, {"tool": "review_risks"}], [2.0, 2.4])
    assert r["pass"] and r["type_recall"] == 1.0 and r["rule_recall"] == 1.0 and r["mention_recall"] == 1.0


def test_scoring_catches_missing_component_unstated_fact_and_silence():
    d = perfect_store()
    d.remove_component("Images")                              # component never captured
    r = score_run(SCENARIOS["store"], d, [], [{"tool": "estimate_cost"}], [])
    assert not r["pass"] and r["missing_types"] == ["s3"] and "s3-public" in r["missed_rules"]
    d2 = perfect_store()
    d2.set_property("DB", "backups", "true")                  # fact stated wrongly / not captured
    r2 = score_run(SCENARIOS["store"], d2, [], [{"tool": "estimate_cost"}], [])
    assert r2["missed_rules"] == ["db-no-backups"]
    r3 = score_run(SCENARIOS["store"], perfect_store(), [{"role": "assistant", "text": "Looks fine to me."}],
                   [{"tool": "estimate_cost"}], [])        # right design state, but the agent said nothing about it
    assert r3["rule_recall"] == 1.0 and r3["mention_recall"] == 0.0 and not r3["pass"]


def test_negative_control_fails_on_a_false_high_risk():
    d = Design()
    t = tool_map(d)
    for typ, name, det in (("cdn", "CDN", "waf=true"), ("alb", "ALB", ""), ("ecs", "S", "tasks=3, autoscaling=true"),
                           ("aurora", "DB", "instances=2, backups=true, encrypted=true"), ("monitoring", "CW", "")):
        t["add_component"](typ, name, det)
    assert score_run(SCENARIOS["clean"], d, [], [], [])["pass"]
    t["set_property"]("DB", "backups", "false")             # a wrongly captured fact creates a high finding
    r = score_run(SCENARIOS["clean"], d, [], [], [])
    assert not r["pass"] and "db-no-backups" in r["high_findings"]


def test_aggregate_reports_pass_rate_over_repeated_runs():
    good = {"scenario": "store", "pass": True, "type_recall": 1.0, "rule_recall": 1.0, "mention_recall": 1.0,
            "extra_components": 0, "median_latency_s": 2.0, "missed_rules": [], "unmentioned_rules": []}
    bad = dict(good, **{"pass": False, "rule_recall": 0.67, "missed_rules": ["s3-public"], "median_latency_s": 3.0})
    s = aggregate([good, bad, good])["store"]
    assert s["runs"] == 3 and s["passed"] == 2 and s["missed_rules"] == ["s3-public"] and s["median_latency_s"] == 2.0


# --- reasoning-leak detection and next_question -------------------------------------------------------
from architect.questions import next_question  # noqa: E402
from architect.scoring import leaks  # noqa: E402


def test_leak_detector_flags_thinking_aloud_but_not_normal_speech():
    bad = [{"role": "assistant", "text": "Okay, the user has added CloudFront. Now I need to ask about the backend."},
           {"role": "assistant", "text": "The instructions say to ask exactly one question at a time."},
           {"role": "assistant", "text": "word " * 120}]
    good = [{"role": "assistant", "text": "I see one high risk: your orders database has no backups. Turn on automated "
                                          "backups and test a restore."},
            {"role": "assistant", "text": "The estimated cost is about seven hundred dollars a month."},
            {"role": "user", "text": "okay the user wants to know"}]  # only assistant turns count
    assert len(leaks(bad)) == 3 and leaks(good) == []


def test_a_leaked_turn_fails_an_otherwise_perfect_run():
    d = perfect_store()
    spoken = [{"role": "assistant", "text": "The database is in a single availability zone, has no backups, and the "
                                            "bucket is public."},
              {"role": "assistant", "text": "Okay, the user wants cost. I need to call the tool."}]
    r = score_run(SCENARIOS["store"], d, spoken, [{"tool": "estimate_cost"}], [2.0])
    assert r["leaked_turns"] == 1 and r["rule_recall"] == 1.0 and not r["pass"]


def test_allowed_extra_type_is_not_counted_as_extra():
    d = Design()
    t = tool_map(d)
    for typ, name, det in (("cdn", "CDN", ""), ("waf", "WAF", ""), ("alb", "ALB", ""), ("ecs", "S", "tasks=3, autoscaling=true"),
                           ("aurora", "DB", "instances=2, backups=true, encrypted=true"), ("monitoring", "CW", "")):
        t["add_component"](typ, name, det)
    r = score_run(SCENARIOS["clean"], d, [], [], [])
    assert r["extra_components"] == 0 and r["unexpected_types"] == []


def test_next_question_prefers_open_questions_then_traffic_then_failure_and_never_repeats():
    d = Design()
    assert next_question(d)["question"] == "What is the system for, and who uses it?"
    d.add_component("rds", "Orders database")
    q1 = next_question(d)
    assert "Orders database" in q1["question"] and ("availability zone" in q1["question"] or "backups" in q1["question"])
    assert "Ask exactly this question" in q1["instruction_for_assistant"]
    seen = {q1["question"]}
    for _ in range(12):
        q = next_question(d)["question"]
        if q is None:
            break
        assert q not in seen                                  # never asks the same thing twice
        seen.add(q)
    assert next_question(d)["question"] is None               # finally says the main areas are covered


def test_next_question_asks_for_traffic_once_the_open_facts_are_stated():
    d = Design()
    d.add_component("rds", "DB", "multi_az=true, backups=true, encrypted=true, public=false")
    d.add_component("monitoring", "CloudWatch")
    assert next_question(d)["question"] == "How many requests per second do you expect at peak?"


# --- turn taking, silent turns, duplicates --------------------------------------------------------------
from architect.scoring import silent_turns  # noqa: E402


def test_silent_turns_counts_user_sentences_that_got_no_reply():
    u, a = (lambda x: {"role": "user", "text": x}), (lambda x: {"role": "assistant", "text": x})
    assert silent_turns([u("a"), a("ok"), u("b"), a("ok")]) == 0
    assert silent_turns([u("a"), u("b"), a("ok")]) == 1          # first sentence never answered
    assert silent_turns([u("a"), a("ok"), u("b")]) == 1          # last sentence never answered
    assert silent_turns([]) == 0


def test_a_silent_turn_fails_an_otherwise_perfect_run():
    d = perfect_store()
    spoken = [{"role": "user", "text": "x"},
              {"role": "assistant", "text": "The database is in a single availability zone, has no backups and the "
                                            "bucket is public."},
              {"role": "user", "text": "y"}]
    r = score_run(SCENARIOS["store"], d, spoken, [{"tool": "estimate_cost"}], [2.0])
    assert r["silent_turns"] == 1 and r["rule_recall"] == 1.0 and not r["pass"]


def test_repeating_add_component_updates_instead_of_duplicating():
    d = Design()
    t = tool_map(d)
    t["add_component"]("ec2", "Web servers", "count=2")
    out = t["add_component"]("ec2", "Web servers", "instance_type=t3.large")
    assert "updated" in out and len(d.of_type("ec2")) == 1
    assert d.find("Web servers").attrs["count"] == 2 and d.find("Web servers").attrs["instance_type"] == "t3.large"
    t["add_component"]("rds", "Web servers")                       # same name, different type: a new component
    assert len(d.components) == 2


def test_add_and_connect_tell_the_model_not_to_speak_until_review_risks():
    t = tool_map(Design())
    out = t["add_component"]("lambda", "A")
    assert "Do not speak yet" in out["instruction_for_assistant"] and "review_risks" in out["instruction_for_assistant"]


# --- one-call update_design ------------------------------------------------------------------------------
from architect.tools import AGENT_TOOLS, agent_tools, apply_update  # noqa: E402


def test_update_design_records_everything_in_one_call_and_returns_risks_and_one_question():
    d = Design()
    t = tool_map(d)
    out = t["update_design"](
        components="rds | Orders database | multi_az=false, backups=false; ec2 | Web servers | count=2; "
                   "s3 | Images | public=true",
        connections="Web servers -> Orders database | sync | orders; Web servers -> Images",
        traffic="requests_per_second=200")
    assert out["errors"] == [] and len(d.components) == 3 and len(d.connections) == 2
    assert d.traffic["avg_rps"] == 200
    assert {f["rule"] for f in out["risks_to_state"]} == {"db-single-az", "db-no-backups", "s3-public"}
    assert out["next_question"] and "ONE spoken reply" in out["instruction_for_assistant"]


def test_update_design_collects_errors_without_stopping_and_tells_the_model_to_ask():
    d = Design()
    out = tool_map(d)["update_design"](components="spaceship | X; lambda | Orders", connections="Orders -> Nowhere",
                                       properties="Orders | turbo=true")
    assert len(d.components) == 1 and d.find("Orders").type == "lambda"       # the good item still went in
    assert len(out["errors"]) == 3 and "could not be recorded" in out["instruction_for_assistant"]


def test_update_design_accepts_the_formats_a_model_actually_writes():
    d = Design()
    done, errors = apply_update(d, components="rds: Orders database\nsqs | Jobs | dead_letter_queue=false",
                                connections="Orders database => Jobs | async", properties="Jobs | dlq=false")
    assert errors == [] and d.find("Jobs").attrs["dlq"] is False
    assert d.connections[0].kind == "async"
    assert any(x.startswith("added") for x in done)


def test_update_design_is_idempotent_and_reports_a_stated_fact_that_arrives_later_once():
    d = Design()
    t = tool_map(d)
    t["update_design"](components="rds | DB")                                   # nothing stated yet
    t["update_design"](components="rds | DB")                                   # repeating it changes nothing
    assert len(d.components) == 1
    out = t["update_design"](properties="DB | multi_az=false")
    assert [f["rule"] for f in out["risks_to_state"]] == ["db-single-az"]
    assert t["update_design"](properties="DB | multi_az=false")["risks_to_state"] == []   # said once, not twice


def test_the_voice_model_sees_only_the_small_tool_set():
    names = [x.tool_name for x in agent_tools(Design())]
    assert names == list(AGENT_TOOLS) and "add_component" not in names and "connect" not in names


# --- robustness found in live runs ----------------------------------------------------------------------
def test_aurora_typed_as_rds_is_corrected_from_the_name():
    d = Design()
    d.add_component("rds", "Aurora database", "count=2, backups=true")      # live run: model typed rds
    c = d.find("Aurora database")
    assert c.type == "aurora" and c.attrs["instances"] == 2 and c.attrs["backups"] is True
    d.add_component("rds", "Orders database")                              # a plain name stays plain rds
    assert d.find("Orders database").type == "rds"
    d.add_component("ec2", "Fargate workers")
    assert d.find("Fargate workers").type == "ecs"
    d.add_component("s3", "Lambda artifacts")                              # different family: never overridden
    assert d.find("Lambda artifacts").type == "s3"


def test_a_used_service_given_as_a_property_becomes_a_component():
    d = Design()
    out = tool_map(d)["update_design"](components="ecs | Service | tasks=3",
                                       properties="Service | monitoring=CloudWatch")
    assert out["errors"] == []
    assert [c.type for c in d.components.values()] == ["ecs", "monitoring"]
    assert d.find("CloudWatch").name == "CloudWatch"


def test_connecting_from_users_creates_the_users_box():
    d = Design()
    out = tool_map(d)["update_design"](components="cdn | CloudFront", connections="Users -> CloudFront | sync")
    assert out["errors"] == [] and d.find("Users").type == "users" and len(d.connections) == 1
    out = tool_map(d)["update_design"](connections="Nobody -> CloudFront")   # unknown, not a users word: still an error
    assert len(out["errors"]) == 1


# --- the detector must not cry wolf ----------------------------------------------------------------------
from architect.scoring import narration  # noqa: E402


def test_ordinary_spoken_answers_are_not_leaks_even_if_they_start_with_okay():
    ok = [{"role": "assistant", "text": "Okay, the biggest risks are: your orders database has no backups, and the product "
                                        "bucket is public."},
          {"role": "assistant", "text": "Okay, the risk is that the order queue has no dead-letter queue."},
          {"role": "assistant", "text": "I added CloudFront and the load balancer. How many requests per second at peak?"}]
    assert leaks(ok) == []


def test_third_person_and_instruction_talk_are_strict_leaks_but_i_need_to_ask_is_only_mild():
    strict = [{"role": "assistant", "text": "Okay, the user mentioned CloudFront."},
              {"role": "assistant", "text": "I should check the risks first."},
              {"role": "assistant", "text": "Hmm, let me think about the next question."}]
    assert len(leaks(strict)) == 3
    mild = [{"role": "assistant", "text": "There are no new risks, but I need to ask about monitoring."}]
    assert leaks(mild) == [] and len(narration(mild)) == 1


def test_numbered_identical_servers_collapse_into_one_component_with_a_count():
    d = Design()
    tm = tool_map(d)
    tm["update_design"](components="ec2 | Web Server 1")
    out = tm["update_design"](components="ec2 | Web Server 2")
    assert len(d.of_type("ec2")) == 1 and "errors" in out and out["errors"] == []
    c = d.of_type("ec2")[0]
    assert c.attrs["count"] == 2 and c.name == "Web Server"
    tm["update_design"](components="ec2 | Web Server 3")
    assert len(d.of_type("ec2")) == 1 and d.of_type("ec2")[0].attrs["count"] == 3
    tm["update_design"](components="ec2 | Worker 1")                      # a different family stays separate
    assert len(d.of_type("ec2")) == 2


def test_collapsed_servers_still_get_the_right_risk_and_cost():
    d = Design()
    tm = tool_map(d)
    tm["update_design"](components="ec2 | Web Server 1; ec2 | Web Server 2")
    assert "single-instance" not in {f.rule for f in __import__("architect.rules", fromlist=["analyze"]).analyze(d)}
    from architect.costs import estimate
    assert estimate(d)["breakdown"][0]["note"].startswith("2 x")


# --- the export must include the diagram, not just a Markdown file ------------------------------------------
import json as _json  # noqa: E402
import urllib.request as _url  # noqa: E402

from architect.doc import to_html, to_markdown  # noqa: E402
from architect.session import Session  # noqa: E402


def _risky_design():
    d = Design()
    tool_map(d)["update_design"](components="cdn | CloudFront; rds | Orders database | multi_az=false, backups=false",
                                 connections="CloudFront -> Orders database")
    return d


def test_markdown_embeds_the_diagram_image_when_a_reference_is_given():
    d = _risky_design()
    assert "![Architecture diagram](diagram.svg)" in to_markdown(d, diagram_ref="diagram.svg")
    assert "![Architecture diagram]" not in to_markdown(d)                    # backwards compatible


def test_html_report_is_self_contained_with_diagram_risks_and_cost():
    html = to_html(_risky_design())
    assert html.count("<svg") == 1 and "Orders database" in html and "HIGH" in html and "per month" in html
    external = html.replace("http://www.w3.org/2000/svg", "")        # the SVG namespace is a name, not a download
    assert "http://" not in external and "https://" not in external and "src=" not in external   # nothing external to load


def test_export_writes_document_diagram_and_report_into_one_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(tools_module, "EXPORT_DIR", tmp_path)
    out = tool_map(_risky_design())["export_design_doc"]()
    from pathlib import Path
    folder = Path(out["folder"])
    assert sorted(p.name for p in folder.iterdir()) == ["design.md", "diagram.svg", "report.html"]
    assert (folder / "diagram.svg").read_text().startswith("<svg")
    assert "![Architecture diagram](diagram.svg)" in (folder / "design.md").read_text()
    assert "diagram" in out["instruction_for_assistant"] and out["file"].endswith("design.md")


def test_live_page_serves_the_downloads():
    s = Session(port=0)
    s.live.port = 0
    s.live.start()
    port = s.live._server.server_address[1]
    s.design.add_component("rds", "DB", "multi_az=false")
    get = lambda p: _url.urlopen(f"http://127.0.0.1:{port}{p}", timeout=5).read().decode()  # noqa: E731
    assert get("/design.svg").startswith("<svg") and "![Architecture diagram](architecture.svg)" in get("/design.md")
    assert "<svg" in get("/report.html") and "diagram PNG" in get("/") and "downloadPng" in get("/")
    s.live.stop()


def test_html_report_forces_a_light_page_and_fits_the_diagram_to_the_width():
    html = to_html(_risky_design())
    assert "color-scheme:light" in html and "background:#fff" in html      # readable even in a dark-mode browser
    assert ".d svg{max-width:100%;height:auto" in html                      # a wide diagram scales instead of overflowing
