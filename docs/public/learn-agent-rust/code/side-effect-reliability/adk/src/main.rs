//! P02（ADK-Rust 3.0 部分）：把“创建工单”放进 Runner，看动作账本（ActionLedger）能管到哪里。
//!
//! 每次调用本程序是一个独立进程，状态都在 DIR 里：
//! - agent.sqlite：会话事件（SqliteSessionService）与动作账本（SqliteActionLedger）
//! - provider.jsonl：外部工单服务的“数据库”，每行一张工单；它按操作身份去重
//!
//! 用法：learn-agent-p02-adk DIR PHASE [--crash in-tool|after-tool] [--key call|business] [--ledger sqlite|memory]
//!   PHASE = first   模型请求创建工单（可以在工具里或工具之后注入进程退出）
//!           recover 只做恢复：用账本回答上次没有结果的调用，不执行任何工具
//!           retry   新一轮运行：模型再次请求创建同一张工单
//!           inspect 打印会话轨迹与工单
mod trace;

use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    sync::Arc,
};

use adk_agent::LlmAgentBuilder;
use adk_core::{ActionLedger, Content, InMemoryActionLedger, ToolContext};
use adk_model::{ScriptedLlm, ScriptedResponse};
use adk_runner::Runner;
use adk_session::{
    CreateRequest, GetRequest, SessionService, SqliteActionLedger, SqliteSessionService,
};
use adk_tool::FunctionTool;
use futures::StreamExt;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

const APP: &str = "p02";
const USER: &str = "reader";
const SESSION: &str = "review-42";

struct Options {
    dir: PathBuf,
    phase: String,
    crash: Option<String>,
    business_key: bool,
    durable_ledger: bool,
}

// region provider
/// 外部工单服务的替身：按操作身份去重，同一身份第二次到达时返回已有工单，不再新建。
/// 简化：单进程顺序访问，先读后追加不是原子操作，同身份不同内容也不报冲突；
/// 真实服务要像第 4 节那样在一个事务里完成“查重 + 创建”，并拒绝同键不同参数。
fn apply_ticket(dir: &Path, operation: &str, title: &str) -> Value {
    // 每次到达都记一笔，用来区分“服务被调用了几次”和“建了几张工单”
    let mut attempts = OpenOptions::new()
        .create(true)
        .append(true)
        .open(dir.join("provider-attempts.log"))
        .expect("provider attempts");
    writeln!(attempts, "{operation}").expect("write attempt");
    attempts.sync_all().expect("fsync attempts");
    let path = dir.join("provider.jsonl");
    let existing = fs::read_to_string(&path).unwrap_or_default();
    for line in existing.lines() {
        let row: Value = serde_json::from_str(line).expect("provider row");
        if row["operation"] == operation {
            return json!({ "ticket": row["ticket"], "deduplicated": true });
        }
    }
    let ticket = format!("T-{}", existing.lines().count() + 1);
    let row = json!({ "ticket": ticket, "operation": operation, "title": title });
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .expect("provider");
    writeln!(file, "{row}").expect("write provider row");
    file.sync_all().expect("fsync provider");
    json!({ "ticket": ticket, "deduplicated": false })
}
// endregion provider

// region tool
/// 业务身份（演示用的简化）：同一会话里“为这个标题创建工单”算同一件事，跨运行、跨进程不变。
/// 代价：同一会话里两张同名工单会被合并，换个说法的标题又不会去重。第 3、5 节的做法更可靠：
/// 创建意图时生成操作 ID 并和意图一起保存（例如写进会话状态），工具读取它。
fn business_operation(scope: &str, title: &str) -> String {
    let digest = Sha256::digest(format!("{scope}|create_ticket|{title}"));
    format!("biz-{digest:x}")[..20].to_string()
}

/// 创建工单的工具。没有声明 ToolEffect，框架按“非幂等”对待：只执行一次、不重试，
/// 执行前后在动作账本里记录开始与结果。
fn create_ticket_tool(dir: PathBuf, crash: Option<String>, business_key: bool) -> FunctionTool {
    let handler = move |ctx: Arc<dyn ToolContext>, args: Value| {
        let (dir, crash) = (dir.clone(), crash.clone());
        async move {
            let title = args["title"].as_str().unwrap_or_default().to_string();
            // 操作身份：框架给的幂等键按“这一次调用”生成；业务身份按“这件事”生成
            let operation = if business_key {
                let scope = format!("{}/{}/{}", ctx.app_name(), ctx.user_id(), ctx.session_id());
                business_operation(&scope, &title)
            } else {
                ctx.idempotency_key()
            };
            let receipt = apply_ticket(&dir, &operation, &title);
            if crash.as_deref() == Some("in-tool") {
                // 外部工单已经写入，结果还没交回框架：进程在这里消失
                eprintln!("injected_exit=in-tool");
                std::process::exit(9);
            }
            Ok(receipt)
        }
    };
    FunctionTool::new("create_ticket", "在外部工单系统创建一张工单。", handler)
}
// endregion tool

fn script(phase: &str) -> Vec<ScriptedResponse> {
    let create = || {
        ScriptedResponse::function_call("create_ticket", json!({ "title": "审查 Rust 超时处理" }))
    };
    match phase {
        "first" => vec![create(), ScriptedResponse::text("工单已创建。")],
        "retry" => vec![create(), ScriptedResponse::text("工单已再次提交。")],
        _ => vec![],
    }
}

fn get_request() -> GetRequest {
    GetRequest {
        app_name: APP.into(),
        user_id: USER.into(),
        session_id: SESSION.into(),
        num_recent_events: None,
        after: None,
    }
}

// region runner
async fn runner(o: &Options) -> Result<(Runner, Arc<SqliteSessionService>)> {
    let url = format!("sqlite:{}?mode=rwc", o.dir.join("agent.sqlite").display());
    let sessions = Arc::new(SqliteSessionService::new(&url).await?);
    sessions.migrate().await?;
    if sessions.get(get_request()).await.is_err() {
        sessions
            .create(CreateRequest {
                app_name: APP.into(),
                user_id: USER.into(),
                session_id: Some(SESSION.into()),
                state: Default::default(),
            })
            .await?;
    }
    // 账本放在同一个 SQLite 文件里；memory 模式用于对照：进程退出后记录随之消失
    let ledger: Arc<dyn ActionLedger> = if o.durable_ledger {
        let ledger = SqliteActionLedger::new(&url).await?;
        ledger.migrate().await?;
        Arc::new(ledger)
    } else {
        Arc::new(InMemoryActionLedger::new())
    };
    let mut agent = LlmAgentBuilder::new("assistant")
        .instruction("需要时调用 create_ticket 创建工单。")
        .model(Arc::new(ScriptedLlm::new("scripted", script(&o.phase))))
        .tool(Arc::new(create_ticket_tool(
            o.dir.clone(),
            o.crash.clone(),
            o.business_key,
        )));
    if o.crash.as_deref() == Some("after-tool") {
        // 工具已返回、账本已记下结果，但这条结果还没写进会话：进程在这里消失
        agent = agent.after_tool_callback(Box::new(|_ctx| {
            Box::pin(async move {
                eprintln!("injected_exit=after-tool");
                std::process::exit(9)
            })
        }));
    }
    let runner = Runner::builder()
        .app_name(APP)
        .agent(Arc::new(agent.build()?))
        .session_service(sessions.clone())
        .action_ledger(ledger)
        .without_intra_compaction()
        .build()?;
    Ok((runner, sessions))
}
// endregion runner

fn parse() -> Result<Options> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let [dir, phase, rest @ ..] = args.as_slice() else {
        return Err("usage: DIR PHASE [--crash in-tool|after-tool] [--key call|business] [--ledger sqlite|memory]".into());
    };
    let mut o = Options {
        dir: PathBuf::from(dir),
        phase: phase.clone(),
        crash: None,
        business_key: false,
        durable_ledger: true,
    };
    for pair in rest.chunks(2) {
        match (pair[0].as_str(), pair.get(1).map(String::as_str)) {
            ("--crash", Some(v @ ("in-tool" | "after-tool"))) => o.crash = Some(v.into()),
            ("--key", Some(v @ ("call" | "business"))) => o.business_key = v == "business",
            ("--ledger", Some(v @ ("sqlite" | "memory"))) => o.durable_ledger = v == "sqlite",
            _ => return Err(format!("bad option {pair:?}").into()),
        }
    }
    Ok(o)
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    let o = parse()?;
    fs::create_dir_all(&o.dir)?;
    let (runner, sessions) = runner(&o).await?;
    // region phases
    match o.phase.as_str() {
        "recover" => {
            let answered = runner.recover_unanswered_calls(USER, SESSION).await?;
            println!("recovered_calls={answered}");
        }
        "first" | "retry" => {
            let input = Content::new("user").with_text("请创建工单：审查 Rust 超时处理。");
            let mut stream = runner.run_str(USER, SESSION, input).await?;
            while let Some(event) = stream.next().await {
                for line in trace::event_lines(&event?) {
                    println!("{line}");
                }
            }
        }
        "inspect" => {
            let session = sessions.get(get_request()).await?;
            for event in session.events().all() {
                for line in trace::event_lines(&event) {
                    println!("{line}");
                }
            }
            let attempts =
                fs::read_to_string(o.dir.join("provider-attempts.log")).unwrap_or_default();
            let rows = fs::read_to_string(o.dir.join("provider.jsonl")).unwrap_or_default();
            println!("provider_attempts={}", attempts.lines().count());
            println!("provider_tickets={}", rows.lines().count());
        }
        other => return Err(format!("unknown phase {other}").into()),
    }
    // endregion phases
    runner.close().await;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn provider_deduplicates_by_operation() {
        let dir = std::env::temp_dir().join(format!("p02-adk-test-{}", std::process::id()));
        fs::create_dir_all(&dir).unwrap();
        let first = apply_ticket(&dir, "op-1", "a");
        let again = apply_ticket(&dir, "op-1", "a");
        let other = apply_ticket(&dir, "op-2", "a");
        assert_eq!(first, json!({ "ticket": "T-1", "deduplicated": false }));
        assert_eq!(again, json!({ "ticket": "T-1", "deduplicated": true }));
        assert_eq!(other["ticket"], "T-2");
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn business_identity_is_stable_and_specific() {
        assert_eq!(business_operation("s", "a"), business_operation("s", "a"));
        assert_ne!(business_operation("s", "a"), business_operation("s", "b"));
        assert_ne!(business_operation("s", "a"), business_operation("t", "a"));
    }
}
