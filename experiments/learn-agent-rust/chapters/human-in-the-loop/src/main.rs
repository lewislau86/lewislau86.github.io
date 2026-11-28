//! D07（ADK-Rust 3.0）：人工介入与审批恢复。
//!
//!   cargo run --locked                         全部场景的摘要
//!   cargo run --locked -- edit                 某个场景的完整轨迹（场景名见 CASES）
//!   cargo run --locked -- disk DIR start "写 3.0 的升级说明并发布"   跨进程：每条命令是一个独立进程
//!   cargo run --locked -- disk DIR pending | approve | deny 理由 | edit 新内容 | resume | say 消息 | show
//!
//! 发布流程是一个 `SequentialAgent`：写作者（`LlmAgent`，output_key → report）→ 版本检查（`CustomAgent`）
//! → 发布者（`LlmAgent`，调用 publish_report）。应用策略要求发布先经人批准：调用被挂起，运行结束。
//! 会话和审批记录都存在 SQLite 文件里，下一个进程读出等待中的请求、记下决定，再恢复运行。
//! 模型是按规则回复的替身；发布写的是工作目录里的真实文件。
mod trace;

use std::{fs, path::Path, sync::Arc};

use adk_agent::{CustomAgent, LlmAgentBuilder, SequentialAgent};
use adk_core::{
    AdkError, Agent, ApprovalScope, ApprovalStore, Content, ErrorCategory, ErrorComponent, Event,
    FinishReason, InvocationContext, Llm, LlmRequest, LlmResponse, LlmResponseStream, Part,
    PolicyDecision, ToolApproval, ToolContext, ToolPolicy, ToolPolicyRequest,
};
use adk_runner::Runner;
use adk_session::{
    CreateRequest, GetRequest, SessionService, SqliteApprovalStore, SqliteSessionService,
};
use adk_tool::FunctionTool;
use async_trait::async_trait;
use futures::StreamExt;
use serde_json::{Value, json};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

const APP: &str = "d07";
const USER: &str = "editor";
const SESSION: &str = "release";

const CASES: &[&str] = &[
    "approve",
    "no-decision",
    "deny",
    "edit",
    "edit-forbidden",
    "clarify",
    "changed-mind",
    "changed-mind-revoked",
];

// region policy
/// 发布策略：只能发到 releases/ 下、内容不超过 400 字节，而且每次都要人批准。
/// 批准人改过的参数也会再过一遍这里。
#[derive(Debug)]
struct PublishPolicy;

#[async_trait]
impl ToolPolicy for PublishPolicy {
    async fn evaluate(&self, request: &ToolPolicyRequest) -> PolicyDecision {
        let target = request.args["target"].as_str().unwrap_or_default();
        let content = request.args["content"].as_str().unwrap_or_default();
        match request.tool_name.as_str() {
            "publish_report"
                if target.starts_with("releases/")
                    && !target.contains("..")
                    && content.len() <= 400 =>
            {
                PolicyDecision::require_approval("发布升级说明需要编辑批准")
            }
            _ => PolicyDecision::deny("publish_outside_policy"),
        }
    }
}
// endregion policy

// region tool
/// publish_report：把内容写进工作目录下的目标文件。能不能写由策略和审批决定。
fn publish_report(root: Arc<std::path::PathBuf>) -> FunctionTool {
    FunctionTool::new(
        "publish_report",
        "发布升级说明：target 是 releases/ 下的路径，content 是全文。",
        move |_ctx: Arc<dyn ToolContext>, args: Value| {
            let root = root.clone();
            async move {
                let target = root.join(args["target"].as_str().unwrap_or_default());
                let content = args["content"].as_str().unwrap_or_default();
                let written = target
                    .parent()
                    .map_or(Ok(()), fs::create_dir_all)
                    .and_then(|()| fs::write(&target, content));
                written.map_err(|e| {
                    AdkError::new(
                        ErrorComponent::Tool,
                        ErrorCategory::Unavailable,
                        "publish.write_failed",
                        e.to_string(),
                    )
                })?;
                Ok(json!({ "published": args["target"] }))
            }
        },
    )
}
// endregion tool

// region model
/// 替身模型：按系统消息里的“角色：xxx”扮演写作者或发布者。
struct ReleaseLlm;

fn texts(content: &Content) -> String {
    content.parts.iter().filter_map(Part::text).collect()
}

fn reply(part: Part) -> adk_core::Result<LlmResponseStream> {
    let mut response = LlmResponse::new(Content {
        role: "model".into(),
        parts: vec![part],
    });
    response.finish_reason = Some(FinishReason::Stop);
    response.turn_complete = true;
    Ok(Box::pin(futures::stream::iter([Ok(response)])))
}

fn text(t: impl Into<String>) -> Part {
    Part::Text { text: t.into() }
}

/// 用户消息里提到的目标版本（最后一次提到的为准）。
fn version_in(request: &LlmRequest) -> Option<String> {
    request
        .contents
        .iter()
        .filter(|c| c.role == "user")
        .map(texts)
        .filter_map(|t| {
            t.split(|c: char| !(c.is_ascii_digit() || c == '.'))
                .find(|w| w.starts_with("3.") && w.len() > 2)
                .map(str::to_owned)
        })
        .next_back()
}

#[async_trait]
impl Llm for ReleaseLlm {
    fn name(&self) -> &str {
        "release-llm"
    }

    async fn generate_content(
        &self,
        request: LlmRequest,
        _stream: bool,
    ) -> adk_core::Result<LlmResponseStream> {
        let system: String = request
            .contents
            .iter()
            .filter(|c| c.role == "system")
            .map(texts)
            .collect();
        if system.contains("角色：writer") {
            return reply(text(match version_in(&request) {
                Some(v) => format!("升级到 {v}：把 member 的启动命令改成 serve。"),
                None => "升级说明：把 member 的启动命令改成 serve（目标版本待确认）。".into(),
            }));
        }
        // 发布者：上一次发布调用的内容就是现在的稿子，就照那次的结果说话；
        // 稿子变了（或者还没提出过），就提出发布
        let report = system
            .split("待发布：")
            .nth(1)
            .and_then(|r| r.lines().next())
            .unwrap_or("")
            .trim()
            .to_owned();
        let parts: Vec<&Part> = request
            .contents
            .iter()
            .flat_map(|c| c.parts.iter())
            .collect();
        let last_call = parts.iter().rev().find_map(|p| match p {
            Part::FunctionCall { args, .. } => Some(args["content"].as_str().unwrap_or("")),
            _ => None,
        });
        let last_result = parts.iter().rev().find_map(|p| match p {
            Part::FunctionResponse {
                function_response, ..
            } => Some(function_response.response.clone()),
            _ => None,
        });
        match (last_call, last_result) {
            (Some(content), Some(r)) if content == report && r.get("published").is_some() => {
                reply(text(format!(
                    "已发布到 {}。",
                    r["published"].as_str().unwrap_or("?")
                )))
            }
            (Some(content), Some(r)) if content == report => reply(text(format!(
                "没有发布：{}",
                r["error"].as_str().unwrap_or("?")
            ))),
            _ => {
                let version = report
                    .split_whitespace()
                    .nth(1)
                    .filter(|v| v.starts_with("3."))
                    .map(|v| v.split('：').next().unwrap_or(v).to_owned())
                    .unwrap_or_else(|| "draft".into());
                reply(Part::FunctionCall {
                    name: "publish_report".into(),
                    args: json!({ "target": format!("releases/{version}.md"), "content": report }),
                    id: Some("publish".into()),
                    thought_signature: None,
                })
            }
        }
    }
}
// endregion model

// region workflow
/// 写作者 → 版本检查 → 发布者。版本检查发现稿子里没有确定的版本，就上报（escalate）停下，
/// 把问题交给人；发布者的调用被挂起时，整个工作流停在发布者这一步。
fn release_workflow(root: Arc<std::path::PathBuf>) -> Result<Arc<dyn Agent>> {
    let model = Arc::new(ReleaseLlm);
    let writer = LlmAgentBuilder::new("writer")
        .instruction("角色：writer 根据用户的要求写一句升级说明。")
        .model(model.clone())
        .output_key("report")
        .build()?;
    let check = CustomAgent::builder("version_check")
        .handler(|ctx: Arc<dyn InvocationContext>| async move {
            let report = ctx
                .session()
                .state()
                .get("report")
                .and_then(|v| v.as_str().map(str::to_owned))
                .unwrap_or_default();
            let mut event = Event::new(ctx.invocation_id());
            event.author = "version_check".into();
            if report.contains("待确认") {
                event.actions.escalate = true;
                event.llm_response.content =
                    Some(Content::new("model").with_text("请确认目标版本，确认后我重新写。"));
            }
            Ok(Box::pin(futures::stream::iter([Ok(event)])) as adk_core::EventStream)
        })
        .build()?;
    let publisher = LlmAgentBuilder::new("publisher")
        .instruction("角色：publisher 把待发布的升级说明发布出去。\n待发布：{report}")
        .model(model)
        .tool(Arc::new(publish_report(root)))
        .build()?;
    Ok(Arc::new(SequentialAgent::new(
        "release",
        vec![
            Arc::new(writer) as Arc<dyn Agent>,
            Arc::new(check),
            Arc::new(publisher),
        ],
    )))
}
// endregion workflow

// region stores
/// 每一步都像一个新进程：从目录里的 SQLite 文件重新打开会话与审批记录。
struct Desk {
    root: Arc<std::path::PathBuf>,
    sessions: Arc<SqliteSessionService>,
    approvals: Arc<SqliteApprovalStore>,
}

impl Desk {
    async fn open(dir: &Path) -> Result<Self> {
        let db = format!("sqlite:{}?mode=rwc", dir.join("d07.db").display());
        let sessions = Arc::new(SqliteSessionService::new(&db).await?);
        sessions.migrate().await?;
        let approvals = Arc::new(SqliteApprovalStore::new(&db).await?);
        approvals.migrate().await?;
        Ok(Self {
            root: Arc::new(dir.canonicalize()?),
            sessions,
            approvals,
        })
    }

    fn scope() -> ApprovalScope {
        ApprovalScope::new(APP, USER, SESSION)
    }

    /// 运行一次：空文本表示“只为恢复等待中的调用而运行”。
    async fn run(&self, message: &str, lines: &mut Vec<String>) -> Result<()> {
        let exists = self
            .sessions
            .get(GetRequest {
                app_name: APP.into(),
                user_id: USER.into(),
                session_id: SESSION.into(),
                num_recent_events: None,
                after: None,
            })
            .await
            .is_ok();
        if !exists {
            self.sessions
                .create(CreateRequest {
                    app_name: APP.into(),
                    user_id: USER.into(),
                    session_id: Some(SESSION.into()),
                    state: Default::default(),
                })
                .await?;
        }
        let runner = Runner::builder()
            .app_name(APP)
            .agent(release_workflow(self.root.clone())?)
            .session_service(self.sessions.clone())
            .tool_policy(Arc::new(PublishPolicy))
            .approval_store(self.approvals.clone())
            .without_intra_compaction()
            .build()?;
        let mut stream = runner
            .run_with_config(
                USER.try_into()?,
                SESSION.try_into()?,
                Content::new("user").with_text(message),
                None,
            )
            .await?;
        while let Some(event) = stream.next().await {
            let event = event?;
            lines.extend(
                trace::event_lines(&event)
                    .into_iter()
                    .filter(|l| !l.contains("] held ")),
            );
            if event.actions.escalate {
                lines.push(format!("[{}] escalate", event.author));
            }
        }
        Ok(())
    }

    async fn pending(&self) -> Result<Vec<adk_core::PendingApproval>> {
        Ok(self.approvals.pending(&Self::scope()).await?)
    }

    /// 审批人对第一条等待中的请求记下决定。应用另把指纹记进自己的决定日志，
    /// 以后需求变了，还能找到这条决定把它撤回。
    async fn decide(&self, approval: ToolApproval) -> Result<()> {
        let pending = self.pending().await?;
        let first = pending.first().ok_or("nothing is waiting for approval")?;
        self.approvals
            .decide(&Self::scope(), &first.fingerprint, approval)
            .await?;
        fs::write(self.root.join("last-decision.txt"), &first.fingerprint)?;
        Ok(())
    }

    /// 撤回：把还没用掉的批准改成拒绝（同一个指纹再记一次决定）。
    /// 先确认那次调用还挂着：发布者最后一条事件仍是“等待批准”。批准已经用掉时再记拒绝，
    /// 会变成一条预先的拒绝，以后同样的发布不问人就被拒。
    async fn revoke(&self, reason: &str) -> Result<()> {
        let session = self
            .sessions
            .get(GetRequest {
                app_name: APP.into(),
                user_id: USER.into(),
                session_id: SESSION.into(),
                num_recent_events: None,
                after: None,
            })
            .await?;
        let events = session.events();
        // 发布者最近一条工具结果是不是“等待批准”
        let still_held = (0..events.len())
            .rev()
            .filter_map(|i| events.at(i))
            .filter(|e| e.author == "publisher")
            .flat_map(|e| e.content().cloned().into_iter().flat_map(|c| c.parts))
            .find_map(|p| match p {
                Part::FunctionResponse {
                    function_response, ..
                } => Some(function_response.response["status"] == "confirmation_pending"),
                _ => None,
            })
            .unwrap_or(false);
        if !still_held {
            return Err("nothing is held: the approval was already used or never given".into());
        }
        let fingerprint = fs::read_to_string(self.root.join("last-decision.txt"))?;
        self.approvals
            .decide(
                &Self::scope(),
                &fingerprint,
                ToolApproval::deny().with_message(reason),
            )
            .await?;
        Ok(())
    }

    /// releases/ 下发布了哪些文件；内容被审批人改过的标上 (edited)。
    fn published(&self) -> Vec<String> {
        let mut files: Vec<String> = fs::read_dir(self.root.join("releases"))
            .into_iter()
            .flatten()
            .flatten()
            .map(|entry| {
                let name = entry.file_name().to_string_lossy().into_owned();
                let text = fs::read_to_string(entry.path()).unwrap_or_default();
                if text.contains("CI") {
                    format!("{name}(edited)")
                } else {
                    name
                }
            })
            .collect();
        files.sort();
        files
    }

    /// 会话里写作者回答了几次（每次回答都是写作者的一次运行）。
    async fn writer_runs(&self) -> Result<usize> {
        let session = self
            .sessions
            .get(GetRequest {
                app_name: APP.into(),
                user_id: USER.into(),
                session_id: SESSION.into(),
                num_recent_events: None,
                after: None,
            })
            .await?;
        let events = session.events();
        Ok((0..events.len())
            .filter_map(|i| events.at(i))
            .filter(|e| e.author == "writer" && e.content().is_some_and(|c| !texts(c).is_empty()))
            .count())
    }
}
// endregion stores

/// 一条命令 = 一步。`disk` 子命令里每一步是一个独立进程；场景里每一步重新打开存储。
async fn step(dir: &Path, command: &str, arg: &str, lines: &mut Vec<String>) -> Result<String> {
    let desk = Desk::open(dir).await?;
    lines.push(format!("--- {command} {arg}").trim_end().to_owned());
    let label = match command {
        "start" | "say" => {
            desk.run(arg, lines).await?;
            command.to_owned()
        }
        "resume" => {
            desk.run("", lines).await?;
            "resume".to_owned()
        }
        "approve" => {
            desk.decide(ToolApproval::approve()).await?;
            "approve".to_owned()
        }
        "deny" => {
            desk.decide(ToolApproval::deny().with_message(arg)).await?;
            "deny".to_owned()
        }
        "edit" => {
            // 批准，但把内容换成审批人改过的版本
            let first = desk.pending().await?;
            let mut args = first.first().ok_or("nothing pending")?.request.args.clone();
            args["content"] = json!(arg);
            desk.decide(ToolApproval::approve().with_edited_args(args))
                .await?;
            "edit".to_owned()
        }
        "edit-target" => {
            let first = desk.pending().await?;
            let mut args = first.first().ok_or("nothing pending")?.request.args.clone();
            args["target"] = json!(arg);
            desk.decide(ToolApproval::approve().with_edited_args(args))
                .await?;
            "edit-target".to_owned()
        }
        "revoke" => {
            desk.revoke(arg).await?;
            "revoke".to_owned()
        }
        "pending" | "show" => command.to_owned(),
        other => return Err(format!("unknown command {other}").into()),
    };
    let pending = desk.pending().await?;
    for p in &pending {
        lines.push(format!(
            "[pending] {} {}",
            p.request.tool_name, p.request.args
        ));
    }
    if command == "show" {
        for name in desk.published() {
            let text = fs::read_to_string(
                desk.root
                    .join("releases")
                    .join(name.trim_end_matches("(edited)")),
            )?;
            lines.push(format!(
                "[file] releases/{} {text}",
                name.trim_end_matches("(edited)")
            ));
        }
    }
    let suffix = if pending.is_empty() { "" } else { ":held" };
    Ok(format!("{label}{suffix}"))
}

fn script(scenario: &str) -> Vec<(&'static str, &'static str)> {
    let start = ("start", "写 3.0 的升级说明并发布");
    match scenario {
        "approve" => vec![start, ("approve", ""), ("resume", "")],
        "no-decision" => vec![start, ("resume", "")],
        "deny" => vec![start, ("deny", "目标版本写错了，先别发"), ("resume", "")],
        "edit" => vec![
            start,
            (
                "edit",
                "升级到 3.0：把 member 的启动命令改成 serve，并更新 CI 脚本。",
            ),
            ("resume", ""),
        ],
        "edit-forbidden" => vec![start, ("edit-target", "../outside.md"), ("resume", "")],
        "clarify" => vec![
            ("start", "写升级说明并发布"),
            ("say", "目标版本是 3.0"),
            ("approve", ""),
            ("resume", ""),
        ],
        // 批准以后、恢复之前，用户改了主意：发 3.1
        "changed-mind" => vec![start, ("approve", ""), ("say", "改成 3.1 再发")],
        // 同样改了主意，但应用先撤回旧批准、把挂起的那一步了结，再处理新要求
        "changed-mind-revoked" => vec![
            start,
            ("approve", ""),
            ("revoke", "需求变了：改发 3.1"),
            ("resume", ""),
            ("say", "改成 3.1 再发"),
            ("approve", ""),
            ("resume", ""),
        ],
        _ => vec![],
    }
}

async fn run(scenario: &str) -> Result<(Vec<String>, String)> {
    let dir = tempfile::tempdir()?;
    let mut lines = Vec::new();
    let mut labels = Vec::new();
    for (command, arg) in script(scenario) {
        labels.push(step(dir.path(), command, arg, &mut lines).await?);
    }
    let desk = Desk::open(dir.path()).await?;
    let published = desk.published();
    for name in &published {
        let file = name.trim_end_matches("(edited)");
        let text = fs::read_to_string(desk.root.join("releases").join(file))?;
        lines.push(format!("[file] releases/{file} {text}"));
    }
    let outside = dir.path().join("outside.md").exists()
        || dir
            .path()
            .parent()
            .is_some_and(|p| p.join("outside.md").exists());
    let summary = format!(
        "{scenario}: steps=[{}] writer_runs={} published=[{}] pending={}{}",
        labels.join(","),
        desk.writer_runs().await?,
        published.join(","),
        desk.pending().await?.len(),
        if outside { " outside=written" } else { "" },
    );
    lines.push(summary.clone());
    Ok((lines, summary))
}

async fn cli(args: &[String]) -> Result<()> {
    match args {
        [] => {
            for name in CASES {
                println!("{}", run(name).await?.1);
            }
            Ok(())
        }
        [name] if CASES.contains(&name.as_str()) => {
            for line in run(name).await?.0 {
                println!("{line}");
            }
            Ok(())
        }
        [disk, dir, command, rest @ ..] if disk == "disk" => {
            fs::create_dir_all(dir)?;
            let mut lines = Vec::new();
            let label = step(
                Path::new(dir),
                command,
                rest.first().map(String::as_str).unwrap_or(""),
                &mut lines,
            )
            .await?;
            for line in lines {
                println!("{line}");
            }
            println!("step: {label}");
            Ok(())
        }
        _ => Err(format!(
            "usage: human-in-the-loop [{}] | disk DIR start|say|pending|approve|deny|edit|edit-target|resume|show [ARG]",
            CASES.join("|")
        )
        .into()),
    }
}

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if let Err(error) = cli(&args).await {
        eprintln!("{error}");
        std::process::exit(2);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    async fn summary(name: &str) -> String {
        run(name).await.unwrap().1
    }

    #[tokio::test]
    async fn a_held_call_survives_reopening_the_stores_and_resumes_in_place() {
        let approve = summary("approve").await;
        assert!(
            approve.ends_with("writer_runs=1 published=[3.0.md] pending=0"),
            "{approve}"
        );
        assert!(summary("no-decision").await.ends_with("pending=1"));
    }

    #[tokio::test]
    async fn denials_and_edited_arguments_follow_the_policy() {
        assert!(summary("deny").await.contains("published=[]"));
        assert!(summary("edit").await.contains("published=[3.0.md(edited)]"));
        assert!(summary("edit-forbidden").await.contains("published=[]"));
    }

    #[tokio::test]
    async fn a_clarification_restarts_the_workflow_but_an_approval_does_not() {
        assert!(
            summary("clarify")
                .await
                .contains("steps=[start,say:held,approve,resume] writer_runs=2")
        );
    }

    #[tokio::test]
    async fn an_unused_approval_must_be_revoked_when_the_request_changes() {
        assert!(
            summary("changed-mind")
                .await
                .contains("writer_runs=1 published=[3.0.md]")
        );
        assert!(
            summary("changed-mind-revoked")
                .await
                .contains("writer_runs=2 published=[3.1.md]")
        );
    }
}
