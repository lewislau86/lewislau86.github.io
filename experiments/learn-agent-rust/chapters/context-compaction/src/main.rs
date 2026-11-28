//! R08（ADK-Rust 3.0）：上下文压缩。
//!
//!   cargo run --locked                    全部场景的摘要
//!   cargo run --locked -- normal          某个场景的完整轨迹（场景名见 CASES）
//!
//! 一次代码审查：第一次运行读技能、读目标文件、读三份大资料；第二次运行“继续，给出结论”。
//! 压缩由框架执行：运行之间用 `EventsCompactionConfig`，运行之内用 `IntraCompactionConfig`；
//! 摘要器是应用自写的 `FactSummarizer`：让摘要模型写出事实清单，逐项核对后才交给框架。
//! 两个模型都是按规则回复的替身，只看得到各自的请求；文件工具真实读取临时目录。
mod trace;

use std::{
    fs,
    path::PathBuf,
    sync::{Arc, Mutex},
};

use adk_agent::LlmAgentBuilder;
use adk_core::{
    AdkError, BaseEventsSummarizer, Content, DeclarativePolicy, ErrorCategory, ErrorComponent,
    Event, EventCompaction, EventsCompactionConfig, FinishReason, IntraCompactionConfig, Llm,
    LlmRequest, LlmResponse, LlmResponseStream, Part, RunConfig, ToolContext, ToolEffect,
};
use adk_runner::Runner;
use adk_session::{CreateRequest, GetRequest, InMemorySessionService, SessionService};
use adk_tool::FunctionTool;
use async_trait::async_trait;
use futures::StreamExt;
use serde::Deserialize;
use serde_json::{Value, json};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

const SKILL: &str = "# Rust 函数审查\n先给结论，再列证据；没有运行测试时写明“未运行测试”。\n";
const SOURCE: &str = "pub fn first(values: &[u8]) -> u8 { values[0] }\n";
const TASK: &str = "审查 src/first.rs：先读审查规范和 docs 下的三份资料。禁止修改文件；没有运行测试时要说明“未运行测试”。";
const TASK_AND_CONCLUDE: &str = "审查 src/first.rs：读审查规范和 docs 下的三份资料，然后给出结论。禁止修改文件；没有运行测试时要说明“未运行测试”。";
const CONTINUE: &str = "继续，给出结论。";

const CASES: &[&str] = &[
    "normal",
    "small",
    "intra",
    "naive-trim",
    "omit-fact",
    "omit-unchecked",
    "invent-fact",
    "bad-json",
    "summary-error",
    "not-smaller",
];

// region facts
/// 应用为这次审查声明的事实清单：值来自真实读到的内容和用户的话。
/// 摘要必须逐项保留，而且每个值都要能在被压缩的那段历史里找到。
/// 另外一项 `latest_request` 是被压缩历史里用户最后说的话：用户的请求也会被压进摘要。
const FACTS: [(&str, &str); 7] = [
    ("target", "src/first.rs"),
    ("finding", "values[0]"),
    ("test_status", "未运行测试"),
    ("constraint", "禁止修改文件"),
    ("doc_a", "DOC-A"),
    ("doc_b", "DOC-B"),
    ("doc_c", "DOC-C"),
];

#[derive(Deserialize, PartialEq, Debug)]
#[serde(deny_unknown_fields)]
struct Fact {
    key: String,
    value: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct FactSummary {
    version: u32,
    facts: Vec<Fact>,
}

/// 核对摘要：格式、版本、事实的键与值都要和清单一致，值还要出现在被压缩的历史里。
/// 这次要压缩的那段历史里出现过的事实，才要求摘要保留；没压进来的部分原样留在历史里。
fn checklist(window: &str) -> Vec<(String, String)> {
    let mut facts: Vec<(String, String)> = FACTS
        .iter()
        .filter(|(_, v)| v.split(',').all(|part| window.contains(part)))
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect();
    if let Some(request) = window
        .lines()
        .filter_map(|line| line.strip_prefix("user: "))
        // 运行之内的摘要以用户角色的“系统通知”出现，它不是用户说的话
        .rfind(|text| !text.starts_with("[System notice]"))
    {
        facts.push(("latest_request".into(), request.to_string()));
    }
    facts
}

fn check_summary(
    text: &str,
    window: &str,
    expected: &[(String, String)],
) -> std::result::Result<(), &'static str> {
    let summary: FactSummary =
        serde_json::from_str(text).map_err(|_| "compaction.summary_schema")?;
    if summary.version != 1 || summary.facts.len() != expected.len() {
        return Err("compaction.summary_facts");
    }
    for (fact, (key, value)) in summary.facts.iter().zip(expected) {
        // 来源核对：值（多项时逐项）要出现在被压缩的那段历史里
        if fact.key != *key || fact.value != *value || !value.split(',').all(|v| window.contains(v))
        {
            return Err("compaction.summary_facts");
        }
    }
    Ok(())
}
// endregion facts

// region summarizer
/// 应用自写的摘要器：把要压缩的事件渲染成文字，交给摘要模型写事实清单，核对通过才返回。
/// 返回错误时，框架保留原历史继续运行（压缩是可选的优化，不是必须成功的步骤）。
struct FactSummarizer {
    model: Arc<dyn Llm>,
    /// 只用于 omit-unchecked 对照：不核对就接受
    checked: bool,
    calls: Mutex<Vec<String>>,
}

/// 和框架自带的摘要器一样：最近一次的旧摘要代替它覆盖的那些事件，不再重复渲染原文。
fn render(events: &[Event]) -> String {
    let earlier = events
        .iter()
        .rev()
        .find_map(|event| event.actions.compaction.as_ref())
        .map(|compaction| compaction.end_timestamp);
    let mut lines = Vec::new();
    for event in events {
        if event.actions.compaction.is_none() && earlier.is_some_and(|end| event.timestamp <= end) {
            continue;
        }
        if let Some(compaction) = &event.actions.compaction {
            for text in compaction
                .compacted_content
                .parts
                .iter()
                .filter_map(Part::text)
            {
                lines.push(format!("earlier summary: {text}"));
            }
            continue;
        }
        for part in event
            .content()
            .map(|c| c.parts.as_slice())
            .unwrap_or_default()
        {
            match part {
                Part::Text { text } => lines.push(format!("{}: {text}", event.author)),
                Part::FunctionCall { name, args, .. } => {
                    lines.push(format!("{} called {name} {args}", event.author))
                }
                Part::FunctionResponse {
                    function_response, ..
                } => lines.push(format!(
                    "{} result: {}",
                    function_response.name, function_response.response
                )),
                _ => {}
            }
        }
    }
    lines.join("\n")
}

impl FactSummarizer {
    async fn generate(&self, request: LlmRequest) -> adk_core::Result<String> {
        let mut stream = adk_core::generate_metered(self.model.as_ref(), request, false).await?;
        let mut text = String::new();
        while let Some(chunk) = stream.next().await {
            for part in chunk?.content.iter().flat_map(|c| c.parts.iter()) {
                if let Some(t) = part.text() {
                    text.push_str(t);
                }
            }
        }
        Ok(text)
    }
}

#[async_trait]
impl BaseEventsSummarizer for FactSummarizer {
    async fn summarize_events(&self, events: &[Event]) -> adk_core::Result<Option<Event>> {
        let window = render(events);
        let expected = checklist(&window);
        let keep: Vec<String> = expected
            .iter()
            .map(|(k, v)| format!("keep: {k}={v}"))
            .collect();
        let prompt = format!(
            "把下面的历史压缩成 JSON：{{\"version\":1,\"facts\":[{{\"key\",\"value\"}}]}}，按顺序保留这些事实：\n{}\n历史：\n{window}",
            keep.join("\n")
        );
        let request = LlmRequest::new(
            self.model.name(),
            vec![Content::new("user").with_text(prompt)],
        );
        // 和框架自带的摘要器一样，经过运行的预算记账
        let text = match self.generate(request).await {
            Ok(text) => text,
            Err(error) => {
                self.calls
                    .lock()
                    .unwrap()
                    .push(format!("failed {}", error.code));
                return Err(error);
            }
        };
        let verdict = if self.checked {
            check_summary(&text, &window, &expected).err()
        } else {
            None
        };
        self.calls.lock().unwrap().push(match verdict {
            Some(code) => format!("rejected {code}"),
            None => "accepted".into(),
        });
        if let Some(code) = verdict {
            return Err(AdkError::new(
                ErrorComponent::Agent,
                ErrorCategory::InvalidInput,
                code,
                "摘要没有通过事实核对，保留原历史",
            ));
        }
        let (Some(first), Some(last)) = (events.first(), events.last()) else {
            return Ok(None);
        };
        let mut event = Event::new("compaction");
        event.author = "compaction".into();
        event.actions.compaction = Some(EventCompaction {
            start_timestamp: first.timestamp,
            end_timestamp: last.timestamp,
            compacted_content: Content::new("model").with_text(text),
        });
        Ok(Some(event))
    }
}
// endregion summarizer

// region models
fn reply(part: Part) -> adk_core::Result<LlmResponseStream> {
    let mut response = LlmResponse::new(Content {
        role: "model".into(),
        parts: vec![part],
    });
    response.finish_reason = Some(FinishReason::Stop);
    response.turn_complete = true;
    Ok(Box::pin(futures::stream::iter([Ok(response)])))
}

/// 摘要模型：按场景写出事实清单（正常、漏写目标、虚构测试结果、不是 JSON、出错、写得太长）。
struct SummaryLlm {
    scenario: String,
}

#[async_trait]
impl Llm for SummaryLlm {
    fn name(&self) -> &str {
        "summary-llm"
    }

    async fn generate_content(
        &self,
        request: LlmRequest,
        _stream: bool,
    ) -> adk_core::Result<LlmResponseStream> {
        // 按提示里列出的 keep: 行复制事实；故障场景漏写目标或改写测试状态
        let prompt: String = request
            .contents
            .iter()
            .flat_map(|c| c.parts.iter().filter_map(Part::text))
            .collect();
        let facts: Vec<Value> = prompt
            .lines()
            .filter_map(|line| line.strip_prefix("keep: ")?.split_once('='))
            .filter(|(key, _)| {
                !(*key == "target"
                    && matches!(self.scenario.as_str(), "omit-fact" | "omit-unchecked"))
            })
            .map(|(key, value)| {
                let value = match self.scenario.as_str() {
                    "invent-fact" if key == "test_status" => "测试通过".to_string(),
                    // 漏掉目标：连用户原话里的文件名也没写进摘要
                    "omit-fact" | "omit-unchecked" => value.replace("src/first.rs", "那个文件"),
                    _ => value.to_string(),
                };
                json!({ "key": key, "value": value })
            })
            .collect();
        let text = match self.scenario.as_str() {
            "bad-json" => "目标是 src/first.rs，空输入会越界，未运行测试。".to_string(),
            "summary-error" => {
                return Err(AdkError::new(
                    ErrorComponent::Model,
                    ErrorCategory::Unavailable,
                    "model.unavailable",
                    "summary-llm: simulated provider failure",
                ));
            }
            "not-smaller" => format!(
                "{}{}",
                json!({ "version": 1, "facts": facts }),
                " ".repeat(20_000)
            ),
            _ => json!({ "version": 1, "facts": facts }).to_string(),
        };
        reply(Part::Text { text })
    }
}

/// 审查模型：只看请求内容决定下一步。
struct ReviewLlm {
    requests: Mutex<Vec<LlmRequest>>,
}

fn request_text(request: &LlmRequest) -> String {
    serde_json::to_string(&request.contents).unwrap_or_default()
}

/// 最后一条用户消息之后，有没有读过目标文件：证据要是这一轮的。
fn fresh_read(request: &LlmRequest) -> bool {
    let last_user = request
        .contents
        .iter()
        .rposition(|c| c.role == "user" && c.parts.iter().any(|p| p.text().is_some()));
    request.contents[last_user.map_or(0, |i| i + 1)..]
        .iter()
        .flat_map(|c| &c.parts)
        .any(|part| {
            matches!(part, Part::FunctionResponse { function_response, .. }
                if function_response.name == "read_file")
        })
}

fn call(name: &str, args: Value, id: String) -> Part {
    Part::FunctionCall {
        name: name.into(),
        args,
        id: Some(id),
        thought_signature: None,
    }
}

impl ReviewLlm {
    fn decide(&self, request: &LlmRequest, turn: usize) -> Vec<Part> {
        let text = request_text(request);
        let id = |name: &str| format!("{name}-{turn}");
        if !text.contains("先给结论") {
            return vec![call("load_skill", json!({}), id("skill"))];
        }
        if !text.contains("src/first.rs") {
            return vec![Part::Text {
                text: "任务未完成：历史里找不到要审查的文件（missing_evidence）。".into(),
            }];
        }
        if !fresh_read(request) {
            return vec![call(
                "read_file",
                json!({ "path": "src/first.rs" }),
                id("read"),
            )];
        }
        // 资料一次读一份：请求里（原文或摘要）还没出现的那份
        if let Some(doc) = ["a", "b", "c"]
            .into_iter()
            .find(|doc| !text.contains(&format!("DOC-{}", doc.to_uppercase())))
        {
            return vec![call(
                "read_doc",
                json!({ "name": doc }),
                id(&format!("doc-{doc}")),
            )];
        }
        if !text.contains("给出结论") {
            return vec![Part::Text {
                text: "资料已读完，等待下一步。".into(),
            }];
        }
        let tests = if text.contains("未运行测试") {
            "未运行测试。"
        } else {
            ""
        };
        vec![Part::Text {
            text: format!(
                "结论：空输入会触发索引越界。证据：src/first.rs 直接使用 values[0]。{tests}"
            ),
        }]
    }
}

#[async_trait]
impl Llm for ReviewLlm {
    fn name(&self) -> &str {
        "review-llm"
    }

    async fn generate_content(
        &self,
        request: LlmRequest,
        _stream: bool,
    ) -> adk_core::Result<LlmResponseStream> {
        let turn = {
            let mut requests = self.requests.lock().unwrap();
            requests.push(request.clone());
            requests.len()
        };
        // 让每条事件落在不同的毫秒：框架在会话里记录运行之内的压缩时，按毫秒时间戳定位切口，
        // 同一毫秒里的几条事件会让切口位置随机器快慢变化（见正文第 3 节）
        tokio::time::sleep(std::time::Duration::from_millis(3)).await;
        let mut response = LlmResponse::new(Content {
            role: "model".into(),
            parts: self.decide(&request, turn),
        });
        response.finish_reason = Some(FinishReason::Stop);
        response.turn_complete = true;
        Ok(Box::pin(futures::stream::iter([Ok(response)])))
    }
}
// endregion models

// region tools
fn tools(root: Arc<PathBuf>) -> Vec<FunctionTool> {
    let skill = FunctionTool::new(
        "load_skill",
        "读取 rust-review 审查规范。",
        |_ctx, _args| async { Ok(json!({ "skill": "rust-review", "body": SKILL })) },
    )
    .with_effect(ToolEffect::ReadOnly);
    let source_root = root.clone();
    let read = FunctionTool::new(
        "read_file",
        "读取 src/first.rs。",
        move |_ctx: Arc<dyn ToolContext>, args: Value| {
            let root = source_root.clone();
            async move {
                if args["path"] != "src/first.rs" {
                    return Err(AdkError::tool("只允许读取 src/first.rs"));
                }
                let text = fs::read_to_string(root.join("src/first.rs"))
                    .map_err(|e| AdkError::tool(e.to_string()))?;
                Ok(json!({ "path": "src/first.rs", "text": text }))
            }
        },
    )
    .with_effect(ToolEffect::ReadOnly);
    let doc = FunctionTool::new(
        "read_doc",
        "读取 docs 下的一份资料。",
        move |_ctx: Arc<dyn ToolContext>, args: Value| {
            let root = root.clone();
            async move {
                let name = args["name"].as_str().unwrap_or_default().to_owned();
                let text = fs::read_to_string(root.join(format!("docs/{name}.md")))
                    .map_err(|e| AdkError::tool(e.to_string()))?;
                Ok(json!({ "name": name, "text": text }))
            }
        },
    )
    .with_effect(ToolEffect::ReadOnly);
    vec![skill, read, doc]
}
// endregion tools

// region wiring
#[derive(Clone, Copy, PartialEq)]
enum Compaction {
    /// 不压缩
    Off,
    /// 每次运行结束后，把整段历史压成一份摘要（EventsCompactionConfig）
    BetweenRuns,
    /// 运行之中，请求估算超过阈值时压缩（IntraCompactionConfig）
    WithinRun,
}

struct Lab {
    runner: Runner,
    sessions: Arc<InMemorySessionService>,
    review: Arc<ReviewLlm>,
    summarizer: Arc<FactSummarizer>,
}

async fn lab(scenario: &str, root: Arc<PathBuf>, mode: Compaction) -> Result<Lab> {
    let review = Arc::new(ReviewLlm {
        requests: Mutex::new(Vec::new()),
    });
    let summarizer = Arc::new(FactSummarizer {
        model: Arc::new(SummaryLlm {
            scenario: scenario.into(),
        }),
        checked: scenario != "omit-unchecked",
        calls: Mutex::new(Vec::new()),
    });
    let mut agent = LlmAgentBuilder::new("reviewer")
        .instruction("你是代码审查助手。")
        .model(review.clone());
    for tool in tools(root) {
        agent = agent.tool(Arc::new(tool));
    }
    let sessions = Arc::new(InMemorySessionService::new());
    sessions
        .create(CreateRequest {
            app_name: "r08".into(),
            user_id: "user".into(),
            session_id: Some("s1".into()),
            state: Default::default(),
        })
        .await?;
    let policy = DeclarativePolicy::builder()
        .allow("load_skill")
        .allow("read_file")
        .allow("read_doc")
        .build();
    let mut runner = Runner::builder()
        .app_name("r08")
        .agent(Arc::new(agent.build()?))
        .session_service(sessions.clone())
        .tool_policy(Arc::new(policy));
    runner = match mode {
        Compaction::Off => runner.without_intra_compaction(),
        Compaction::BetweenRuns => {
            runner
                .without_intra_compaction()
                .compaction_config(EventsCompactionConfig {
                    compaction_interval: 1,
                    overlap_size: 0,
                    summarizer: summarizer.clone(),
                })
        }
        // 估算约 4 个 UTF-8 字节一个 token；读完第三份资料后的请求超过 1000
        Compaction::WithinRun => runner
            .intra_compaction_config(
                IntraCompactionConfig::at_tokens(1_000).with_overlap_event_count(0),
            )
            .intra_compaction_summarizer(summarizer.clone()),
    };
    Ok(Lab {
        runner: runner.build()?,
        sessions,
        review,
        summarizer,
    })
}
// endregion wiring

fn workspace() -> Result<(tempfile::TempDir, Arc<PathBuf>)> {
    let dir = tempfile::tempdir()?;
    let root = dir.path();
    fs::create_dir_all(root.join("src"))?;
    fs::create_dir_all(root.join("docs"))?;
    fs::write(root.join("src/first.rs"), SOURCE)?;
    for name in ["a", "b", "c"] {
        let marker = format!("DOC-{}", name.to_uppercase());
        let body = format!("{marker}: release checklist line for reviewers.\n").repeat(32);
        fs::write(root.join(format!("docs/{name}.md")), body)?;
    }
    let root = Arc::new(dir.path().canonicalize()?);
    Ok((dir, root))
}

/// 资料正文很长，轨迹里只写长度。
fn shorten(line: String) -> String {
    match line.find("read_doc status=ok ") {
        Some(at) => format!(
            "{}read_doc status=ok ({} bytes)",
            &line[..at],
            line.len() - at - "read_doc status=ok ".len()
        ),
        None => line,
    }
}

// region run
async fn run_once(lab: &Lab, text: &str, lines: &mut Vec<String>) -> Result<String> {
    run_once_with(lab, text, None, lines).await
}

async fn run_once_with(
    lab: &Lab,
    text: &str,
    config: Option<RunConfig>,
    lines: &mut Vec<String>,
) -> Result<String> {
    lines.push(format!("--- run: {text}"));
    let mut stream = lab
        .runner
        .run_with_config(
            "user".try_into()?,
            "s1".try_into()?,
            Content::new("user").with_text(text),
            config,
        )
        .await?;
    let mut answer = String::new();
    while let Some(event) = stream.next().await {
        let event = event?;
        lines.extend(trace::event_lines(&event).into_iter().map(shorten));
        if event.is_final_response() && event.author == "reviewer" {
            answer = event
                .content()
                .map(|c| c.parts.iter().filter_map(Part::text).collect())
                .unwrap_or_default();
        }
    }
    Ok(answer)
}

async fn run(scenario: &str) -> Result<(Vec<String>, String)> {
    let (_dir, root) = workspace()?;
    let mode = match scenario {
        "small" | "naive-trim" => Compaction::Off,
        "intra" => Compaction::WithinRun,
        _ => Compaction::BetweenRuns,
    };
    let lab = lab(scenario, root, mode).await?;
    let mut lines = Vec::new();
    let answer = if mode == Compaction::WithinRun {
        run_once(&lab, TASK_AND_CONCLUDE, &mut lines).await?
    } else {
        run_once(&lab, TASK, &mut lines).await?;
        if scenario == "naive-trim" {
            // 只装入最近的事件：第二次运行只带最后 2 条事件
            let config = RunConfig::builder().history_max_events(Some(2)).build();
            run_once_with(&lab, CONTINUE, Some(config), &mut lines).await?
        } else {
            run_once(&lab, CONTINUE, &mut lines).await?
        }
    };
    let session = lab
        .sessions
        .get(GetRequest {
            app_name: "r08".into(),
            user_id: "user".into(),
            session_id: "s1".into(),
            num_recent_events: None,
            after: None,
        })
        .await?;
    let compactions: Vec<String> = session
        .events()
        .all()
        .iter()
        .filter_map(|e| e.actions.compaction.as_ref())
        .flat_map(|c| c.compacted_content.parts.iter().filter_map(Part::text))
        .map(str::to_owned)
        .collect();
    for summary in &compactions {
        lines.push(format!("[compaction] {summary}"));
    }
    let requests = lab.review.requests.lock().unwrap().clone();
    for (i, request) in requests.iter().enumerate() {
        let est = adk_core::intra_compaction::estimate_content_tokens(&request.contents, 4);
        lines.push(format!(
            "{} est_tokens={est}",
            trace::request_lines(std::slice::from_ref(request))[0].replacen(
                "request 0",
                &format!("request {i}"),
                1
            )
        ));
    }
    let calls = lab.summarizer.calls.lock().unwrap().clone();
    let reloads = requests
        .iter()
        .flat_map(|r| r.contents.last())
        .filter(|c| {
            c.parts.iter().any(|p| matches!(p, Part::FunctionResponse { function_response, .. } if function_response.name == "load_skill"))
        })
        .count();
    let summary = format!(
        "{scenario}: summary_calls=[{}] compactions={} review_calls={} skill_loads={reloads} conclusion={} says_untested={}",
        calls.join(","),
        compactions.len(),
        requests.len(),
        answer.starts_with("结论："),
        answer.contains("未运行测试"),
    );
    lines.push(format!("answer: {answer}"));
    lines.push(summary.clone());
    Ok((lines, summary))
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
        _ => Err(format!("usage: context-compaction [{}]", CASES.join("|")).into()),
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

    #[test]
    fn the_checker_wants_every_fact_with_its_source() {
        let window = "user: 审查 src/first.rs，禁止修改文件，未运行测试\nresult: values[0] DOC-A DOC-B DOC-C";
        let expected = checklist(window);
        let good: Vec<Value> = expected
            .iter()
            .map(|(k, v)| json!({ "key": k, "value": v }))
            .collect();
        let text = json!({ "version": 1, "facts": good }).to_string();
        assert_eq!(check_summary(&text, window, &expected), Ok(()));
        let short = json!({ "version": 1, "facts": &good[1..] }).to_string();
        assert_eq!(
            check_summary(&short, window, &expected),
            Err("compaction.summary_facts")
        );
        assert_eq!(
            check_summary("不是 JSON", window, &expected),
            Err("compaction.summary_schema")
        );
        let changed = text.replace("values[0]", "values[1]");
        assert_eq!(
            check_summary(&changed, window, &expected),
            Err("compaction.summary_facts")
        );
        let wrong_version = text.replace("\"version\":1", "\"version\":2");
        assert_eq!(
            check_summary(&wrong_version, window, &expected),
            Err("compaction.summary_facts")
        );
        // 值必须出现在被压缩的历史里
        assert_eq!(
            check_summary(&text, "user: 别的内容", &expected),
            Err("compaction.summary_facts")
        );
    }

    fn tokens(lines: &[String], request: usize) -> u64 {
        let prefix = format!("request {request}:");
        let line = lines.iter().find(|l| l.starts_with(&prefix)).unwrap();
        line.rsplit("est_tokens=").next().unwrap().parse().unwrap()
    }

    #[tokio::test]
    async fn a_checked_summary_replaces_the_history_between_runs() {
        let (lines, line) = run("normal").await.unwrap();
        assert!(
            line.contains("compactions=2") && line.contains("conclusion=true"),
            "{line}"
        );
        assert!(line.contains("says_untested=true"), "{line}");
        // 第二次运行的第一次请求：摘要 + 新的用户消息，资料原文不在了
        let first_of_run_two = lines.iter().find(|l| l.starts_with("request 6:")).unwrap();
        assert!(
            first_of_run_two.contains("roles=system,model,user"),
            "{first_of_run_two}"
        );
        assert!(tokens(&lines, 6) * 5 < tokens(&lines, 5));
    }

    #[tokio::test]
    async fn a_rejected_summary_leaves_the_history_as_it_is() {
        for name in [
            "omit-fact",
            "invent-fact",
            "bad-json",
            "summary-error",
            "not-smaller",
        ] {
            let (lines, line) = run(name).await.unwrap();
            assert!(
                !line.contains("summary_calls=[]"),
                "the summarizer must have run: {line}"
            );
            assert!(line.contains("compactions=0"), "{line}");
            assert!(line.contains("conclusion=true"), "{line}");
            // 第二次运行的第一次请求带着完整的第一次运行
            assert!(tokens(&lines, 6) > 1_000, "{name}");
        }
    }

    #[tokio::test]
    async fn losing_the_target_stops_the_review() {
        for name in ["omit-unchecked", "naive-trim"] {
            let (lines, line) = run(name).await.unwrap();
            assert!(line.contains("conclusion=false"), "{line}");
            assert!(
                lines.iter().any(|l| l.contains("missing_evidence")),
                "{name}"
            );
        }
    }

    #[tokio::test]
    async fn compaction_within_a_run_keeps_calls_and_results_together() {
        let (lines, line) = run("intra").await.unwrap();
        assert!(
            line.contains("summary_calls=[accepted]") && line.contains("compactions=1"),
            "{line}"
        );
        assert!(line.contains("conclusion=true"), "{line}");
        // 压缩后的第一次请求：摘要通知 + 最后一对调用与结果（没有落单的结果），估算降到阈值以下
        let after = lines.iter().find(|l| l.starts_with("request 5:")).unwrap();
        assert!(
            after.contains("roles=system,user,model,function tools="),
            "{after}"
        );
        assert!(tokens(&lines, 5) < 1_000);
    }
}
