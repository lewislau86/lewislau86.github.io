//! D08（ADK-Rust 3.0）：模式组合与选型实战。
//!
//!   cargo run --locked                 全部场景的摘要
//!   cargo run --locked -- naive        某个场景的完整轨迹（场景名见 CASES）
//!   cargo run --locked -- live         换成 OpenAI 兼容服务跑一遍组合流程（读 OPENAI_BASE_URL、OPENAI_MODEL、OPENAI_API_KEY）
//!
//! 升级发布流程把前面几章的模式串起来：
//!   checks（ParallelAgent，第 18 章）→ merge（CustomAgent 核对成员与修订）
//!   → refine（LoopAgent：写作者 + 评估者，第 21 章）→ publisher（发布要人批准，第 22 章）
//! 外层是一个 SequentialAgent，整次运行共用一个预算（RunBudget）。
//! 默认模型是按规则回复的替身；live 子命令把同一个流程交给真实服务。
mod trace;

use std::{
    fs,
    path::PathBuf,
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, Ordering},
    },
};

use adk_agent::{CustomAgent, LlmAgentBuilder, LoopAgent, ParallelAgent, SequentialAgent};
use adk_core::{
    AdkError, Agent, ApprovalScope, ApprovalStore, Content, ErrorCategory, ErrorComponent, Event,
    FinishReason, InMemoryApprovalStore, InvocationContext, Llm, LlmRequest, LlmResponse,
    LlmResponseStream, Part, PolicyDecision, RunBudget, RunConfig, StreamingMode, ToolApproval,
    ToolContext, ToolPolicy, ToolPolicyRequest,
};
use adk_runner::Runner;
use adk_session::{CreateRequest, InMemorySessionService, SessionService};
use adk_tool::FunctionTool;
use async_trait::async_trait;
use futures::StreamExt;
use serde_json::{Value, json};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

const TASK: &str = "审查修订 r2 的升级，写一段带来源的升级说明并发布。";
const MEMBERS: [&str; 2] = ["deps", "docs"];

const CASES: &[&str] = &[
    "naive",
    "normal",
    "stale-branch",
    "branch-failed",
    "never-accepted",
    "budget",
    "budget-resume",
];

// region model
/// 替身模型：按系统消息里的“角色：xxx”扮演检查者、写作者或发布者。
struct RuleLlm {
    scenario: String,
    calls: Mutex<Vec<String>>,
}

fn texts(content: &Content) -> String {
    content.parts.iter().filter_map(Part::text).collect()
}

fn system_text(request: &LlmRequest) -> String {
    request
        .contents
        .iter()
        .filter(|c| c.role == "system")
        .map(texts)
        .collect::<Vec<_>>()
        .join("\n")
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

fn role_of(system: &str) -> String {
    system
        .split("角色：")
        .nth(1)
        .and_then(|t| t.split_whitespace().next())
        .unwrap_or("?")
        .to_owned()
}

impl RuleLlm {
    fn answer(&self, role: &str, system: &str, request: &LlmRequest) -> adk_core::Result<Part> {
        match role {
            "deps_checker" if self.scenario == "branch-failed" => Err(AdkError::new(
                ErrorComponent::Model,
                ErrorCategory::Unavailable,
                "model.unavailable",
                "rule-llm: 依赖检查服务没有响应",
            )),
            "deps_checker" | "docs_checker" => {
                let member = role.trim_end_matches("_checker");
                let revision = if self.scenario == "stale-branch" && member == "deps" {
                    "r1"
                } else {
                    "r2"
                };
                let finding = if member == "deps" {
                    "tokio 需要升到 1.40"
                } else {
                    "启动命令改成 serve"
                };
                Ok(Part::Text {
                    text: json!({ "member": member, "revision": revision, "finding": finding })
                        .to_string(),
                })
            }
            "writer" => {
                // 第一稿漏了来源；看到反馈后补上。never-accepted 一直引用没检查过的来源
                let revised = system.contains("\"failed\"");
                let sources: Vec<&str> = match (self.scenario.as_str(), revised) {
                    ("never-accepted", true) => vec!["blog"],
                    (_, true) => vec!["deps", "docs"],
                    (_, false) => vec![],
                };
                Ok(Part::Text {
                    text: json!({
                        "text": "升级到 3.0：tokio 升到 1.40，启动命令改成 serve。",
                        "sources": sources,
                    })
                    .to_string(),
                })
            }
            _ => {
                // 发布者：最后一条是工具结果就照结果说话，否则提出发布
                let last = request
                    .contents
                    .last()
                    .into_iter()
                    .flat_map(|c| c.parts.iter())
                    .find_map(|p| match p {
                        Part::FunctionResponse {
                            function_response, ..
                        } => Some(function_response.response.clone()),
                        _ => None,
                    });
                let draft = system
                    .split("定稿：")
                    .nth(1)
                    .and_then(|r| r.lines().next())
                    .and_then(|r| serde_json::from_str::<Value>(r.trim()).ok())
                    .unwrap_or(Value::Null);
                Ok(match last {
                    Some(r) if r.get("published").is_some() => Part::Text {
                        text: "已发布。".into(),
                    },
                    Some(r) => Part::Text {
                        text: format!("没有发布：{}", r["error"].as_str().unwrap_or("?")),
                    },
                    None => Part::FunctionCall {
                        name: "publish_report".into(),
                        args: json!({ "target": "releases/3.0.md", "content": draft["text"] }),
                        id: Some("publish".into()),
                        thought_signature: None,
                    },
                })
            }
        }
    }
}

#[async_trait]
impl Llm for RuleLlm {
    fn name(&self) -> &str {
        "rule-llm"
    }

    async fn generate_content(
        &self,
        request: LlmRequest,
        _stream: bool,
    ) -> adk_core::Result<LlmResponseStream> {
        let system = system_text(&request);
        let role = role_of(&system);
        self.calls.lock().unwrap().push(role.clone());
        reply(self.answer(&role, &system, &request)?)
    }
}
// endregion model

// region stages
/// 两个检查者同时运行，各写自己的状态键（第 18 章）。
fn checks(model: Arc<dyn Llm>) -> Result<Arc<dyn Agent>> {
    let mut agents: Vec<Arc<dyn Agent>> = Vec::new();
    for member in MEMBERS {
        agents.push(Arc::new(
            LlmAgentBuilder::new(format!("{member}_checker"))
                .static_instruction(format!(
                    "角色：{member}_checker 只检查 {member} 这一项。只回一个 JSON 对象：\
                     {{\"member\": \"{member}\", \"revision\": \"r2\", \"finding\": \"一句话\"}}"
                ))
                .model(model.clone())
                .output_key(format!("check_{member}"))
                .build()?,
        ));
    }
    Ok(Arc::new(ParallelAgent::new("checks", agents)))
}

/// 归并：两项发现都在、成员对得上、修订都是 r2，才写出证据；否则上报，整个流程停下。
fn merge() -> Result<Arc<dyn Agent>> {
    Ok(Arc::new(
        CustomAgent::builder("merge")
            .handler(|ctx: Arc<dyn InvocationContext>| async move {
                let state = ctx.session().state();
                let mut notes = Vec::new();
                let mut problem = None;
                for member in MEMBERS {
                    let finding: Option<Value> = state
                        .get(&format!("check_{member}"))
                        .and_then(|v| v.as_str().and_then(|s| serde_json::from_str(s).ok()));
                    match finding {
                        Some(f) if f["member"] == member && f["revision"] == "r2" => {
                            notes.push(json!({ "member": member, "finding": f["finding"] }));
                        }
                        Some(f) => {
                            problem = Some(format!(
                                "stale_result:{member}@{}",
                                f["revision"].as_str().unwrap_or("?")
                            ));
                        }
                        None => problem = Some(format!("missing:{member}")),
                    }
                }
                let mut event = Event::new(ctx.invocation_id());
                event.author = "merge".into();
                let text = match problem {
                    Some(reason) => {
                        event.actions.escalate = true;
                        format!("merge:{reason}")
                    }
                    None => {
                        event
                            .actions
                            .state_delta
                            .insert("evidence".into(), json!(notes).to_string().into());
                        "merge:ok".to_string()
                    }
                };
                event.llm_response.content = Some(Content::new("model").with_text(text));
                Ok(Box::pin(futures::stream::iter([Ok(event)])) as adk_core::EventStream)
            })
            .build()?,
    ))
}

/// 修复循环（第 21 章）：写作者按证据写稿，评估者检查来源；通过就上报，最多 3 轮。
fn refine(model: Arc<dyn Llm>) -> Result<Arc<dyn Agent>> {
    let writer = LlmAgentBuilder::new("writer")
        .static_instruction(
            "角色：writer 根据证据写一段升级说明。只回一个 JSON 对象：\
             {\"text\": \"说明\", \"sources\": [\"证据里的 member\"]}",
        )
        .instruction("证据：{evidence}\n评估反馈：{feedback?}")
        .model(model)
        .output_key("draft")
        .build()?;
    let evaluator = CustomAgent::builder("evaluator")
        .handler(|ctx: Arc<dyn InvocationContext>| async move {
            let state = ctx.session().state();
            let draft: Value = state
                .get("draft")
                .and_then(|v| v.as_str().and_then(|s| serde_json::from_str(s).ok()))
                .unwrap_or(Value::Null);
            let sources: Vec<&str> = draft["sources"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(Value::as_str)
                .collect();
            let mut failed = Vec::new();
            if draft["text"].as_str().unwrap_or("").is_empty() {
                failed.push("empty_text");
            }
            if sources.is_empty() {
                failed.push("missing_source");
            } else if sources.iter().any(|s| !MEMBERS.contains(s)) {
                failed.push("unchecked_source");
            }
            let mut event = Event::new(ctx.invocation_id());
            event.author = "evaluator".into();
            event
                .actions
                .state_delta
                .insert("feedback".into(), json!({ "failed": failed }));
            let text = if failed.is_empty() {
                event.actions.escalate = true;
                event
                    .actions
                    .state_delta
                    .insert("final_draft".into(), draft.to_string().into());
                "accepted".to_string()
            } else {
                format!("repair:{}", failed.join("+"))
            };
            event.llm_response.content = Some(Content::new("model").with_text(text));
            Ok(Box::pin(futures::stream::iter([Ok(event)])) as adk_core::EventStream)
        })
        .build()?;
    Ok(Arc::new(
        LoopAgent::new("refine", vec![Arc::new(writer), Arc::new(evaluator)])
            .with_max_iterations(3),
    ))
}
// endregion stages

// region boundary
/// 接缝适配：内层循环用 escalate 表示“通过、收工”，但这个信号会一路传到外层的
/// SequentialAgent，让整个流程停下。适配器把内层的 escalate 清掉，再按约定交出结果：
/// 有通过的稿子就让外层继续；没有，就自己上报一次，让外层停下。
fn contained(inner: Arc<dyn Agent>) -> Result<Arc<dyn Agent>> {
    Ok(Arc::new(
        CustomAgent::builder("refine_boundary")
            .handler(move |ctx: Arc<dyn InvocationContext>| {
                let inner = inner.clone();
                async move {
                    let accepted = Arc::new(AtomicBool::new(false));
                    let failed = Arc::new(AtomicBool::new(false));
                    let (seen, broke) = (accepted.clone(), failed.clone());
                    let invocation = ctx.invocation_id().to_string();
                    let events = inner.run(ctx).await?.map(move |item| {
                        if item.is_err() {
                            broke.store(true, Ordering::SeqCst);
                        }
                        item.map(|mut event| {
                            if event.actions.escalate {
                                if event.author == "evaluator" {
                                    seen.store(true, Ordering::SeqCst);
                                }
                                event.actions.escalate = false;
                            }
                            event
                        })
                    });
                    let verdict = futures::stream::once(async move {
                        // 内层出错时错误已经交出去了，不再补一条结论
                        if accepted.load(Ordering::SeqCst) || failed.load(Ordering::SeqCst) {
                            None
                        } else {
                            let mut event = Event::new(&invocation);
                            event.author = "refine_boundary".into();
                            event.actions.escalate = true;
                            event.llm_response.content =
                                Some(Content::new("model").with_text("refine:no_accepted_draft"));
                            Some(Ok(event))
                        }
                    })
                    .filter_map(futures::future::ready);
                    Ok(Box::pin(events.chain(verdict)) as adk_core::EventStream)
                }
            })
            .build()?,
    ))
}
// endregion boundary

// region publish
#[derive(Debug)]
struct PublishPolicy;

#[async_trait]
impl ToolPolicy for PublishPolicy {
    async fn evaluate(&self, request: &ToolPolicyRequest) -> PolicyDecision {
        if request.tool_name == "publish_report"
            && request.args["target"]
                .as_str()
                .is_some_and(|t| t.starts_with("releases/") && !t.contains(".."))
        {
            PolicyDecision::require_approval("发布需要编辑批准")
        } else {
            PolicyDecision::deny("publish_outside_policy")
        }
    }
}

fn publisher(model: Arc<dyn Llm>, root: Arc<PathBuf>) -> Result<Arc<dyn Agent>> {
    let tool = FunctionTool::new(
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
    );
    Ok(Arc::new(
        LlmAgentBuilder::new("publisher")
            .static_instruction(
                "角色：publisher 把定稿发布到 releases/3.0.md：调用 publish_report，content 用定稿的 text。",
            )
            .instruction("定稿：{final_draft}")
            .model(model)
            .tool(Arc::new(tool))
            .build()?,
    ))
}
// endregion publish

// region pipeline
/// 组合：检查 → 归并 → 修复循环 → 发布。`naive` 直接把内层循环放进外层顺序流程。
fn pipeline(model: Arc<dyn Llm>, root: Arc<PathBuf>, naive: bool) -> Result<Arc<dyn Agent>> {
    let refine = refine(model.clone())?;
    let refine = if naive { refine } else { contained(refine)? };
    Ok(Arc::new(SequentialAgent::new(
        "release",
        vec![
            checks(model.clone())?,
            merge()?,
            refine,
            publisher(model, root)?,
        ],
    )))
}
// endregion pipeline

struct Outcome {
    lines: Vec<String>,
    stop: String,
    held: bool,
}

async fn run_once(runner: &Runner, message: &str, config: RunConfig) -> Result<Outcome> {
    let mut out = Outcome {
        lines: vec![format!("--- run: {message}")],
        stop: "completed".into(),
        held: false,
    };
    let mut stream = runner
        .run_with_config(
            "user".try_into()?,
            "s1".try_into()?,
            Content::new("user").with_text(message),
            Some(config),
        )
        .await?;
    while let Some(event) = stream.next().await {
        let event = match event {
            Ok(event) => event,
            Err(error) => {
                out.lines.push(format!("[error] {error}"));
                out.stop = format!("error:{}", error.code);
                break;
            }
        };
        out.lines.extend(
            trace::event_lines(&event)
                .into_iter()
                .filter(|l| !l.contains("] held ")),
        );
        if event.actions.tool_confirmation.is_some() {
            out.held = true;
        }
        if event.actions.escalate {
            out.lines.push(format!("[{}] escalate", event.author));
            let text = event.content().map(texts).unwrap_or_default();
            out.stop = match event.author.as_str() {
                "evaluator" => "escalated_by:evaluator".into(),
                _ => text,
            };
        }
    }
    Ok(out)
}

async fn run_with(scenario: &str, model: Arc<dyn Llm>) -> Result<(Vec<String>, String)> {
    let dir = tempfile::tempdir()?;
    let root = Arc::new(dir.path().canonicalize()?);
    let sessions = Arc::new(InMemorySessionService::new());
    sessions
        .create(CreateRequest {
            app_name: "d08".into(),
            user_id: "user".into(),
            session_id: Some("s1".into()),
            state: Default::default(),
        })
        .await?;
    let approvals = Arc::new(InMemoryApprovalStore::new());
    let runner = Runner::builder()
        .app_name("d08")
        .agent(pipeline(model, root.clone(), scenario == "naive")?)
        .session_service(sessions)
        .tool_policy(Arc::new(PublishPolicy))
        .approval_store(approvals.clone())
        .without_intra_compaction()
        .build()?;
    // 整次运行共用一个预算：检查、写作、发布的模型调用都从这里扣
    let mut config = RunConfig {
        // 一次拿到完整回答（不逐块推送），替身和真实服务走同一条路
        streaming_mode: StreamingMode::None,
        ..RunConfig::default()
    };
    // budget 只够 4 次；budget-resume 的 5 次刚好用到发布挂起，恢复是新的运行、重新计数
    let max_calls = match scenario {
        "budget" => 4,
        "budget-resume" => 5,
        _ => 12,
    };
    config.budget = Some(RunBudget::new().max_model_calls(max_calls));
    let first = run_once(&runner, TASK, config.clone()).await?;
    let mut lines = first.lines;
    let mut stop = first.stop;
    let mut steps = vec![if first.held { "run:held" } else { "run" }.to_string()];
    if first.held {
        // 审批人批准等待中的发布，再恢复
        let scope = ApprovalScope::new("d08", "user", "s1");
        let pending = approvals.pending(&scope).await?;
        let fingerprint = &pending.first().ok_or("nothing pending")?.fingerprint;
        approvals
            .decide(&scope, fingerprint, ToolApproval::approve())
            .await?;
        lines.push("--- approve".into());
        let second = run_once(&runner, "", config).await?;
        lines.extend(second.lines);
        stop = second.stop;
        steps.push("approve".into());
        steps.push(if second.held { "resume:held" } else { "resume" }.into());
    }
    let published = fs::read_to_string(root.join("releases/3.0.md")).is_ok();
    let summary_tail = format!(
        "steps=[{}] published={} stop={stop}",
        steps.join(","),
        if published { "yes" } else { "no" }
    );
    Ok((lines, summary_tail))
}

async fn run(scenario: &str) -> Result<(Vec<String>, String)> {
    let model = Arc::new(RuleLlm {
        scenario: scenario.into(),
        calls: Mutex::new(Vec::new()),
    });
    let (mut lines, tail) = run_with(scenario, model.clone()).await?;
    let calls = model.calls.lock().unwrap().clone();
    let count = |role: &str| calls.iter().filter(|c| *c == role).count();
    let summary = format!(
        "{scenario}: model_calls={} checkers={} writer={} publisher={} {tail}",
        calls.len(),
        count("deps_checker") + count("docs_checker"),
        count("writer"),
        count("publisher"),
    );
    lines.push(summary.clone());
    Ok((lines, summary))
}

// region live
/// 同一个组合流程，换成 OpenAI 兼容服务。服务地址、模型和密钥只从环境变量读取。
async fn live() -> Result<()> {
    let base_url =
        std::env::var("OPENAI_BASE_URL").map_err(|_| "set OPENAI_BASE_URL (with /v1)")?;
    let model_name = std::env::var("OPENAI_MODEL").map_err(|_| "set OPENAI_MODEL")?;
    let api_key = std::env::var("OPENAI_API_KEY").unwrap_or_else(|_| "unused".into());
    let model = Arc::new(adk_model::openai::OpenAIClient::compatible(
        api_key, base_url, model_name,
    )?);
    let (lines, tail) = run_with("live", model).await?;
    for line in lines {
        println!("{line}");
    }
    println!("live: {tail}");
    Ok(())
}
// endregion live

async fn cli(args: &[String]) -> Result<()> {
    match args {
        [] => {
            for name in CASES {
                println!("{}", run(name).await?.1);
            }
            Ok(())
        }
        [name] if name == "live" => live().await,
        [name] if CASES.contains(&name.as_str()) => {
            for line in run(name).await?.0 {
                println!("{line}");
            }
            Ok(())
        }
        _ => Err(format!("usage: pattern-composition [{}|live]", CASES.join("|")).into()),
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
    async fn an_inner_escalate_stops_the_outer_workflow_unless_contained() {
        assert!(
            summary("naive")
                .await
                .ends_with("publisher=0 steps=[run] published=no stop=escalated_by:evaluator")
        );
        assert!(
            summary("normal")
                .await
                .ends_with("steps=[run:held,approve,resume] published=yes stop=completed")
        );
    }

    #[tokio::test]
    async fn a_bad_branch_stops_the_pipeline_before_writing() {
        assert!(summary("stale-branch").await.contains(
            "writer=0 publisher=0 steps=[run] published=no stop=merge:stale_result:deps@r1"
        ));
        assert!(
            summary("branch-failed")
                .await
                .ends_with("stop=error:model.unavailable")
        );
    }

    #[tokio::test]
    async fn a_loop_without_an_accepted_draft_does_not_reach_the_publisher() {
        assert!(summary("never-accepted").await.contains(
            "writer=3 publisher=0 steps=[run] published=no stop=refine:no_accepted_draft"
        ));
    }

    #[tokio::test]
    async fn one_budget_covers_every_stage() {
        assert!(
            summary("budget")
                .await
                .contains("model_calls=4 checkers=2 writer=2 publisher=0")
        );
        // 预算按运行计：第一次运行用满 5 次挂起，恢复运行重新计数，照样发布
        assert!(
            summary("budget-resume")
                .await
                .contains("model_calls=6 checkers=2 writer=2 publisher=2 steps=[run:held,approve,resume] published=yes")
        );
    }
}
