use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{collections::HashSet, fs, path::Path};

const GOAL: &str = "读取 README，整理启动说明";
const README: &str = "项目：Rust Agent 练习\n启动命令：cargo run --release\n要求：Rust 1.99.1\n";
const CASES: &[&str] = &[
    "normal",
    "claims-only",
    "read-error",
    "budget-stop",
    "fresh-session",
    "two-active",
    "skip-completion",
    "unknown-status",
    "duplicate-id",
    "empty-content",
    "too-many",
    "remove-item",
    "changed-content",
    "stale-revision",
    "reopen-completed",
    "append-step",
    "yield-step",
    "permission-denied",
    "invalid-json",
    "unknown-field",
];

// region types
#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
enum Status {
    Pending,
    InProgress,
    Completed,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct Item {
    id: String,
    content: String,
    status: Status,
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
struct Plan {
    goal: String,
    revision: u64,
    items: Vec<Item>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct WriteArgs {
    expected_revision: u64,
    items: Vec<Item>,
}
// endregion types

// region transition
fn can_move(from: Status, to: Status) -> bool {
    from == to
        || matches!(
            (from, to),
            (Status::Pending, Status::InProgress)
                | (Status::InProgress, Status::Completed)
                | (Status::InProgress, Status::Pending)
        )
}
// endregion transition

impl Plan {
    fn new() -> Self {
        Self {
            goal: GOAL.into(),
            revision: 0,
            items: vec![],
        }
    }

    // region validate
    fn write(&mut self, args: WriteArgs) -> Result<(), &'static str> {
        if args.expected_revision != self.revision {
            return Err("revision_conflict");
        }
        if args.items.is_empty() || args.items.len() > 8 {
            return Err("item_count");
        }
        let mut ids = HashSet::new();
        let mut active = 0;
        for item in &args.items {
            if item.id.is_empty()
                || item.id.len() > 24
                || !item
                    .id
                    .bytes()
                    .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'-')
            {
                return Err("invalid_id");
            }
            if !ids.insert(item.id.as_str()) {
                return Err("duplicate_id");
            }
            if item.content.trim().is_empty() || item.content.chars().count() > 120 {
                return Err("invalid_content");
            }
            active += usize::from(item.status == Status::InProgress);
            match self.items.iter().find(|old| old.id == item.id) {
                Some(old) => {
                    if old.content != item.content {
                        return Err("content_changed");
                    }
                    if !can_move(old.status, item.status) {
                        return Err("invalid_transition");
                    }
                }
                None if item.status != Status::Pending => return Err("new_item_not_pending"),
                None => {}
            }
        }
        if active > 1 {
            return Err("multiple_active");
        }
        if self.items.iter().any(|old| !ids.contains(old.id.as_str())) {
            return Err("removed_item");
        }
        // Commit only after the complete candidate passes every check.
        self.items = args.items;
        self.revision += 1;
        Ok(())
    }
    // endregion validate
}

// region messages
#[derive(Clone, Debug, Serialize)]
struct Call {
    call_id: String,
    tool: String,
    arguments: String,
}

#[derive(Clone, Debug, Serialize)]
struct ToolResult {
    call_id: String,
    ok: bool,
    code: String,
    data: Value,
}

#[derive(Serialize)]
struct ModelInput {
    goal: String,
    plan: Plan,
    history: Vec<Value>,
}

struct Runtime {
    plan: Plan,
    history: Vec<Value>,
    reads: usize,
}

impl Runtime {
    fn new() -> Self {
        Self {
            plan: Plan::new(),
            history: vec![],
            reads: 0,
        }
    }

    fn model_input(&self) -> ModelInput {
        ModelInput {
            goal: self.plan.goal.clone(),
            plan: self.plan.clone(),
            history: self.history.clone(),
        }
    }
    // endregion messages

    // region dispatch
    fn execute(&mut self, call: &Call, root: &Path) -> ToolResult {
        let operation = || -> Result<Value, &'static str> {
            match call.tool.as_str() {
                "todo_read" => {
                    #[derive(Deserialize)]
                    #[serde(deny_unknown_fields)]
                    struct EmptyArgs {}
                    let _: EmptyArgs =
                        serde_json::from_str(&call.arguments).map_err(|_| "invalid_arguments")?;
                    Ok(json!(self.plan))
                }
                "todo_write" => {
                    let args: WriteArgs =
                        serde_json::from_str(&call.arguments).map_err(|_| "invalid_arguments")?;
                    self.plan.write(args)?;
                    Ok(json!(self.plan))
                }
                "read_file" => {
                    #[derive(Deserialize)]
                    #[serde(deny_unknown_fields)]
                    struct ReadArgs {
                        path: String,
                    }
                    let args: ReadArgs =
                        serde_json::from_str(&call.arguments).map_err(|_| "invalid_arguments")?;
                    if args.path != "README.md" {
                        return Err("permission_denied");
                    }
                    let content =
                        fs::read_to_string(root.join("README.md")).map_err(|_| "read_error")?;
                    self.reads += 1;
                    Ok(json!({"content": content}))
                }
                "write_file" => Err("permission_denied"),
                _ => Err("unknown_tool"),
            }
        }();
        let result = match operation {
            Ok(data) => ToolResult {
                call_id: call.call_id.clone(),
                ok: true,
                code: "ok".into(),
                data,
            },
            Err(code) => ToolResult {
                call_id: call.call_id.clone(),
                ok: false,
                code: code.into(),
                data: Value::Null,
            },
        };
        self.history
            .push(json!({"role": "assistant", "call": call}));
        self.history.push(json!({"role": "tool", "result": result}));
        result
    }
    // endregion dispatch
}

fn initial_items() -> Vec<Item> {
    [
        ("read", "读取 README"),
        ("summarize", "整理启动说明"),
        ("check", "核对说明与原文"),
    ]
    .into_iter()
    .map(|(id, content)| Item {
        id: id.into(),
        content: content.into(),
        status: Status::Pending,
    })
    .collect()
}

fn write_call(id: &str, plan: &Plan, items: Vec<Item>) -> Call {
    Call {
        call_id: id.into(),
        tool: "todo_write".into(),
        arguments: json!({"expected_revision": plan.revision, "items": items}).to_string(),
    }
}

// region scripted-model
enum Reply {
    Tool(Call),
    Answer(String),
}

fn scripted_model(input: &ModelInput, turn: usize, claims_only: bool) -> Reply {
    let mut items = input.plan.items.clone();
    let call_id = format!("call-{turn}");
    match turn {
        1 => items = initial_items(),
        2 => items[0].status = Status::InProgress,
        3 => {
            return Reply::Tool(Call {
                call_id,
                tool: if claims_only {
                    "todo_read"
                } else {
                    "read_file"
                }
                .into(),
                arguments: if claims_only {
                    json!({})
                } else {
                    json!({"path": "README.md"})
                }
                .to_string(),
            });
        }
        4 => {
            items[0].status = Status::Completed;
            items[1].status = Status::InProgress;
        }
        5 => {
            items[1].status = Status::Completed;
            items[2].status = Status::InProgress;
        }
        6 => items[2].status = Status::Completed,
        _ => {
            let content = input.history.iter().find_map(|message| {
                message
                    .pointer("/result/data/content")
                    .and_then(Value::as_str)
            });
            return Reply::Answer(content.map_or_else(
                || "清单已完成，但缺少 README 读取证据。".into(),
                |text| format!("启动说明：\n{text}"),
            ));
        }
    }
    Reply::Tool(write_call(&call_id, &input.plan, items))
}
// endregion scripted-model

#[derive(Serialize)]
struct RunReport {
    scenario: String,
    stop: String,
    model_turns: usize,
    tool_calls: usize,
    reads: usize,
    all_completed: bool,
    goal_verified: bool,
    answer: Option<String>,
    plan: Plan,
    inputs: Vec<ModelInput>,
    history: Vec<Value>,
}

// region loop
fn run(name: &str, root: &Path, budget: usize) -> RunReport {
    let mut runtime = Runtime::new();
    let mut inputs = vec![];
    let mut answer = None;
    let mut stop = "turn_limit";
    for turn in 1..=budget {
        let input = runtime.model_input();
        let reply = scripted_model(&input, turn, name == "claims-only");
        inputs.push(input);
        match reply {
            Reply::Tool(call) => {
                let result = runtime.execute(&call, root);
                if !result.ok {
                    stop = "tool_error";
                    break;
                }
            }
            Reply::Answer(text) => {
                answer = Some(text);
                stop = "answer";
                break;
            }
        }
    }
    let all_completed = !runtime.plan.items.is_empty()
        && runtime
            .plan
            .items
            .iter()
            .all(|item| item.status == Status::Completed);
    // This fixture's external acceptance condition is independent of the todo flags.
    let expected = fs::read_to_string(root.join("README.md")).ok();
    let goal_verified = runtime.reads == 1
        && expected
            .as_ref()
            .is_some_and(|text| answer.as_ref() == Some(&format!("启动说明：\n{text}")));
    RunReport {
        scenario: name.into(),
        stop: stop.into(),
        model_turns: inputs.len(),
        tool_calls: runtime.history.len() / 2,
        reads: runtime.reads,
        all_completed,
        goal_verified,
        answer,
        plan: runtime.plan,
        inputs,
        history: runtime.history,
    }
}
// endregion loop

fn run_scenario(name: &str) -> Value {
    let directory = tempfile::tempdir().expect("temporary fixture");
    let root = directory.path();
    if name != "read-error" {
        fs::write(root.join("README.md"), README).unwrap();
    }
    if matches!(
        name,
        "normal" | "claims-only" | "read-error" | "budget-stop"
    ) {
        let report = run(name, root, if name == "budget-stop" { 3 } else { 7 });
        match name {
            "normal" => {
                assert!(report.goal_verified);
                assert_eq!(report.plan.revision, 5);
            }
            "claims-only" => {
                assert!(report.all_completed);
                assert!(!report.goal_verified);
            }
            "read-error" => {
                assert_eq!(report.stop, "tool_error");
                assert_eq!(report.plan.revision, 2);
            }
            _ => {
                assert_eq!(report.stop, "turn_limit");
                assert!(report.answer.is_none());
            }
        }
        return json!(report);
    }
    let mut rt = Runtime::new();
    if name == "fresh-session" {
        let previous = run("normal", root, 7);
        assert_eq!(previous.plan.revision, 5);
        assert_eq!(rt.plan.revision, 0);
        return json!({"scenario": name, "previous_revision": previous.plan.revision, "plan": rt.plan});
    }
    assert!(
        rt.execute(&write_call("seed", &rt.plan, initial_items()), root)
            .ok
    );
    if matches!(name, "reopen-completed" | "yield-step") {
        let mut next = rt.plan.items.clone();
        next[0].status = Status::InProgress;
        assert!(rt.execute(&write_call("start", &rt.plan, next), root).ok);
    }
    if name == "reopen-completed" {
        let mut next = rt.plan.items.clone();
        next[0].status = Status::Completed;
        assert!(rt.execute(&write_call("complete", &rt.plan, next), root).ok);
    }
    let before = rt.plan.clone();
    let mut items = before.items.clone();
    let expected = match name {
        "two-active" => {
            items[0].status = Status::InProgress;
            items[1].status = Status::InProgress;
            "multiple_active"
        }
        "skip-completion" => {
            items[0].status = Status::Completed;
            "invalid_transition"
        }
        "duplicate-id" => {
            items[1].id = items[0].id.clone();
            "duplicate_id"
        }
        "empty-content" => {
            items[0].content = "  ".into();
            "invalid_content"
        }
        "too-many" => {
            for i in 3..9 {
                items.push(Item {
                    id: format!("extra-{i}"),
                    content: "新增步骤".into(),
                    status: Status::Pending,
                });
            }
            "item_count"
        }
        "remove-item" => {
            items.pop();
            "removed_item"
        }
        "changed-content" => {
            items[0].content = "悄悄换了目标".into();
            "content_changed"
        }
        "reopen-completed" => {
            items[0].status = Status::InProgress;
            "invalid_transition"
        }
        "append-step" => {
            items.push(Item {
                id: "verify-env".into(),
                content: "补查环境要求".into(),
                status: Status::Pending,
            });
            "ok"
        }
        "yield-step" => {
            items[0].status = Status::Pending;
            items[1].status = Status::InProgress;
            "ok"
        }
        "stale-revision" => "revision_conflict",
        "permission-denied" => "permission_denied",
        "invalid-json" | "unknown-field" | "unknown-status" => "invalid_arguments",
        _ => panic!("unknown scenario: {name}"),
    };
    let mut call = write_call("candidate", &rt.plan, items);
    match name {
        "stale-revision" => {
            let mut args: Value = serde_json::from_str(&call.arguments).unwrap();
            args["expected_revision"] = json!(0);
            call.arguments = args.to_string();
        }
        "unknown-status" | "unknown-field" => {
            let mut args: Value = serde_json::from_str(&call.arguments).unwrap();
            if name == "unknown-status" {
                args["items"][0]["status"] = json!("done");
            } else {
                args["force"] = json!(true);
            }
            call.arguments = args.to_string();
        }
        "invalid-json" => call.arguments = "{".into(),
        "permission-denied" => {
            // Even an explicit todo asking for a write cannot grant that permission.
            let mut next = rt.plan.items.clone();
            next.push(Item {
                id: "write".into(),
                content: "写入 summary.txt".into(),
                status: Status::Pending,
            });
            assert!(
                rt.execute(&write_call("add-write", &rt.plan, next), root)
                    .ok
            );
            call.tool = "write_file".into();
            call.arguments = json!({"path": "summary.txt", "content": "hello"}).to_string();
        }
        _ => {}
    }
    let before = if name == "permission-denied" {
        rt.plan.clone()
    } else {
        before
    };
    let result = rt.execute(&call, root);
    assert_eq!(result.code, expected);
    assert_eq!(result.call_id, call.call_id);
    let unchanged = rt.plan == before;
    assert_eq!(unchanged, !result.ok);
    assert!(!root.join("summary.txt").exists());
    assert_eq!(rt.model_input().plan, rt.plan);
    json!({"scenario": name, "expected_code": expected, "result": result,
        "unchanged": unchanged, "before": before, "after": rt.plan,
        "summary_exists": root.join("summary.txt").exists()})
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.first().map(String::as_str) == Some("--json") {
        let name = args.get(1).expect("usage: --json SCENARIO");
        assert!(CASES.contains(&name.as_str()), "unknown scenario");
        println!(
            "{}",
            serde_json::to_string_pretty(&run_scenario(name)).unwrap()
        );
    } else {
        for name in CASES {
            let result = run_scenario(name);
            if let Some(stop) = result.get("stop") {
                println!(
                    "{name}: stop={} turns={} calls={} revision={} reads={} completed={} goal_verified={}",
                    stop.as_str().unwrap(),
                    result["model_turns"],
                    result["tool_calls"],
                    result["plan"]["revision"],
                    result["reads"],
                    result["all_completed"],
                    result["goal_verified"]
                );
            } else if *name == "fresh-session" {
                println!(
                    "fresh-session: previous_revision={} new_revision={}",
                    result["previous_revision"], result["plan"]["revision"]
                );
            } else {
                println!(
                    "{name}: code={} unchanged={}",
                    result["result"]["code"].as_str().unwrap(),
                    result["unchanged"]
                );
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exhaustive_transition_matrix() {
        use Status::*;
        let states = [Pending, InProgress, Completed];
        let expected = [
            [true, true, false],
            [true, true, true],
            [false, false, true],
        ];
        for (i, from) in states.into_iter().enumerate() {
            for (j, to) in states.into_iter().enumerate() {
                assert_eq!(can_move(from, to), expected[i][j]);
            }
        }
    }

    #[test]
    fn reject_entire_batch_after_valid_first_change() {
        let mut plan = Plan::new();
        plan.write(WriteArgs {
            expected_revision: 0,
            items: initial_items(),
        })
        .unwrap();
        let before = plan.clone();
        let mut items = plan.items.clone();
        items[0].status = Status::InProgress;
        items[2].content = " ".into();
        assert_eq!(
            plan.write(WriteArgs {
                expected_revision: 1,
                items
            }),
            Err("invalid_content")
        );
        assert_eq!(plan, before);
    }

    #[test]
    fn all_scenario_contracts() {
        for name in CASES {
            run_scenario(name);
        }
    }

    #[test]
    fn latest_plan_and_history_reach_each_model_turn() {
        let directory = tempfile::tempdir().unwrap();
        fs::write(directory.path().join("README.md"), README).unwrap();
        let report = run("normal", directory.path(), 7);
        let revisions: Vec<_> = report
            .inputs
            .iter()
            .map(|input| input.plan.revision)
            .collect();
        assert_eq!(revisions, [0, 1, 2, 2, 3, 4, 5]);
        for (index, input) in report.inputs.iter().enumerate() {
            assert_eq!(input.history.len(), index * 2);
        }
        for pair in report.history.as_chunks::<2>().0 {
            assert_eq!(pair[0]["call"]["call_id"], pair[1]["result"]["call_id"]);
        }
    }

    #[test]
    fn answer_uses_changed_readme_not_a_canned_command() {
        let directory = tempfile::tempdir().unwrap();
        fs::write(directory.path().join("README.md"), "启动命令：just dev\n").unwrap();
        let report = run("normal", directory.path(), 7);
        assert!(report.goal_verified);
        assert_eq!(
            report.answer.as_deref(),
            Some("启动说明：\n启动命令：just dev\n")
        );
    }

    #[test]
    fn identifier_and_content_limits_are_checked() {
        for (id, content) in [
            ("UPPER".into(), "步骤".into()),
            ("x".repeat(25), "步骤".into()),
            ("ok".into(), "字".repeat(121)),
        ] {
            let mut plan = Plan::new();
            let items = vec![Item {
                id,
                content,
                status: Status::Pending,
            }];
            assert!(
                plan.write(WriteArgs {
                    expected_revision: 0,
                    items
                })
                .is_err()
            );
            assert_eq!(plan, Plan::new());
        }
        assert_eq!(
            Plan::new().write(WriteArgs {
                expected_revision: 0,
                items: vec![]
            }),
            Err("item_count")
        );
    }
}
