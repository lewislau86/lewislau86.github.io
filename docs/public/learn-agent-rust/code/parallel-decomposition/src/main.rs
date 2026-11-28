//! D03（ADK-Rust 3.0）：并行分解与结果归并。
//!
//!   cargo run --locked                 全部场景的摘要
//!   cargo run --locked -- failure      某个场景的完整轨迹（场景名见 CASES）
//!
//! 升级审查同时检查三件互不依赖的事：文档（docs）、依赖（deps）、配置（config）。
//! `ParallelAgent` 同时运行三个检查者，每个把发现写进自己的状态键；
//! 外层 `SequentialAgent` 再运行归并（一个 `CustomAgent`）：成员齐全、修订一致，才按成员顺序写出报告。
//! 检查者是 `LlmAgent`，模型是按规则回复的替身：每次请求先停一小会儿（让三个分支真正重叠），
//! 再回一个 JSON 发现。替身同时记录有几次请求在同时进行。
//! 运行时使用暂停的 Tokio 时钟，停顿按到期先后推进，完成顺序在任何机器上都一样。
mod trace;

use std::{
    sync::{
        Arc, Mutex,
        atomic::{AtomicUsize, Ordering},
    },
    time::Duration,
};

use adk_agent::{CustomAgent, LlmAgentBuilder, ParallelAgent, SequentialAgent};
use adk_core::{
    AdkError, Agent, Content, DeclarativePolicy, ErrorCategory, ErrorComponent, Event,
    FinishReason, InvocationContext, Llm, LlmRequest, LlmResponse, LlmResponseStream, Part,
};
use adk_runner::Runner;
use adk_session::{CreateRequest, InMemorySessionService, SessionService};
use adk_tool::ExitLoopTool;
use async_trait::async_trait;
use futures::StreamExt;
use serde_json::{Value, json};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

const MEMBERS: [&str; 3] = ["config", "deps", "docs"];
const TASK: &str = "审查修订 r2 的升级：文档、依赖、配置分别检查，再汇总。";

const CASES: &[&str] = &[
    "normal",
    "reverse",
    "failure",
    "escalate",
    "stale",
    "missing",
    "key-collision",
];

// region model
/// 替身模型：按系统消息里的“成员：xxx”扮演对应的检查者。
/// 先停一小会儿（毫秒数按场景给），再回一个发现；同时记录同一时刻有几次请求在进行。
struct CheckerLlm {
    scenario: String,
    in_flight: AtomicUsize,
    peak: AtomicUsize,
    calls: Mutex<Vec<String>>,
}

fn member_of(request: &LlmRequest) -> String {
    request
        .contents
        .iter()
        .filter(|c| c.role == "system")
        .flat_map(|c| c.parts.iter().filter_map(Part::text))
        .find_map(|t| t.split("成员：").nth(1))
        .and_then(|t| t.split_whitespace().next())
        .unwrap_or("?")
        .to_owned()
}

impl CheckerLlm {
    fn delay_ms(&self, member: &str) -> u64 {
        let order = MEMBERS.iter().position(|m| *m == member).unwrap_or(0) as u64;
        // normal：config 最快、docs 最慢；reverse 反过来
        if self.scenario == "reverse" {
            30 + (2 - order) * 40
        } else {
            30 + order * 40
        }
    }

    fn finding(&self, member: &str) -> std::result::Result<Part, AdkError> {
        let revision = if self.scenario == "stale" && member == "deps" {
            "r1"
        } else {
            "r2"
        };
        let note = match member {
            "config" => "配置里有一个 3.0 改名的键",
            "deps" => "tokio 需要升到 1.40",
            _ => "启动文档要改一行命令",
        };
        match (self.scenario.as_str(), member) {
            ("failure", "deps") => Err(AdkError::new(
                ErrorComponent::Model,
                ErrorCategory::Unavailable,
                "model.unavailable",
                "checker-llm: 依赖检查服务没有响应",
            )),
            // escalate：配置检查发现阻断问题，调用 exit_loop 让整个审查停下
            ("escalate", "config") => Ok(Part::FunctionCall {
                name: "exit_loop".into(),
                args: json!({}),
                id: Some("stop-config".into()),
                thought_signature: None,
            }),
            // missing：文档检查者没有给出结构化发现，只回了一句闲话
            ("missing", "docs") => Ok(Part::Text {
                text: "文档我看过了，应该没问题。".into(),
            }),
            _ => Ok(Part::Text {
                text: json!({ "member": member, "revision": revision, "finding": note })
                    .to_string(),
            }),
        }
    }
}

#[async_trait]
impl Llm for CheckerLlm {
    fn name(&self) -> &str {
        "checker-llm"
    }

    async fn generate_content(
        &self,
        request: LlmRequest,
        _stream: bool,
    ) -> adk_core::Result<LlmResponseStream> {
        let member = member_of(&request);
        self.calls.lock().unwrap().push(member.clone());
        let now = self.in_flight.fetch_add(1, Ordering::SeqCst) + 1;
        self.peak.fetch_max(now, Ordering::SeqCst);
        tokio::time::sleep(Duration::from_millis(self.delay_ms(&member))).await;
        self.in_flight.fetch_sub(1, Ordering::SeqCst);
        let part = self.finding(&member)?;
        let mut response = LlmResponse::new(Content {
            role: "model".into(),
            parts: vec![part],
        });
        response.finish_reason = Some(FinishReason::Stop);
        response.turn_complete = true;
        Ok(Box::pin(futures::stream::iter([Ok(response)])))
    }
}
// endregion model

// region fanout
/// 三个检查者：每个写自己的状态键 `check_<成员>`。
/// key-collision 场景故意让三个都写同一个键 `check`，看最后留下的是谁。
fn checkers(model: Arc<CheckerLlm>, shared_key: bool) -> Result<Arc<dyn Agent>> {
    let mut agents: Vec<Arc<dyn Agent>> = Vec::new();
    for member in MEMBERS {
        let key = if shared_key {
            "check".to_string()
        } else {
            format!("check_{member}")
        };
        let mut builder = LlmAgentBuilder::new(format!("{member}_checker"))
            .instruction(format!("成员：{member} 只检查这一项，回一个 JSON 发现。"))
            .model(model.clone())
            .output_key(key);
        if member == "config" {
            builder = builder.tool(Arc::new(ExitLoopTool::new()));
        }
        agents.push(Arc::new(builder.build()?));
    }
    Ok(Arc::new(ParallelAgent::new("checks", agents)))
}
// endregion fanout

// region merge
/// 归并：三个成员都要有发现、修订都是 r2；按成员名排序写报告。否则把事件标成 escalate（上报）。
/// 归并已是序列的最后一步，上报在这里不再改变流程，只是一个标记，调用方据此判断没有出报告。
/// `key` 给出每个成员的发现存在哪个状态键里。
fn merge_findings(
    state: &dyn Fn(&str) -> Option<Value>,
    key: &dyn Fn(&str) -> String,
) -> std::result::Result<String, String> {
    let mut lines = Vec::new();
    let mut missing = Vec::new();
    for member in MEMBERS {
        let finding: Option<Value> =
            state(&key(member)).and_then(|v| v.as_str().and_then(|s| serde_json::from_str(s).ok()));
        match finding {
            Some(f) if f["member"] == member && f["revision"] == "r2" => {
                lines.push(format!(
                    "{member}: {}",
                    f["finding"].as_str().unwrap_or("?")
                ));
            }
            Some(f) if f["member"] == member => {
                return Err(format!(
                    "stale_result:{member}@{}",
                    f["revision"].as_str().unwrap_or("?")
                ));
            }
            _ => missing.push(member),
        }
    }
    if missing.is_empty() {
        Ok(format!("报告（修订 r2）\n{}", lines.join("\n")))
    } else {
        Err(format!("member_mismatch:missing={}", missing.join("+")))
    }
}

fn merger(shared_key: bool) -> Result<Arc<dyn Agent>> {
    Ok(Arc::new(
        CustomAgent::builder("merge")
            .handler(move |ctx: Arc<dyn InvocationContext>| async move {
                let state = ctx.session().state();
                let key = |member: &str| {
                    if shared_key {
                        "check".to_string()
                    } else {
                        format!("check_{member}")
                    }
                };
                let verdict = merge_findings(&|k| state.get(k), &key);
                let mut event = Event::new(ctx.invocation_id());
                event.author = "merge".into();
                let text = match verdict {
                    Ok(report) => report,
                    Err(reason) => {
                        event.actions.escalate = true;
                        format!("merge:{reason}")
                    }
                };
                event.llm_response.content = Some(Content::new("model").with_text(text));
                Ok(Box::pin(futures::stream::iter([Ok(event)])) as adk_core::EventStream)
            })
            .build()?,
    ))
}
// endregion merge

// region run
async fn run(scenario: &str) -> Result<(Vec<String>, String)> {
    let model = Arc::new(CheckerLlm {
        scenario: scenario.into(),
        in_flight: AtomicUsize::new(0),
        peak: AtomicUsize::new(0),
        calls: Mutex::new(Vec::new()),
    });
    let review = SequentialAgent::new(
        "review",
        vec![
            checkers(model.clone(), scenario == "key-collision")?,
            merger(scenario == "key-collision")?,
        ],
    );
    let sessions = Arc::new(InMemorySessionService::new());
    sessions
        .create(CreateRequest {
            app_name: "d03".into(),
            user_id: "user".into(),
            session_id: Some("s1".into()),
            state: Default::default(),
        })
        .await?;
    let runner = Runner::builder()
        .app_name("d03")
        .agent(Arc::new(review))
        .session_service(sessions)
        .tool_policy(Arc::new(
            DeclarativePolicy::builder().allow("exit_loop").build(),
        ))
        .without_intra_compaction()
        .build()?;
    let mut lines = vec![format!("--- run: {TASK}")];
    let (mut finished, mut outcome, mut report) =
        (Vec::<String>::new(), String::from("report"), String::new());
    let mut stream = runner
        .run_with_config(
            "user".try_into()?,
            "s1".try_into()?,
            Content::new("user").with_text(TASK),
            None,
        )
        .await?;
    while let Some(event) = stream.next().await {
        let event = match event {
            Ok(event) => event,
            Err(error) => {
                lines.push(format!("[error] {error}"));
                outcome = format!("error:{}", error.code);
                break;
            }
        };
        lines.extend(trace::event_lines(&event));
        if event.actions.escalate {
            lines.push(format!("[{}] escalate", event.author));
        }
        let text = event
            .content()
            .map(|c| c.parts.iter().filter_map(Part::text).collect::<String>())
            .unwrap_or_default();
        if let Some(member) = event.author.strip_suffix("_checker")
            && event.is_final_response()
            && !finished.contains(&member.to_owned())
        {
            finished.push(member.to_owned());
        }
        if event.author == "merge" {
            match text.strip_prefix("merge:") {
                Some(reason) => outcome = reason.to_owned(),
                None => report = text.clone(),
            }
        } else if event.actions.escalate {
            outcome = format!("escalated_by:{}", event.author);
        }
    }
    let calls = model.calls.lock().unwrap().clone();
    let peak = model.peak.load(Ordering::SeqCst);
    lines.push(format!("report: {}", report.replace('\n', " | ")));
    let summary = format!(
        "{scenario}: started=[{}] finished=[{}] peak_concurrent={peak} outcome={outcome}{}",
        calls.join(","),
        finished.join(","),
        if report.is_empty() {
            String::new()
        } else {
            format!(" report_sha={}", short_hash(&report))
        }
    );
    lines.push(summary.clone());
    Ok((lines, summary))
}

/// 报告的指纹：比较两次运行的报告是否逐字相同。
fn short_hash(text: &str) -> String {
    let mut hash: u64 = 0xcbf29ce484222325;
    for byte in text.bytes() {
        hash ^= u64::from(byte);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    format!("{hash:016x}")[..8].to_owned()
}
// endregion run

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
        _ => Err(format!("usage: parallel-decomposition [{}]", CASES.join("|")).into()),
    }
}

// 用暂停的时钟：停顿按到期先后推进，不受机器快慢影响，完成顺序是确定的
#[tokio::main(flavor = "current_thread", start_paused = true)]
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

    #[tokio::test(start_paused = true)]
    async fn all_branches_overlap_and_the_report_ignores_finish_order() {
        let normal = summary("normal").await;
        let reverse = summary("reverse").await;
        assert!(
            normal.contains("finished=[config,deps,docs] peak_concurrent=3"),
            "{normal}"
        );
        assert!(
            reverse.contains("finished=[docs,deps,config] peak_concurrent=3"),
            "{reverse}"
        );
        assert_eq!(
            normal.split("report_sha=").nth(1),
            reverse.split("report_sha=").nth(1)
        );
    }

    #[tokio::test(start_paused = true)]
    async fn a_failed_branch_fails_the_fan_out_after_its_siblings_finish() {
        let line = summary("failure").await;
        assert!(line.contains("finished=[config,docs]"), "{line}");
        assert!(line.ends_with("outcome=error:model.unavailable"), "{line}");
    }

    #[tokio::test(start_paused = true)]
    async fn an_escalation_stops_the_other_branches() {
        let line = summary("escalate").await;
        assert!(line.contains("finished=[config]"), "{line}");
        assert!(
            line.ends_with("outcome=escalated_by:config_checker"),
            "{line}"
        );
    }

    #[tokio::test(start_paused = true)]
    async fn the_merge_checks_members_and_revisions() {
        assert!(
            summary("stale")
                .await
                .ends_with("outcome=stale_result:deps@r1")
        );
        assert!(
            summary("missing")
                .await
                .ends_with("outcome=member_mismatch:missing=docs")
        );
        assert!(
            summary("key-collision")
                .await
                .ends_with("outcome=member_mismatch:missing=config+deps")
        );
    }
}
