//! D06（ADK-Rust 3.0）：评估、反思与有界修复。
//!
//!   cargo run --locked                 全部场景的摘要
//!   cargo run --locked -- new-error    某个场景的完整轨迹（场景名见 CASES）
//!
//! 第一部分：`LoopAgent` 每一轮先运行写作者（`LlmAgent`，输出一份带来源的升级摘要），
//! 再运行评估者（`CustomAgent`，用固定规则逐条检查，把反馈写进会话状态）。
//! 全部规则通过就上报（escalate）收工；没有进展也上报停下；轮数用完，循环安静地结束。
//! 第二部分：adk-retry-reflect 插件在工具失败时，把结果换成一段“反思提示”，让模型改参数重试，
//! 次数有上限。两部分的模型都是按规则回复的替身。
mod trace;

use std::{
    collections::BTreeMap,
    sync::{Arc, Mutex},
};

use adk_agent::{CustomAgent, LlmAgentBuilder, LoopAgent};
use adk_core::{
    AdkError, Agent, Content, DeclarativePolicy, ErrorCategory, ErrorComponent, Event,
    FinishReason, InvocationContext, Llm, LlmRequest, LlmResponse, LlmResponseStream, Part,
    ToolContext, ToolEffect,
};
use adk_retry_reflect::RetryReflectPluginBuilder;
use adk_runner::Runner;
use adk_session::{CreateRequest, InMemorySessionService, SessionService};
use adk_tool::FunctionTool;
use async_trait::async_trait;
use futures::StreamExt;
use serde_json::{Value, json};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

const CASES: &[&str] = &[
    "normal",
    "already-good",
    "new-error",
    "no-progress",
    "never-good",
    "tool-retry",
    "tool-retry-exhausted",
    "tool-retry-wandering",
];

/// 评估者认可的来源：工作区里真实存在、写作者读过的文件。
const ALLOWED_SOURCES: [&str; 2] = ["README.md", "member/README.md"];
const SUMMARY_TEXT: &str = "升级到 3.0 需要把 member 的启动命令改成 serve。";

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

fn system_text(request: &LlmRequest) -> String {
    request
        .contents
        .iter()
        .filter(|c| c.role == "system")
        .map(texts)
        .collect()
}

// region writer
/// 写作者的替身：从系统消息里读上一稿与评估反馈，按反馈里没通过的规则改出下一稿。
/// 每一稿都附一句“已自查”——评估者不看这句话，只按规则检查。
struct WriterLlm {
    scenario: String,
    /// 每一稿依据的反馈（没通过的规则）；第一稿没有反馈
    used_feedback: Mutex<Vec<String>>,
}

/// 从系统消息里取出模板渲染进来的 JSON（`标记：{...}`）。
fn embedded(system: &str, marker: &str) -> Option<Value> {
    let rest = system.split(marker).nth(1)?;
    let line = rest.lines().next()?.trim();
    serde_json::from_str(line).ok()
}

impl WriterLlm {
    fn draft(&self, system: &str) -> Value {
        let previous = embedded(system, "上一稿：");
        let feedback = embedded(system, "评估反馈：");
        let revision = previous
            .as_ref()
            .and_then(|d| d["revision"].as_u64())
            .unwrap_or(0)
            + 1;
        // 只采用针对上一稿的反馈：修订号要对得上
        let failed: Vec<String> = match (&previous, &feedback) {
            (Some(p), Some(f)) if f["revision"] == p["revision"] => f["failed"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|v| v.as_str().map(str::to_owned))
                .collect(),
            _ => Vec::new(),
        };
        self.used_feedback
            .lock()
            .unwrap()
            .push(if failed.is_empty() {
                "-".to_owned()
            } else {
                failed.join("+")
            });
        let Some(previous) = previous else {
            // 第一稿：结论对，但除了 already-good 都没写来源
            let sources: Vec<&str> = if self.scenario == "already-good" {
                vec!["README.md"]
            } else {
                vec![]
            };
            return self.finish(revision, SUMMARY_TEXT, sources);
        };
        let mut text = previous["text"].as_str().unwrap_or("").to_owned();
        let mut sources: Vec<&str> = previous["sources"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
            .collect();
        // no-progress：嘴上说改了，内容和上一稿一模一样
        if self.scenario != "no-progress" {
            for rule in &failed {
                match rule.as_str() {
                    "missing_source" | "unread_source" if self.scenario == "never-good" => {
                        // 每次换一个说法，引用的都是没读过的网页
                        text = ["据说要改启动命令。", "社区说要改启动命令。"]
                            [(revision as usize) % 2]
                            .to_owned();
                        sources = vec!["https://blog.example/adk-3"];
                    }
                    "missing_source" | "unread_source" => {
                        sources = vec!["README.md"];
                        // new-error：补来源的时候把正文弄丢了
                        if self.scenario == "new-error" {
                            text.clear();
                        }
                    }
                    "empty_text" => text = SUMMARY_TEXT.to_owned(),
                    _ => {}
                }
            }
        }
        self.finish(revision, &text, sources)
    }

    fn finish(&self, revision: u64, text: &str, sources: Vec<&str>) -> Value {
        json!({
            "revision": revision,
            "text": text,
            "sources": sources,
            "self_check": "已自查，没有问题",
        })
    }
}

#[async_trait]
impl Llm for WriterLlm {
    fn name(&self) -> &str {
        "writer-llm"
    }

    async fn generate_content(
        &self,
        request: LlmRequest,
        _stream: bool,
    ) -> adk_core::Result<LlmResponseStream> {
        let draft = self.draft(&system_text(&request));
        reply(Part::Text {
            text: draft.to_string(),
        })
    }
}
// endregion writer

// region evaluator
/// 固定规则：每条规则只看候选稿本身，结果可以复核。
fn failed_criteria(draft: &Value) -> Vec<&'static str> {
    let mut failed = Vec::new();
    if draft["text"].as_str().unwrap_or("").trim().is_empty() {
        failed.push("empty_text");
    }
    let sources: Vec<&str> = draft["sources"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .collect();
    if sources.is_empty() {
        failed.push("missing_source");
    } else if sources.iter().any(|s| !ALLOWED_SOURCES.contains(s)) {
        failed.push("unread_source");
    }
    failed
}

/// 评估者：检查最新一稿，把反馈（绑定修订号）写进状态。
/// 全部通过就上报收工；和上一稿内容相同（没有进展）也上报停下。第一稿另存为基线。
fn evaluator() -> Result<Arc<dyn Agent>> {
    Ok(Arc::new(
        CustomAgent::builder("evaluator")
            .handler(|ctx: Arc<dyn InvocationContext>| async move {
                let state = ctx.session().state();
                let draft: Value = state
                    .get("draft")
                    .and_then(|v| v.as_str().and_then(|s| serde_json::from_str(s).ok()))
                    .unwrap_or(Value::Null);
                let previous = state.get("feedback");
                let failed = failed_criteria(&draft);
                let revision = draft["revision"].as_u64().unwrap_or(0);
                let same_as_before = previous.as_ref().is_some_and(|f| {
                    f["text"] == draft["text"] && f["sources"] == draft["sources"]
                });
                let mut event = Event::new(ctx.invocation_id());
                event.author = "evaluator".into();
                let verdict = if failed.is_empty() {
                    event.actions.escalate = true;
                    format!("accepted:r{revision}")
                } else if same_as_before {
                    event.actions.escalate = true;
                    "no_progress".to_string()
                } else {
                    format!("repair:{}", failed.join("+"))
                };
                event.actions.state_delta.insert(
                    "feedback".into(),
                    json!({
                        "revision": revision,
                        "failed": failed,
                        "text": draft["text"],
                        "sources": draft["sources"],
                    }),
                );
                if state.get("baseline").is_none() {
                    event
                        .actions
                        .state_delta
                        .insert("baseline".into(), draft.clone());
                }
                event.llm_response.content = Some(Content::new("model").with_text(verdict));
                Ok(Box::pin(futures::stream::iter([Ok(event)])) as adk_core::EventStream)
            })
            .build()?,
    ))
}
// endregion evaluator

// region loop
fn refine_loop(model: Arc<WriterLlm>) -> Result<Arc<dyn Agent>> {
    let writer = LlmAgentBuilder::new("writer")
        .instruction(
            "写一段升级摘要，JSON 格式（revision、text、sources）。\n\
             上一稿：{draft?}\n\
             评估反馈：{feedback?}",
        )
        .model(model)
        .output_key("draft")
        .build()?;
    Ok(Arc::new(
        LoopAgent::new("refine", vec![Arc::new(writer), evaluator()?]).with_max_iterations(3),
    ))
}
// endregion loop

async fn session_service(app: &str) -> Result<Arc<InMemorySessionService>> {
    let sessions = Arc::new(InMemorySessionService::new());
    sessions
        .create(CreateRequest {
            app_name: app.into(),
            user_id: "user".into(),
            session_id: Some("s1".into()),
            state: Default::default(),
        })
        .await?;
    Ok(sessions)
}

async fn run_refine(scenario: &str) -> Result<(Vec<String>, String)> {
    let model = Arc::new(WriterLlm {
        scenario: scenario.into(),
        used_feedback: Mutex::new(Vec::new()),
    });
    let runner = Runner::builder()
        .app_name("d06")
        .agent(refine_loop(model.clone())?)
        .session_service(session_service("d06").await?)
        .without_intra_compaction()
        .build()?;
    let task = "写一段升级摘要，每个结论都要有来源。";
    let mut lines = vec![format!("--- run: {task}")];
    let (mut verdicts, mut stop, mut iterations) = (Vec::new(), "loop_limit".to_string(), 0);
    let mut baseline = String::from("-");
    let mut stream = runner
        .run_with_config(
            "user".try_into()?,
            "s1".try_into()?,
            Content::new("user").with_text(task),
            None,
        )
        .await?;
    while let Some(event) = stream.next().await {
        let event = event?;
        lines.extend(trace::event_lines(&event));
        if event.author != "evaluator" {
            continue;
        }
        iterations += 1;
        let verdict = event.content().map(texts).unwrap_or_default();
        let feedback = &event.actions.state_delta["feedback"];
        let failed: Vec<&str> = feedback["failed"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
            .collect();
        verdicts.push(format!(
            "r{}:{}",
            feedback["revision"],
            if failed.is_empty() {
                "pass".to_string()
            } else {
                failed.join("+")
            }
        ));
        if let Some(b) = event.actions.state_delta.get("baseline") {
            baseline = format!("r{}", b["revision"]);
        }
        if event.actions.escalate {
            lines.push("[evaluator] escalate".into());
            stop = verdict.split(':').next().unwrap_or("?").to_owned();
        }
    }
    lines.push(format!(
        "[writer] 每一稿依据的反馈：{:?}",
        model.used_feedback.lock().unwrap()
    ));
    let summary = format!(
        "{scenario}: checks=[{}] iterations={iterations} baseline={baseline} stop={stop}",
        verdicts.join(",")
    );
    lines.push(summary.clone());
    Ok((lines, summary))
}

// region tool
/// read_file：只读一个内存里的小工作区；路径不存在就报错。
fn read_file() -> FunctionTool {
    let files: BTreeMap<&str, &str> = [
        ("README.md", "成员：member"),
        ("member/README.md", "启动命令：serve"),
    ]
    .into();
    FunctionTool::new(
        "read_file",
        "读取工作区里的一个文件：path 是相对路径。",
        move |_ctx: Arc<dyn ToolContext>, args: Value| {
            let content = args["path"].as_str().and_then(|p| files.get(p)).copied();
            let path = args["path"].as_str().unwrap_or("").to_owned();
            async move {
                match content {
                    Some(text) => Ok(json!({ "path": path, "content": text })),
                    None => Err(AdkError::new(
                        ErrorComponent::Tool,
                        ErrorCategory::NotFound,
                        "tool.file_not_found",
                        format!("no such file: {path}"),
                    )),
                }
            }
        },
    )
    .with_effect(ToolEffect::ReadOnly)
}
// endregion tool

/// 读文件的替身模型：路径写错了，看到反思提示就换一个路径再试，看到原始错误就放弃。
struct ReaderLlm {
    scenario: String,
    /// 每次调用 read_file 时用的路径
    tried: Mutex<Vec<String>>,
}

#[async_trait]
impl Llm for ReaderLlm {
    fn name(&self) -> &str {
        "reader-llm"
    }

    async fn generate_content(
        &self,
        request: LlmRequest,
        _stream: bool,
    ) -> adk_core::Result<LlmResponseStream> {
        let last = request
            .contents
            .iter()
            .rev()
            .flat_map(|c| c.parts.iter())
            .find_map(|p| match p {
                Part::FunctionResponse {
                    function_response, ..
                } => Some(function_response.response.clone()),
                _ => None,
            });
        let mut tried = self.tried.lock().unwrap();
        let next = match last {
            None => Some("READMe.md"),
            Some(result) if result.get("content").is_some() => None,
            // 原始错误（没有反思提示）：放弃
            Some(result) if result.get("reflection").is_none() => {
                return reply(Part::Text {
                    text: "读不到这个文件，先停下来问用户。".into(),
                });
            }
            Some(_) => Some(match self.scenario.as_str() {
                // 按提示改正大小写
                "tool-retry" => "README.md",
                // 一直用同一个错路径
                "tool-retry-exhausted" => "READMe.md",
                // 每次换一个错路径
                _ => ["readme.md", "Readme.md", "README.txt", "docs/README.md"]
                    [(tried.len() - 1) % 4],
            }),
        };
        let Some(path) = next else {
            return reply(Part::Text {
                text: format!("读到了：{}", tried.last().cloned().unwrap_or_default()),
            });
        };
        tried.push(path.to_owned());
        reply(Part::FunctionCall {
            name: "read_file".into(),
            args: json!({ "path": path }),
            id: Some(format!("read-{}", tried.len())),
            thought_signature: None,
        })
    }
}

// region reflect
/// 反思插件：同一工具、同样参数的失败最多给 2 次反思提示；
/// 整次运行最多 3 次（global_limit），防止模型每次换个参数绕过单次上限。
fn reader(scenario: &str, model: Arc<ReaderLlm>) -> Result<Arc<dyn Agent>> {
    let plugin = RetryReflectPluginBuilder::new()
        .max_retries(2)
        .global_limit(3)
        .build()?;
    Ok(Arc::new(
        LlmAgentBuilder::new("reader")
            .instruction(format!("读 README.md，场景：{scenario}"))
            .model(model)
            .tool(Arc::new(read_file()))
            .enhanced_plugin(Arc::new(plugin))
            .max_iterations(8)
            .build()?,
    ))
}
// endregion reflect

async fn run_reflect(scenario: &str) -> Result<(Vec<String>, String)> {
    let model = Arc::new(ReaderLlm {
        scenario: scenario.into(),
        tried: Mutex::new(Vec::new()),
    });
    let runner = Runner::builder()
        .app_name("d06")
        .agent(reader(scenario, model.clone())?)
        .session_service(session_service("d06").await?)
        .tool_policy(Arc::new(
            DeclarativePolicy::builder().allow("read_file").build(),
        ))
        .without_intra_compaction()
        .build()?;
    let task = "读一下 README.md。";
    let mut lines = vec![format!("--- run: {task}")];
    let (mut results, mut answer, mut stop) = (Vec::new(), String::new(), "answered".to_string());
    let mut stream = runner
        .run_with_config(
            "user".try_into()?,
            "s1".try_into()?,
            Content::new("user").with_text(task),
            None,
        )
        .await?;
    while let Some(event) = stream.next().await {
        let event = match event {
            Ok(event) => event,
            Err(error) => {
                lines.push(format!("[error] {error}"));
                stop = format!("error:{}", error.code);
                break;
            }
        };
        lines.extend(trace::event_lines(&event));
        for part in event.content().iter().flat_map(|c| c.parts.iter()) {
            match part {
                Part::FunctionResponse {
                    function_response, ..
                } => {
                    let r = &function_response.response;
                    results.push(if r.get("content").is_some() {
                        "ok"
                    } else if r.get("reflection").is_some() {
                        "reflection"
                    } else {
                        "error"
                    });
                }
                Part::Text { text } if event.is_final_response() => answer = text.clone(),
                _ => {}
            }
        }
    }
    let tried = model.tried.lock().unwrap().clone();
    let calls: Vec<String> = tried
        .iter()
        .zip(&results)
        .map(|(path, result)| format!("{path}:{result}"))
        .collect();
    let outcome = if answer.starts_with("读到了") {
        "read"
    } else if answer.is_empty() {
        "-"
    } else {
        "gave_up"
    };
    let summary = format!(
        "{scenario}: calls=[{}] outcome={outcome} stop={stop}",
        calls.join(",")
    );
    lines.push(summary.clone());
    Ok((lines, summary))
}

async fn run(scenario: &str) -> Result<(Vec<String>, String)> {
    if scenario.starts_with("tool-") {
        run_reflect(scenario).await
    } else {
        run_refine(scenario).await
    }
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
        _ => Err(format!("usage: evaluator-reflection [{}]", CASES.join("|")).into()),
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
    async fn the_evaluator_ignores_self_checks_and_rechecks_every_rule() {
        assert!(
            summary("normal")
                .await
                .contains("checks=[r1:missing_source,r2:pass]")
        );
        assert!(
            summary("new-error")
                .await
                .contains("checks=[r1:missing_source,r2:empty_text,r3:pass]")
        );
        assert!(summary("already-good").await.ends_with("stop=accepted"));
    }

    #[tokio::test]
    async fn no_progress_and_the_loop_limit_both_stop_without_acceptance() {
        assert!(summary("no-progress").await.ends_with("stop=no_progress"));
        let never = summary("never-good").await;
        assert!(
            never.ends_with("iterations=3 baseline=r1 stop=loop_limit"),
            "{never}"
        );
    }

    #[tokio::test]
    async fn a_reflection_prompt_replaces_the_tool_error_until_the_limit() {
        assert!(
            summary("tool-retry")
                .await
                .contains("calls=[READMe.md:reflection,README.md:ok] outcome=read")
        );
        assert!(summary("tool-retry-exhausted").await.contains(
            "calls=[READMe.md:reflection,READMe.md:reflection,READMe.md:error] outcome=gave_up"
        ));
    }

    #[tokio::test]
    async fn the_global_limit_catches_a_model_that_keeps_changing_arguments() {
        let wandering = summary("tool-retry-wandering").await;
        assert!(
            wandering.contains("Readme.md:reflection,README.txt:error] outcome=gave_up"),
            "{wandering}"
        );
    }
}
