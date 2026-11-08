//! R01: an explicit Agent loop with a scripted model and a real file read.
//! rustc --edition=2024 agent-loop.rs -o agent-r01
//! ./agent-r01 --help
use std::{collections::HashSet, env, error::Error, fs, io, path::PathBuf};

const QUESTION: &str = "读取 README.md，告诉我如何启动项目。";

// region messages
#[derive(Clone, Debug)]
struct ToolCall {
    id: String,
    name: String,
    path: String,
}

#[derive(Clone, Debug)]
struct ToolResult {
    call_id: String,
    output: Result<String, String>,
}

#[derive(Clone, Debug)]
enum ModelReply {
    ToolCalls(Vec<ToolCall>),
    Final(String),
}

#[derive(Debug)]
enum Message {
    User(String),
    Assistant(ModelReply),
    Tool(ToolResult),
}
// endregion messages

// region state
#[derive(Clone, Copy)]
struct Limits {
    model_turns: usize,
    tool_calls: usize,
}

#[derive(Debug, PartialEq)]
enum StopReason {
    FinalAnswer,
    ModelBudget,
    ToolBudget,
    InvalidCall,
    ModelError,
}

struct Run {
    messages: Vec<Message>,
    model_turns: usize,
    tool_calls: usize,
    read_attempts: usize,
    read_successes: usize,
    stop: StopReason,
    detail: String,
}
// endregion state

// region model
trait Model {
    fn respond(&mut self, messages: &[Message]) -> Result<ModelReply, String>;
}

struct ScriptedModel {
    scenario: String,
    next_id: usize,
}

impl Model for ScriptedModel {
    fn respond(&mut self, messages: &[Message]) -> Result<ModelReply, String> {
        // Fixed rules exercise the runtime. No LLM, HTTP or natural-language reasoning.
        let first_turn = matches!(messages.last(), Some(Message::User(_)));
        if first_turn || self.scenario == "repeat" || self.scenario == "duplicate-id" {
            self.next_id += 1;
            let id = if self.scenario == "duplicate-id" {
                1
            } else {
                self.next_id
            };
            let call = ToolCall {
                id: format!("read-{id}"),
                name: if self.scenario == "unknown-tool" {
                    "shell"
                } else {
                    "read_file"
                }
                .into(),
                path: if self.scenario == "invalid-path" {
                    "../README.md"
                } else {
                    "README.md"
                }
                .into(),
            };
            let mut calls = vec![call];
            if self.scenario == "two-tools" {
                calls.push(ToolCall {
                    id: "read-2".into(),
                    ..calls[0].clone()
                });
            }
            return Ok(ModelReply::ToolCalls(calls));
        }
        let Some(Message::Tool(result)) = messages.last() else {
            return Err("脚本模型需要 user 消息或 tool 结果".into());
        };
        let answer = match &result.output {
            Ok(content) => match content
                .lines()
                .find_map(|line| line.strip_prefix("启动命令："))
            {
                Some(command) => format!("README 里的启动命令是：{command}"),
                None => "任务未完成：README 中没有启动命令".into(),
            },
            Err(error) => format!("任务未完成：{error}"),
        };
        Ok(ModelReply::Final(answer))
    }
}
// endregion model

// region tool
fn execute(call: &ToolCall, workspace: &Workspace, run: &mut Run) -> ToolResult {
    // Count every dispatch, including rejected names/paths and failed reads.
    run.tool_calls += 1;
    let output = if call.name != "read_file" {
        Err("unknown_tool：只提供 read_file".into())
    } else if call.path != "README.md" {
        Err("invalid_path：只允许练习目录的 README.md".into())
    } else {
        run.read_attempts += 1;
        match fs::read_to_string(workspace.0.join(&call.path)) {
            Ok(content) => {
                run.read_successes += 1;
                Ok(content)
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                Err("missing_file：练习目录中没有 README.md".into())
            }
            Err(error) => Err(format!("read_error：{error}")),
        }
    };
    ToolResult {
        call_id: call.id.clone(),
        output,
    }
}
// endregion tool

// region validation
fn validate_calls(calls: &[ToolCall], seen: &HashSet<String>) -> Result<(), String> {
    if calls.is_empty() {
        return Err("工具请求列表为空".into());
    }
    let mut batch = HashSet::new();
    for call in calls {
        if call.id.is_empty() || seen.contains(&call.id) || !batch.insert(&call.id) {
            return Err(format!("调用 ID 为空或重复：{}", call.id));
        }
    }
    Ok(())
}
// endregion validation

// region agent-loop
fn run_agent(model: &mut impl Model, workspace: &Workspace, limits: Limits) -> Run {
    let mut run = Run {
        messages: vec![Message::User(QUESTION.into())],
        model_turns: 0,
        tool_calls: 0,
        read_attempts: 0,
        read_successes: 0,
        stop: StopReason::ModelBudget,
        detail: String::new(),
    };
    let mut seen = HashSet::new();
    loop {
        if run.model_turns >= limits.model_turns {
            run.stop = StopReason::ModelBudget;
            run.detail = "下一次模型调用前停止".into();
            return run;
        }
        run.model_turns += 1;
        let reply = match model.respond(&run.messages) {
            Ok(reply) => reply,
            Err(error) => {
                run.stop = StopReason::ModelError;
                run.detail = error;
                return run;
            }
        };
        run.messages.push(Message::Assistant(reply.clone()));
        match reply {
            ModelReply::Final(_) => {
                run.stop = StopReason::FinalAnswer;
                return run;
            }
            ModelReply::ToolCalls(calls) => {
                if let Err(error) = validate_calls(&calls, &seen) {
                    // Keep the malformed response for diagnosis; never send it back to a model.
                    run.stop = StopReason::InvalidCall;
                    run.detail = error;
                    return run;
                }
                seen.extend(calls.iter().map(|call| call.id.clone()));
                // Admission applies to the whole batch: no partial tool execution.
                if calls.len() > limits.tool_calls.saturating_sub(run.tool_calls) {
                    for call in calls {
                        run.messages.push(Message::Tool(ToolResult {
                            call_id: call.id,
                            output: Err("tool_budget：应用拒绝执行整批工具".into()),
                        }));
                    }
                    run.stop = StopReason::ToolBudget;
                    run.detail = "整批工具超出剩余预算，执行次数未增加".into();
                    return run;
                }
                for call in calls {
                    let result = execute(&call, workspace, &mut run);
                    run.messages.push(Message::Tool(result));
                }
            }
        }
    }
}
// endregion agent-loop

// region workspace
struct Workspace(PathBuf);

impl Workspace {
    fn create(scenario: &str) -> Result<Self, Box<dyn Error>> {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let sequence = NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_nanos();
        let path = env::temp_dir().join(format!(
            "learn-agent-r01-{}-{stamp}-{sequence}",
            std::process::id()
        ));
        fs::create_dir(&path)?;
        let workspace = Self(path);
        if scenario != "missing-file" {
            let command = if scenario == "changed-readme" {
                "cargo run --release"
            } else {
                "cargo run"
            };
            fs::write(
                workspace.0.join("README.md"),
                format!("# 课程练习项目\n启动命令：{command}\n"),
            )?;
        }
        Ok(workspace)
    }
}

impl Drop for Workspace {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
// endregion workspace

fn print_run(run: &Run, scenario: &str, limits: Limits) {
    println!("场景：{scenario}；模型：固定规则的脚本模型");
    println!(
        "预算：model_turns={} tool_calls={}",
        limits.model_turns, limits.tool_calls
    );
    for (index, message) in run.messages.iter().enumerate() {
        let prefix = format!("消息 {}", index + 1);
        match message {
            Message::User(content) => println!("{prefix} | user | {content}"),
            Message::Assistant(ModelReply::ToolCalls(calls)) => {
                for call in calls {
                    println!(
                        "{prefix} | assistant | call_id={} {}(path={:?})",
                        call.id, call.name, call.path
                    );
                }
            }
            Message::Assistant(ModelReply::Final(answer)) => {
                println!("{prefix} | assistant | {answer}")
            }
            Message::Tool(result) => {
                let (status, content) = match &result.output {
                    Ok(content) => ("ok", content.trim().replace('\n', " / ")),
                    Err(error) => ("error", error.clone()),
                };
                println!(
                    "{prefix} | tool | call_id={} status={status} | {content}",
                    result.call_id
                );
            }
        }
    }
    // A task-specific fixture assertion, independent of the protocol stop reason.
    let command = if scenario == "changed-readme" {
        "cargo run --release"
    } else {
        "cargo run"
    };
    let expected = format!("README 里的启动命令是：{command}");
    let goal_met = run.read_successes > 0
        && matches!(run.messages.last(), Some(Message::Assistant(ModelReply::Final(answer))) if answer == &expected);
    println!(
        "统计：model_turns={} tool_calls={} read_attempts={} read_successes={} messages={}",
        run.model_turns,
        run.tool_calls,
        run.read_attempts,
        run.read_successes,
        run.messages.len()
    );
    println!("停止：{:?}；fixture_goal_met={goal_met}", run.stop);
    if !run.detail.is_empty() {
        println!("原因：{}", run.detail);
    }
}

fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<String> = env::args().skip(1).collect();
    let mut scenario = "normal".to_string();
    let mut limits = Limits {
        model_turns: 3,
        tool_calls: 2,
    };
    let usage = "usage: agent-r01 [--scenario normal|changed-readme|missing-file|repeat|two-tools|duplicate-id|unknown-tool|invalid-path] [--max-model-turns N] [--max-tool-calls N]";
    if args.as_slice() == ["--help"] {
        println!("{usage}");
        return Ok(());
    }
    for pair in args.chunks(2) {
        let [flag, value] = pair else {
            return Err(usage.into());
        };
        match flag.as_str() {
            "--scenario" => scenario = value.clone(),
            "--max-model-turns" => limits.model_turns = value.parse()?,
            "--max-tool-calls" => limits.tool_calls = value.parse()?,
            _ => return Err(usage.into()),
        }
    }
    if ![
        "normal",
        "changed-readme",
        "missing-file",
        "repeat",
        "two-tools",
        "duplicate-id",
        "unknown-tool",
        "invalid-path",
    ]
    .contains(&scenario.as_str())
    {
        return Err(usage.into());
    }
    let workspace = Workspace::create(&scenario)?;
    let mut model = ScriptedModel {
        scenario: scenario.clone(),
        next_id: 0,
    };
    let run = run_agent(&mut model, &workspace, limits);
    print_run(&run, &scenario, limits);
    // Exit 0 means the experiment ran. Stop reason and goal assertion report its outcome.
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    struct FixtureModel(Vec<ModelReply>);
    impl Model for FixtureModel {
        fn respond(&mut self, _: &[Message]) -> Result<ModelReply, String> {
            if self.0.is_empty() {
                Err("model_unavailable".into())
            } else {
                Ok(self.0.remove(0))
            }
        }
    }

    fn call(id: &str) -> ToolCall {
        ToolCall {
            id: id.into(),
            name: "read_file".into(),
            path: "README.md".into(),
        }
    }

    #[test]
    fn zero_model_budget_makes_no_call() {
        let workspace = Workspace::create("normal").unwrap();
        let run = run_agent(
            &mut FixtureModel(vec![]),
            &workspace,
            Limits {
                model_turns: 0,
                tool_calls: 2,
            },
        );
        assert_eq!(run.stop, StopReason::ModelBudget);
        assert_eq!(
            (run.model_turns, run.tool_calls, run.messages.len()),
            (0, 0, 1)
        );
    }

    #[test]
    fn a_batch_cannot_partly_consume_the_tool_budget() {
        let workspace = Workspace::create("normal").unwrap();
        let mut model = FixtureModel(vec![ModelReply::ToolCalls(vec![call("a"), call("b")])]);
        let run = run_agent(
            &mut model,
            &workspace,
            Limits {
                model_turns: 2,
                tool_calls: 1,
            },
        );
        assert_eq!(run.stop, StopReason::ToolBudget);
        assert_eq!((run.tool_calls, run.read_attempts), (0, 0));
        for (index, id) in ["a", "b"].into_iter().enumerate() {
            assert!(
                matches!(&run.messages[index + 2], Message::Tool(r) if r.call_id == id && r.output.is_err())
            );
        }
    }

    #[test]
    fn duplicate_or_empty_ids_are_rejected_before_any_read() {
        let workspace = Workspace::create("normal").unwrap();
        for calls in [vec![call("a"), call("a")], vec![call("")], vec![]] {
            let mut model = FixtureModel(vec![ModelReply::ToolCalls(calls)]);
            let run = run_agent(
                &mut model,
                &workspace,
                Limits {
                    model_turns: 2,
                    tool_calls: 2,
                },
            );
            assert_eq!(run.stop, StopReason::InvalidCall);
            assert_eq!(run.read_attempts, 0);
        }
    }

    #[test]
    fn reused_id_in_a_later_turn_is_not_executed() {
        let workspace = Workspace::create("normal").unwrap();
        let mut model = FixtureModel(vec![
            ModelReply::ToolCalls(vec![call("a")]),
            ModelReply::ToolCalls(vec![call("a")]),
        ]);
        let run = run_agent(
            &mut model,
            &workspace,
            Limits {
                model_turns: 3,
                tool_calls: 3,
            },
        );
        assert_eq!(run.stop, StopReason::InvalidCall);
        assert_eq!(run.read_attempts, 1);
    }

    #[test]
    fn an_early_final_answer_does_not_trigger_a_read() {
        let workspace = Workspace::create("normal").unwrap();
        let mut model = FixtureModel(vec![ModelReply::Final("我猜是 cargo run".into())]);
        let run = run_agent(
            &mut model,
            &workspace,
            Limits {
                model_turns: 3,
                tool_calls: 2,
            },
        );
        assert_eq!(run.stop, StopReason::FinalAnswer);
        assert_eq!(run.read_successes, 0);
    }

    #[test]
    fn model_failure_consumes_a_turn_and_stops_without_tools() {
        let workspace = Workspace::create("normal").unwrap();
        let run = run_agent(
            &mut FixtureModel(vec![]),
            &workspace,
            Limits {
                model_turns: 3,
                tool_calls: 2,
            },
        );
        assert_eq!(run.stop, StopReason::ModelError);
        assert_eq!((run.model_turns, run.tool_calls), (1, 0));
    }
}
