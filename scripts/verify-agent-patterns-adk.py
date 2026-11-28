"""Verify the ADK-Rust 3.0 labs of part five (design patterns, D01–D08).

python3 scripts/verify-agent-patterns-adk.py --lesson D01 [--check]

先取 ADK-Rust 源码：python3 scripts/fetch-adk-rust.py .cache/adk-rust（或设 ADK_RUST_SRC）。
每章：打包、在临时目录解压并在旁边放好 adk-rust/，fmt、clippy -D warnings、cargo test、离线构建；
摘要和几条详细轨迹各连跑两次必须逐字节相同，逐行核对场景，并把结果表写进正文。
尚未迁移的章节仍由 verify-agent-patterns.py 检查。
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import learn_agent_rust_adk as adk  # noqa: E402
from learn_agent_rust_adk import require  # noqa: E402

ROOT = adk.ROOT
OUTPUT = adk.PUBLIC / "outputs"
FILES = ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "README.md", ".gitignore",
         ".cargo/config.toml", "src/main.rs", "src/trace.rs"]
EXTRA = {"fetch-adk-rust.py": ROOT / "scripts/fetch-adk-rust.py",
         "learn-agent-rust-adk.json": ROOT / "scripts/learn-agent-rust-adk.json"}


def d01_checks(outputs):
    workflow = outputs["d01-workflow.txt"]
    require("[read_root] state   root_readme" in workflow and "[writer] text" in workflow,
            "the workflow passes state from code steps to the writer")
    forbidden = outputs["d01-forbidden.txt"]
    require("code=read.outside_workspace" in forbidden, "the path check refuses ../secret.txt")
    require("Max iterations (2) exceeded" in outputs["d01-budget.txt"], "max_iterations stops the third model call")
    require("[read_member] escalate" in outputs["d01-workflow-missing.txt"], "the read step escalates")
    require('member_readme = ""' in outputs["d01-workflow-silent.txt"] and "[writer] text" in outputs["d01-workflow-silent.txt"],
            "without escalate the writer still runs")


def d02_checks(outputs):
    stale = outputs["d02-stale.txt"]
    require(stale.count('state   artifact = "{\\"kind\\":\\"readme\\",\\"revision\\":\\"r1\\"') == 2,
            "the stale artifact passed the schema and was written to state")
    require("[readme_render]" not in stale.split("修订：r2", 1)[1], "the gate stopped the chain before render")
    trap = outputs["d02-substring-trap.txt"]
    require("[Routing to: 不是 readme，是 license]" in trap and "[readme_extract]" in trap, "substring match routes to readme")
    require('"followed":false' in outputs["d02-low-confidence.txt"], "the low-confidence decision is recorded as not followed")
    require("output schema validation failed after 1 attempts" in outputs["d02-missing-field.txt"],
            "missing-field ends with the schema error")
    require(outputs["d02-schema-retry.txt"].count("[readme_extract] text") == 2, "schema-retry shows the rejected and the corrected reply")
    require("[readme_gate] escalate" in stale, "the gate escalates")


def d03_checks(outputs):
    failure = outputs["d03-failure.txt"]
    require("check_config =" in failure and "check_docs =" in failure and "[merge]" not in failure,
            "siblings finish and write state, the merge never runs")
    escalate = outputs["d03-escalate.txt"]
    require("[config_checker] escalate" in escalate and "deps_checker" not in escalate, "escalation drops the other branches")
    collision = [l for l in outputs["d03-key-collision.txt"].splitlines() if "state   check =" in l]
    require(len(collision) == 3 and collision[-1].startswith("[docs_checker]"), "the last writer (docs) wins the shared key")


def d04_checks(outputs):
    discover = outputs["d04-discover.txt"]
    require(discover.count("write_plan status=ok") == 3 and "[planner] escalate" in discover, "three accepted plans, exit_loop")
    require("done_step_removed:s1" in outputs["d04-drops-done.txt"], "the dropped done step is refused")
    approved = outputs["d04-plan-mode-approved.txt"]
    require("plan mode does not allo" in approved and "mode→ask" in approved, "plan mode refuses edits, approval switches to ask")
    require("depends" in outputs["d04-plan-mode-invalid.txt"], "an unknown dependency is refused")
    require("planner_saw=[0,0,1,1," in outputs["d04-summary.txt"],
            "the instruction template is rendered once per planner run, not once per model call")
    turn1 = approved.split("--- turn: 开始执行")[0].split("exit_plan_mode ok mode→ask", 1)[1].strip().splitlines()
    require(len(turn1) == 1 and turn1[0].startswith("[state]  harness:plan steps=2 planHash="),
            "an approved exit_plan_mode ends the turn and mirrors harness:plan into session state")
    rejected = outputs["d04-plan-mode-rejected.txt"]
    require("[state]  harness:plan 没有写入" in rejected and "mode→" not in rejected, "a rejected plan leaves plan mode unchanged")


def d05_checks(outputs):
    handoff = outputs["d05-handoff.txt"]
    turn2 = handoff.split("--- turn: 好的，接下来呢？")[1]
    require("[lead] handoff → license" in handoff and turn2.lstrip().startswith("[license] text"),
            "after a handoff the next user turn goes straight to license")
    require("uncovered: []" in handoff, "the handoff scenario covers both declared relationships")
    note = outputs["d05-handoff-note.txt"]
    require(note.index("[lead] state   handoff_note =") < note.index("[lead] handoff → license")
            and "收到交接说明" in note and "不知道是哪个许可证问题" in handoff,
            "license only knows what the handoff note in session state tells it")
    require('uncovered: ["lead -Handoff-> license"]' in outputs["d05-two.txt"], "the receipt shows the unused handoff edge")
    undeclared = outputs["d05-undeclared.txt"]
    require("status=not_run" in undeclared and 'Available agents: [\\"license\\"]' in undeclared,
            "a handoff to a delegate-only member is refused and lead keeps control")
    failed = outputs["d05-worker-failed.txt"]
    require('"agent":"member_check","error":"model.unavailable' in failed and "lead→member_check delegate failed" in failed,
            "returnError hands the worker failure back to lead and the receipt records it")
    require("used 3, maximum 2" in outputs["d05-budget.txt"], "the delegation budget stops the run")
    require("开始时刻（毫秒）：[0, 0, 30]" in outputs["d05-three.txt"],
            "with maxConcurrentDelegations=2 the third worker starts only after the first one finishes")
    require("消息数：[1, 1]" in outputs["d05-shared-context.txt"],
            "even with shared context the worker's history holds only its own request in turn one")
    require("cycle involving 'lead'" in outputs["d05-cycle.txt"], "a hand-back edge makes the topology cyclic")
    require('[resume] UnsafeDelegate { edge_id: "check-core"' in outputs["d05-interrupted.txt"],
            "an interrupted delegation is not replayed")


def d06_checks(outputs):
    normal = outputs["d06-normal.txt"]
    require('"self_check\\":\\"已自查，没有问题' in normal and "repair:missing_source" in normal,
            "the evaluator ignores the writer's self-check")
    require("[evaluator] escalate" in normal, "acceptance escalates out of the loop")
    require("[evaluator] escalate" not in outputs["d06-never-good.txt"], "the loop limit ends without escalation")
    require('state   baseline = {"revision":1' in outputs["d06-new-error.txt"], "the first draft is kept as the baseline")
    retry = outputs["d06-tool-retry.txt"]
    require("status=ok {\"reflection\":\"[RETRY GUIDANCE - Attempt 1/2]" in retry,
            "the plugin replaces the failed result with a reflection prompt marked ok")
    exhausted = outputs["d06-tool-retry-exhausted.txt"]
    require("Attempt 2/2" in exhausted and "status=failed code=tool.file_not_found" in exhausted,
            "after max_retries the raw error reaches the model")
    wandering = outputs["d06-tool-retry-wandering.txt"]
    require(wandering.count("Attempt 1/2") == 3 and "id=read-4 read_file status=failed" in wandering,
            "each new argument gets its own count; global_limit stops the fourth hint")
    require("[evaluator] escalate" in outputs["d06-no-progress.txt"], "no progress escalates out of the loop")
    require('每一稿依据的反馈：["-", "missing_source", "empty_text"]' in outputs["d06-new-error.txt"],
            "the writer repairs from the rendered feedback")


def d07_disk(binary, folder, env):
    """Each command is its own process; state lives only in the SQLite file in a fresh directory."""
    import tempfile
    steps = [("start", "写 3.0 的升级说明并发布"), ("pending", None), ("edit", "升级到 3.0：把 member 的启动命令改成 serve，并更新 CI 脚本。"),
             ("resume", None), ("show", None), ("revoke", "需求变了")]
    transcript = []
    with tempfile.TemporaryDirectory() as work:
        for command, arg in steps:
            args = [binary, "disk", work, command] + ([arg] if arg else [])
            ok = (2,) if command == "revoke" else (0,)
            result = adk.run(args, folder, env, ok=ok)
            shown = "disk DIR " + command + (f" \"{arg}\"" if arg else "")
            transcript.append(f"$ cargo run --locked -- {shown}")
            transcript.append((result.stdout + result.stderr).rstrip())
    return {"d07-disk.txt": "\n".join(transcript) + "\n"}


def d07_checks(outputs):
    disk = outputs["d07-disk.txt"]
    require("step: start:held" in disk and "step: edit" in disk and "[file] releases/3.0.md 升级到 3.0：把 member 的启动命令改成 serve，并更新 CI 脚本。" in disk,
            "separate processes: hold, edit-approve, resume and publish through the SQLite file")
    require(disk.rstrip().endswith("nothing is held: the approval was already used or never given"),
            "revoking after the approval was used is refused instead of leaving a standing denial")
    approve = outputs["d07-approve.txt"]
    resume = approve.split("--- resume")[1]
    require("[writer]" not in resume and "[publisher] result  id=publish publish_report status=ok" in resume,
            "the workflow resumes at the held publisher; the writer does not run again")
    require("status=held" in approve.split("--- approve")[0] and "\"status\":\"confirmation_pending\"" in approve.split("--- approve")[0], "the publish call is held")
    changed = outputs["d07-changed-mind.txt"].split("--- say 改成 3.1 再发")[1]
    require("[writer]" not in changed and "[publisher] call" not in changed
            and "[publisher] result  id=publish publish_report status=ok {\"published\":\"releases/3.0.md\"}" in changed,
            "a new message after approval runs the approved held call before the model is asked")
    revoked = outputs["d07-changed-mind-revoked.txt"]
    require("the approver declined it: 需求变了：改发 3.1" in revoked
            and revoked.index("declined it") < revoked.index('"target":"releases/3.1.md"'),
            "the revoked approval is settled first, then the new request is held and published")
    require("the approver declined it: 目标版本写错了，先别发" in outputs["d07-deny.txt"], "the denial reason reaches the model")
    require("approver's edited arguments denied by policy" in outputs["d07-edit-forbidden.txt"], "edited args are rechecked")
    require("[version_check] escalate" in outputs["d07-clarify.txt"], "the version check stops the workflow to ask")


def d08_extra(binary, folder, env):
    """`live` through adk-model's OpenAI-compatible client against a loopback fixture; model_compare.py self-test."""
    import tempfile
    live = adk.run([sys.executable, "live_fixture.py", "--", binary, "live"], folder, env)
    kept = [line for line in live.stdout.splitlines() if line.startswith(("live: ", "fixture: "))]
    with tempfile.TemporaryDirectory() as work:
        adk.run([sys.executable, "model_compare.py", "self-test", str(Path(work) / "run")], folder, env)
        report = json.loads((Path(work) / "run" / "report.json").read_text())
    kept.append(f"model_compare self-test: attempted_tasks={report['attempted_tasks']} "
                f"planned_tasks={report['planned_tasks']} live_provider=not_run")
    return {"d08-live.txt": "\n".join(kept) + "\n"}


def d08_checks(outputs):
    naive = outputs["d08-naive.txt"]
    require("[evaluator] escalate" in naive and "[publisher]" not in naive,
            "the evaluator's escalate also stops the outer SequentialAgent")
    normal = outputs["d08-normal.txt"]
    require("[evaluator] escalate" not in normal and "status=held" in normal and '"published":"releases/3.0.md"' in normal,
            "the boundary clears the inner escalate; publishing is held, approved and resumed")
    require("[refine_boundary] escalate" in outputs["d08-never-accepted.txt"], "no accepted draft stops the pipeline")
    budget = outputs["d08-budget.txt"]
    require("[publisher]" not in budget and budget.index('"accepted"') < budget.index("stop    code=budget.model_calls"),
            "one run budget covers every stage: the loop passes, the publisher's call is refused")
    resumed = outputs["d08-normal.txt"].split("--- approve")[1]
    require(all(line.startswith(("[publisher]", "--- run")) for line in resumed.strip().splitlines()[:-1]),
            "the resume runs only the held publisher")
    live = outputs["d08-live.txt"]
    require("live: steps=[run:held,approve,resume] published=yes stop=completed" in live
            and "fixture: requests=6 roles=[deps_checker,docs_checker,publisher,publisher,writer,writer]" in live
            and "attempted_tasks=36 planned_tasks=36" in live,
            "the OpenAI-compatible client runs the same pipeline; model_compare self-test passes")


LESSONS = {
    "D01": dict(
        slug="pattern-selection", tests=4,
        details=["single-partial", "workflow", "workflow-new-member", "workflow-missing", "workflow-silent", "adaptive",
                 "forbidden", "budget"],
        scope="D01 on ADK-Rust 3.0 RC: one LlmAgent call, SequentialAgent of CustomAgent read steps and a writer "
              "(state via instruction templates, escalate stops the sequence), LlmAgent tool loop with max_iterations; "
              "rule-based model, real temp-dir files, application acceptance check",
        expected={
            "single": "structure=single agents=[writer] model_calls=1 reads=[] verdict=accepted",
            "single-partial": "structure=single agents=[writer] model_calls=1 reads=[] "
                              "verdict=rejected:missing:member/README.md",
            "workflow": "structure=workflow agents=[read_root,read_member,writer] model_calls=1 "
                        "reads=[README.md,member/README.md] verdict=accepted",
            "workflow-new-member": "structure=workflow agents=[read_root,read_member,writer] model_calls=1 "
                                   "reads=[README.md,member/README.md] verdict=rejected:missing:plugin/README.md",
            "workflow-missing": "structure=workflow agents=[read_root,read_member] model_calls=0 "
                                "reads=[README.md] verdict=rejected:escalated",
            "workflow-silent": "structure=workflow agents=[read_root,read_member,writer] model_calls=1 "
                               "reads=[README.md] verdict=rejected:missing:member/README.md",
            "adaptive": "structure=adaptive agents=[explorer] model_calls=4 "
                        "reads=[README.md,member/README.md,plugin/README.md] verdict=accepted",
            "forbidden": "structure=adaptive agents=[explorer] model_calls=3 reads=[README.md] verdict=rejected:no_report",
            "budget": "structure=adaptive agents=[explorer] model_calls=2 reads=[README.md,member/README.md] "
                      "verdict=rejected:max_iterations",
        },
        columns=[("structure", "结构"), ("agents", "经过的 Agent"), ("model_calls", "模型调用"),
                 ("reads", "读过的文件"), ("verdict", "应用验收")],
        checks=d01_checks),
    "D02": dict(
        slug="prompt-chaining-routing", tests=4,
        details=["stale", "substring-trap", "low-confidence", "missing-field", "schema-retry"],
        scope="D02 on ADK-Rust 3.0 RC: SequentialAgent chain (output_schema extraction with retries, CustomAgent "
              "revision gate that escalates, render), LlmConditionalAgent / ConditionalAgent / DecisionAgent routing; "
              "rule-based model",
        expected={
            "readme": "router=llm route=readme agents=[router,readme_extract,readme_gate,readme_render] "
                      "model_calls=[route,extract,render] gate=passed outcome=report",
            "cargo": "router=llm route=cargo agents=[router,cargo_extract,cargo_gate,cargo_render] "
                     "model_calls=[route,extract,render] gate=passed outcome=report",
            "unknown": "router=llm route=needs_input agents=[router,needs_input] model_calls=[route] gate=- outcome=needs_input",
            "substring-trap": "router=llm route=readme agents=[router,readme_extract] model_calls=[route,extract,extract] "
                              "gate=- outcome=error",
            "rule-router": "router=rule route=cargo agents=[cargo_extract,cargo_gate,cargo_render] "
                           "model_calls=[extract,render] gate=passed outcome=report",
            "rule-router-other": "router=rule route=needs_input agents=[needs_input] model_calls=[] gate=- "
                                 "outcome=needs_input",
            "low-confidence": "router=decision route=needs_input agents=[router,needs_input] model_calls=[decide] "
                              "gate=- outcome=needs_input",
            "missing-field": "router=llm route=readme agents=[router,readme_extract] model_calls=[route,extract,extract] "
                             "gate=- outcome=error",
            "schema-retry": "router=llm route=readme agents=[router,readme_extract,readme_gate,readme_render] "
                            "model_calls=[route,extract,extract,render] gate=passed outcome=report",
            "stale": "router=llm route=readme agents=[router,readme_extract,readme_gate] "
                     "model_calls=[route,extract,render,route,extract] gate=stale_artifact:r1 outcome=stopped",
        },
        columns=[("router", "路由"), ("route", "进入的分支"), ("model_calls", "模型调用"), ("gate", "质量门"),
                 ("outcome", "结果")],
        checks=d02_checks),
    "D03": dict(
        slug="parallel-decomposition", tests=4,
        details=["normal", "failure", "escalate", "key-collision"],
        scope="D03 on ADK-Rust 3.0 RC: ParallelAgent of three LlmAgent checkers (output_key per branch, exit_loop "
              "escalation), SequentialAgent with a CustomAgent merge that checks members and revisions; rule-based "
              "model with fixed delays so branches overlap",
        expected={
            "normal": "started=[config,deps,docs] finished=[config,deps,docs] peak_concurrent=3 outcome=report report_sha=396f74b4",
            "reverse": "started=[config,deps,docs] finished=[docs,deps,config] peak_concurrent=3 outcome=report report_sha=396f74b4",
            "failure": "started=[config,deps,docs] finished=[config,docs] peak_concurrent=3 outcome=error:model.unavailable",
            "escalate": "started=[config,deps,docs] finished=[config] peak_concurrent=3 outcome=escalated_by:config_checker",
            "stale": "started=[config,deps,docs] finished=[config,deps,docs] peak_concurrent=3 outcome=stale_result:deps@r1",
            "missing": "started=[config,deps,docs] finished=[config,deps,docs] peak_concurrent=3 "
                       "outcome=member_mismatch:missing=docs",
            "key-collision": "started=[config,deps,docs] finished=[config,deps,docs] peak_concurrent=3 "
                             "outcome=member_mismatch:missing=config+deps",
        },
        columns=[("finished", "完成先后"), ("peak_concurrent", "同时进行"), ("outcome", "结果"),
                 ("report_sha", "报告指纹")],
        checks=d03_checks),
    "D04": dict(
        slug="plan-execute-replan", tests=4,
        details=["discover", "drops-done", "missing-file", "stuck", "plan-mode-approved", "plan-mode-rejected",
                 "plan-mode-invalid"],
        scope="D04 on ADK-Rust 3.0 RC: LoopAgent of a planner LlmAgent (write_plan checked by the application, "
              "exit_loop) and an executor CustomAgent with a result ledger; adk-harness (Beta) plan mode with "
              "exit_plan_mode approval; rule-based model and approver, real temp-dir files",
        expected={
            "discover": "revisions=[1,2,3] rejected=[] executed=[README.md,member/README.md,plugin/README.md] "
                        "iterations=3 planner_saw=[0,0,1,1,2,2,3] stop=completed",
            "drops-done": "revisions=[1,2,3] rejected=[done_step_removed:s1,done_step_removed:s1] "
                          "executed=[README.md,member/README.md,plugin/README.md] iterations=3 "
                          "planner_saw=[0,0,1,1,1,2,2,2,3] stop=completed",
            "missing-file": "revisions=[1,2] rejected=[] executed=[README.md,member/README.md(missing)] iterations=2 "
                            "planner_saw=[0,0,1,1] stop=step_failed",
            "stuck": "revisions=[1,2,3] rejected=[] executed=[README.md,member/README.md,plugin/README.md] iterations=6 "
                     "planner_saw=[0,0,1,1,2,2,3,3,3] stop=loop_limit",
            "plan-mode-approved": "tools=[read_file:ok,write_file:refused,exit_plan_mode:ok,write_file:ok] "
                                  "asked=[exit_plan_mode@plan:approve,write_file@ask:approve] file_written=yes",
            "plan-mode-rejected": "tools=[read_file:ok,write_file:refused,exit_plan_mode:refused,write_file:refused] "
                                  "asked=[exit_plan_mode@plan:deny] file_written=no",
            "plan-mode-invalid": "tools=[read_file:ok,write_file:refused,exit_plan_mode:failed(harness.plan.invalid),"
                                 "write_file:refused] asked=[exit_plan_mode@plan:approve] file_written=no",
        },
        columns=[("revisions", "计划修订"), ("rejected", "被拒计划"), ("executed", "执行过的文件"), ("stop", "循环结束"),
                 ("tools", "计划模式的工具结果"), ("asked", "问人"), ("file_written", "写出文件")],
        checks=d04_checks),
    "D05": dict(
        slug="orchestrator-workers-handoffs", tests=4,
        details=["two", "three", "shared-context", "handoff", "handoff-note", "undeclared", "worker-failed", "budget", "cycle", "interrupted"],
        scope="D05 on ADK-Rust 3.0 RC: TeamSpec (JSON) compiled to a CompiledTeam of three LlmAgents; Delegate edge "
              "lowered to AgentTool (parallel tool calls, max 2 concurrent, isolated vs shared context, returnError), "
              "Handoff edge via transfer_to_agent with a handoff note in session state, team budget, cycle rejection, execution receipts, analysis and "
              "resume plan; rule-based model, paused Tokio clock",
        expected={
            "two": "workers=[api,cli] peak=2 worker_saw=[-,-] edges=[delegate:completed,delegate:completed] "
                   "turn1=lead turn2=lead coverage=50%",
            "three": "workers=[api,cli,core] peak=2 worker_saw=[-,-,-] "
                     "edges=[delegate:completed,delegate:completed,delegate:completed] turn1=lead turn2=lead coverage=50%",
            "shared-context": "workers=[api,cli] peak=2 worker_saw=[note,note] edges=[delegate:completed,delegate:completed] "
                              "turn1=lead turn2=lead coverage=50%",
            "handoff": "workers=[api,cli,core] peak=2 worker_saw=[-,-,-] "
                       "edges=[delegate:completed,delegate:completed,delegate:completed,handoff:completed] "
                       "turn1=license turn2=license license_knew=no coverage=100%",
            "handoff-note": "workers=[api,cli,core] peak=2 worker_saw=[-,-,-] "
                            "edges=[delegate:completed,delegate:completed,delegate:completed,handoff:completed] "
                            "turn1=license turn2=license license_knew=yes coverage=100%",
            "undeclared": "workers=[api,cli,core] peak=2 worker_saw=[-,-,-] "
                          "edges=[delegate:completed,delegate:completed,delegate:completed] turn1=lead turn2=lead coverage=50%",
            "worker-failed": "workers=[api,cli] peak=2 worker_saw=[-,-] edges=[delegate:completed,delegate:failed] "
                             "turn1=lead turn2=lead coverage=50%",
            "budget": "workers=[api,cli] peak=2 worker_saw=[-,-] edges=[delegate:completed,delegate:running,delegate:running] "
                      "stop=error:agent.team.budget_exceeded",
            "cycle": "stop=invalid_spec:CyclicTopology",
            "interrupted": "workers=[api,cli,core] peak=2 worker_saw=[-,-,-] "
                           "edges=[delegate:completed,delegate:running,delegate:running] stop=interrupted:UnsafeDelegate",
        },
        columns=[("workers", "派出的工作者"), ("peak", "同时进行"), ("worker_saw", "工作者看到备忘"),
                 ("edges", "执行回执"), ("turn1", "第一轮回答"), ("turn2", "第二轮回答"), ("license_knew", "license 知道问题"),
                 ("coverage", "关系覆盖"),
                 ("stop", "异常结束")],
        checks=d05_checks),
    "D06": dict(
        slug="evaluator-reflection", tests=4,
        details=["normal", "new-error", "no-progress", "never-good", "tool-retry", "tool-retry-exhausted",
                 "tool-retry-wandering"],
        scope="D06 on ADK-Rust 3.0 RC: LoopAgent of a writer LlmAgent (output_key, instruction templates) and a "
              "rule-based evaluator CustomAgent (feedback and baseline in session state, escalate on acceptance or "
              "no progress, max_iterations 3); adk-retry-reflect plugin on an LlmAgent tool (max_retries 2, "
              "global_limit 3); rule-based models",
        expected={
            "normal": "checks=[r1:missing_source,r2:pass] iterations=2 baseline=r1 stop=accepted",
            "already-good": "checks=[r1:pass] iterations=1 baseline=r1 stop=accepted",
            "new-error": "checks=[r1:missing_source,r2:empty_text,r3:pass] iterations=3 baseline=r1 stop=accepted",
            "no-progress": "checks=[r1:missing_source,r2:missing_source] iterations=2 baseline=r1 stop=no_progress",
            "never-good": "checks=[r1:missing_source,r2:unread_source,r3:unread_source] iterations=3 baseline=r1 "
                          "stop=loop_limit",
            "tool-retry": "calls=[READMe.md:reflection,README.md:ok] outcome=read stop=answered",
            "tool-retry-exhausted": "calls=[READMe.md:reflection,READMe.md:reflection,READMe.md:error] "
                                    "outcome=gave_up stop=answered",
            "tool-retry-wandering": "calls=[READMe.md:reflection,readme.md:reflection,Readme.md:reflection,"
                                    "README.txt:error] outcome=gave_up stop=answered",
        },
        columns=[("checks", "每一稿的检查结果"), ("iterations", "轮数"), ("stop", "结束方式"),
                 ("calls", "读文件的尝试"), ("outcome", "结果")],
        checks=d06_checks),
    "D07": dict(
        slug="human-in-the-loop", tests=4,
        details=["approve", "no-decision", "deny", "edit", "edit-forbidden", "clarify", "changed-mind",
                 "changed-mind-revoked"],
        scope="D07 on ADK-Rust 3.0 RC: SequentialAgent (writer LlmAgent, version-check CustomAgent, publisher "
              "LlmAgent) with a ToolPolicy that requires approval; SqliteSessionService + SqliteApprovalStore in one "
              "file, every step a fresh store (and, for the disk transcript, a separate process); approve, deny with "
              "message, approver-edited args rechecked by policy, clarification via escalate, held-call resume "
              "position, revocation by re-deciding; rule-based model, real files",
        expected={
            "approve": "steps=[start:held,approve,resume] writer_runs=1 published=[3.0.md] pending=0",
            "no-decision": "steps=[start:held,resume:held] writer_runs=1 published=[] pending=1",
            "deny": "steps=[start:held,deny,resume] writer_runs=1 published=[] pending=0",
            "edit": "steps=[start:held,edit,resume] writer_runs=1 published=[3.0.md(edited)] pending=0",
            "edit-forbidden": "steps=[start:held,edit-target,resume] writer_runs=1 published=[] pending=0",
            "clarify": "steps=[start,say:held,approve,resume] writer_runs=2 published=[3.0.md] pending=0",
            "changed-mind": "steps=[start:held,approve,say] writer_runs=1 published=[3.0.md] pending=0",
            "changed-mind-revoked": "steps=[start:held,approve,revoke,resume,say:held,approve,resume] writer_runs=2 "
                                    "published=[3.1.md] pending=0",
        },
        columns=[("steps", "步骤（:held 表示之后有调用在等批准）"), ("writer_runs", "写作者运行次数"),
                 ("published", "发布的文件"), ("pending", "最后仍在等待")],
        extra=d07_disk,
        checks=d07_checks),
    "D08": dict(
        slug="pattern-composition", tests=4,
        details=["naive", "normal", "stale-branch", "branch-failed", "never-accepted", "budget"],
        scope="D08 on ADK-Rust 3.0 RC: SequentialAgent composing ParallelAgent checks, a merge CustomAgent, a "
              "LoopAgent writer/evaluator (with and without an escalate-containing boundary CustomAgent) and an "
              "approval-gated publisher; one RunBudget for the run; rule-based model, plus the same pipeline through "
              "adk-model OpenAIClient::compatible against a loopback fixture and model_compare.py self-test",
        expected={
            "naive": "model_calls=4 checkers=2 writer=2 publisher=0 steps=[run] published=no stop=escalated_by:evaluator",
            "normal": "model_calls=6 checkers=2 writer=2 publisher=2 steps=[run:held,approve,resume] published=yes "
                      "stop=completed",
            "stale-branch": "model_calls=2 checkers=2 writer=0 publisher=0 steps=[run] published=no "
                            "stop=merge:stale_result:deps@r1",
            "branch-failed": "model_calls=2 checkers=2 writer=0 publisher=0 steps=[run] published=no "
                             "stop=error:model.unavailable",
            "never-accepted": "model_calls=5 checkers=2 writer=3 publisher=0 steps=[run] published=no "
                              "stop=refine:no_accepted_draft",
            "budget": "model_calls=4 checkers=2 writer=2 publisher=0 steps=[run] published=no "
                      "stop=error:budget.model_calls",
            "budget-resume": "model_calls=6 checkers=2 writer=2 publisher=2 steps=[run:held,approve,resume] "
                             "published=yes stop=completed",
        },
        columns=[("model_calls", "模型调用"), ("checkers", "检查者"), ("writer", "写作者"), ("publisher", "发布者"),
                 ("steps", "步骤"), ("published", "发布"), ("stop", "结束原因")],
        files=["model_compare.py", "model-cases.json", "live_fixture.py"],
        extra=d08_extra,
        checks=d08_checks),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def rows_of(summary):
    rows = []
    for line in summary.splitlines():
        name, rest = line.split(": ", 1)
        fields = dict(item.split("=", 1) for item in rest.split(" "))
        rows.append(dict(name=name, summary=rest, **fields))
    return rows


def verify(lesson, config, folder, env):
    binary = Path(env["CARGO_TARGET_DIR"]) / "debug" / config["slug"]
    summary = adk.repeat_identical([binary], folder, env, times=2)
    rows = rows_of(summary)
    expected = config["expected"]
    require([r["name"] for r in rows] == list(expected), f"{lesson}: scenario list changed")
    for row in rows:
        require(row["summary"] == expected[row["name"]],
                f"{lesson}/{row['name']}: expected {expected[row['name']]}, got {row['summary']}")
    prefix = lesson.lower()
    outputs = {f"{prefix}-summary.txt": summary}
    for name in config["details"]:
        outputs[f"{prefix}-{name}.txt"] = adk.repeat_identical([binary, name], folder, env, times=2)
    if "extra" in config:
        outputs.update(config["extra"](binary, folder, env))
    config["checks"](outputs)
    usage = adk.run([binary, "no-such-scenario"], folder, env, ok=(2,))
    require("usage:" in usage.stderr, f"{lesson}: unknown scenario must print usage")
    return outputs, rows


def table(rows, columns):
    lines = ["| 场景 | " + " | ".join(title for _, title in columns) + " |",
             "| --- | " + " | ".join("---" for _ in columns) + " |"]
    for r in rows:
        lines.append("| `{}` | {} |".format(r["name"], " | ".join(f"`{r[key]}`" if key in r else "—" for key, _ in columns)))
    return "\n".join(lines)


def run_lesson(lesson, check):
    config = LESSONS[lesson]
    slug = config["slug"]
    files = adk.chapter_files(slug, FILES + config.get("files", []))
    files.update({name: path.read_bytes() for name, path in EXTRA.items()})
    packed = adk.pack(slug, files)
    archive = adk.PUBLIC / f"{slug}.zip"
    env = adk.cargo_env(f"learn-agent-{lesson.lower()}-target")
    with adk.staged(slug, packed) as folder:
        checks = adk.standard_checks(folder, env)
        require(checks["rust_tests_passed"] == config["tests"], f"{lesson}: expected {config['tests']} Rust tests, got {checks}")
        outputs, rows = verify(lesson, config, folder, env)
        header = adk.evidence_header(folder, env)
    evidence_path = ROOT / f"scripts/data/learn-agent-rust/{lesson.lower()}-results.json"
    evidence = dict(scope=config["scope"], **header, source_sha256={n: sha(d) for n, d in sorted(files.items())},
                    archive_sha256=sha(packed), **checks, repeated_identical_runs=2,
                    scenarios=[{k: v for k, v in r.items() if k != "summary"} for r in rows],
                    outputs_sha256={n: sha(t.encode()) for n, t in sorted(outputs.items())})
    if check and evidence_path.exists():
        recorded = json.loads(evidence_path.read_text())
        evidence["rustc"], evidence["cargo"] = recorded.get("rustc"), recorded.get("cargo")
    chapter_path = ROOT / f"docs/learn-agent-rust/{slug}.md"
    start, end = f"<!-- {lesson.lower()}-results:start -->", f"<!-- {lesson.lower()}-results:end -->"
    text = chapter_path.read_text()
    before, rest = text.split(start, 1)
    chapter = before + start + "\n\n" + table(rows, config["columns"]) + "\n\n" + end + rest.split(end, 1)[1]
    targets = {OUTPUT / name: t.encode() for name, t in outputs.items()}
    targets[archive] = packed
    targets[evidence_path] = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode()
    targets[chapter_path] = chapter.encode()
    stale = [p for p in OUTPUT.glob(f"{lesson.lower()}-*") if p not in targets]
    for path, content in targets.items():
        if check:
            require(path.exists() and path.read_bytes() == content, f"Stale {lesson} artifact: {path.relative_to(ROOT)}")
        else:
            path.write_bytes(content)
    if check:
        require(not stale, f"Obsolete {lesson} outputs: " + ", ".join(p.name for p in stale))
    else:
        for path in stale:
            path.unlink()
    print(f"{lesson}: {len(rows)} scenarios x2 identical, {checks['rust_tests_passed']} Rust tests, fmt, Clippy; "
          + ("artifacts checked" if check else "artifacts saved"), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lesson", choices=sorted(LESSONS), action="append")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for lesson in args.lesson or sorted(LESSONS):
        run_lesson(lesson, args.check)


if __name__ == "__main__":
    main()
