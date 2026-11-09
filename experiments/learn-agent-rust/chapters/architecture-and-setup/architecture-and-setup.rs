//! R00: a deterministic wiring experiment, using only the Rust standard library.
//! rustc --edition=2024 architecture-and-setup.rs -o agent-r00
//! ./agent-r00 [--deny | --missing-file]
use std::{env, error::Error, fs, io, path::PathBuf, time::SystemTime};

const QUESTION: &str = "读取 README.md，告诉我如何启动项目。";
const README: &str = "# 课程练习项目\n启动命令：cargo run\n";

// region messages
struct Message {
    role: &'static str,
    content: String,
    call_id: Option<&'static str>,
}

struct ToolCall {
    id: &'static str,
    name: &'static str,
    path: &'static str,
}

#[derive(Default)]
struct RunState {
    messages: Vec<Message>,
    model_turns: usize,
    read_attempts: usize,
    read_successes: usize,
}
// endregion messages

// region model
// These fixed rules stand in for model responses. They do not call an LLM.
fn scripted_request(messages: &[Message]) -> ToolCall {
    let user = messages.last().expect("a user message is required");
    assert_eq!(user.role, "user");
    assert!(user.content.contains("README.md"));
    ToolCall {
        id: "read-1",
        name: "read_file",
        path: "README.md",
    }
}

fn scripted_answer(messages: &[Message]) -> (String, bool) {
    let observation = messages.last().expect("a tool result is required");
    assert_eq!(observation.role, "tool");
    assert_eq!(observation.call_id, Some("read-1"));
    match observation
        .content
        .lines()
        .find_map(|line| line.strip_prefix("启动命令："))
    {
        Some(command) => (format!("README 里的启动命令是：{command}"), true),
        None => (format!("任务未完成：{}", observation.content), false),
    }
}
// endregion model

// region tool
fn execute_read(
    call: &ToolCall,
    workspace: &Workspace,
    allow_read: bool,
    state: &mut RunState,
) -> (String, &'static str) {
    // Only a freshly created, application-owned fixture is accessible here.
    // This is a teaching policy, not a general filesystem sandbox.
    if !allow_read || call.name != "read_file" || call.path != "README.md" {
        return ("应用策略拒绝读取 README.md".into(), "denied");
    }
    state.read_attempts += 1;
    match fs::read_to_string(workspace.0.join(call.path)) {
        Ok(text) => {
            state.read_successes += 1;
            (text, "read_ok")
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            ("练习目录中不存在 README.md".into(), "missing_file")
        }
        Err(error) => (format!("读取失败：{error}"), "read_error"),
    }
}
// endregion tool

// region wiring
fn run(workspace: &Workspace, allow_read: bool) -> (&'static str, RunState) {
    let mut state = RunState::default();
    state.messages.push(Message {
        role: "user",
        content: QUESTION.into(),
        call_id: None,
    });

    state.model_turns += 1;
    let call = scripted_request(&state.messages);
    state.messages.push(Message {
        role: "assistant",
        content: format!("{}(\"{}\")", call.name, call.path),
        call_id: Some(call.id),
    });

    let (observation, outcome) = execute_read(&call, workspace, allow_read, &mut state);
    state.messages.push(Message {
        role: "tool",
        content: observation,
        call_id: Some(call.id),
    });

    state.model_turns += 1;
    let (answer, answered) = scripted_answer(&state.messages);
    state.messages.push(Message {
        role: "assistant",
        content: answer,
        call_id: None,
    });
    let outcome = match (outcome, answered) {
        ("read_ok", true) => "completed",
        ("read_ok", false) => "incomplete",
        (error, _) => error,
    };
    (outcome, state)
}
// endregion wiring

// An owned temporary directory keeps the experiment independent of user files.
struct Workspace(PathBuf);

impl Workspace {
    fn create(missing_file: bool) -> Result<Self, Box<dyn Error>> {
        let stamp = SystemTime::now()
            .duration_since(SystemTime::UNIX_EPOCH)?
            .as_nanos();
        let path = env::temp_dir().join(format!("learn-agent-r00-{}-{stamp}", std::process::id()));
        fs::create_dir(&path)?;
        let workspace = Self(path);
        if !missing_file {
            fs::write(workspace.0.join("README.md"), README)?;
        }
        Ok(workspace)
    }
}

impl Drop for Workspace {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<String> = env::args().skip(1).collect();
    let mode = match args.as_slice() {
        [] => "normal",
        [arg] if arg == "--deny" => "deny",
        [arg] if arg == "--missing-file" => "missing_file",
        _ => {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "usage: agent-r00 [--deny | --missing-file]",
            )
            .into());
        }
    };
    let workspace = Workspace::create(mode == "missing_file")?;
    let (outcome, state) = run(&workspace, mode != "deny");
    println!("模式：{mode}；模型：固定规则的脚本模型");
    for (index, message) in state.messages.iter().enumerate() {
        let id = message
            .call_id
            .map(|id| format!(" call_id={id}"))
            .unwrap_or_default();
        println!(
            "消息 {} | {}{} | {}",
            index + 1,
            message.role,
            id,
            message.content.trim()
        );
    }
    println!(
        "统计：model_turns={} tool_requests=1 read_attempts={} read_successes={} messages={} outcome={outcome}",
        state.model_turns,
        state.read_attempts,
        state.read_successes,
        state.messages.len()
    );
    println!("状态：仅保存在当前进程内；本例没有写入检查点。");
    // Exit success means the demonstration ran; outcome reports task completion.
    Ok(())
}
