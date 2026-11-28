//! D01（ADK-Rust 3.0）：模式选择——单次调用、固定工作流与自主循环。
//!
//!   cargo run --locked                 全部场景的摘要
//!   cargo run --locked -- workflow     某个场景的完整轨迹（场景名见 CASES）
//!
//! 同一个任务：根据工作区里的 README 写一份升级报告，并列出依据的文件。
//! 三种结构：一次模型调用（资料随问题给出）、`SequentialAgent` 串起的固定步骤、
//! 由模型决定下一步读什么的 `LlmAgent` 工具循环。模型是按规则回复的替身；
//! 文件真实写在临时目录里；最后由应用验收：报告是否引用了根 README 列出的每个成员。
mod trace;

use std::{
    fs,
    path::PathBuf,
    sync::{Arc, Mutex},
};

use adk_agent::{CustomAgent, LlmAgentBuilder, SequentialAgent};
use adk_core::{
    AdkError, Agent, Content, DeclarativePolicy, ErrorCategory, ErrorComponent, Event,
    FinishReason, InvocationContext, Llm, LlmRequest, LlmResponse, LlmResponseStream, Part,
    ToolContext, ToolEffect,
};
use adk_runner::Runner;
use adk_session::{CreateRequest, InMemorySessionService, SessionService};
use adk_tool::FunctionTool;
use async_trait::async_trait;
use futures::StreamExt;
use serde_json::{Value, json};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

const TASK: &str = "根据工作区的 README 写一份升级报告，列出依据的文件。";
const ROOT_README: &str = "# demo-workspace\n升级到 3.0 需要 Rust 1.99。\n成员：member\n";
const ROOT_WITH_PLUGIN: &str =
    "# demo-workspace\n升级到 3.0 需要 Rust 1.99。\n成员：member, plugin\n";
const MEMBER_README: &str = "# member\n依赖 tokio 1.x；升级前先跑 member 的测试。\n";
const PLUGIN_README: &str = "# plugin\n用到了 3.0 删除的旧接口，需要改写。\n";

const CASES: &[&str] = &[
    "single",
    "single-partial",
    "workflow",
    "workflow-new-member",
    "workflow-missing",
    "workflow-silent",
    "adaptive",
    "forbidden",
    "budget",
];

// region acceptance
/// 根 README 里“成员：”一行列出的成员，加上根本身，就是报告必须引用的文件。
fn required_sources(root: &str) -> Vec<String> {
    let mut required = vec!["README.md".to_string()];
    if let Some(line) = root.lines().find_map(|l| l.strip_prefix("成员：")) {
        required.extend(line.split(',').map(|m| format!("{}/README.md", m.trim())));
    }
    required
}

/// 报告最后一行写着“依据：a, b”。应用据此验收：必须引用到全部必需的文件。
fn accept(report: &str, required: &[String]) -> std::result::Result<(), String> {
    let cited: Vec<&str> = report
        .lines()
        .find_map(|l| l.strip_prefix("依据："))
        .map(|l| l.split(", ").collect())
        .unwrap_or_default();
    let missing: Vec<&str> = required
        .iter()
        .map(String::as_str)
        .filter(|r| !cited.contains(r))
        .collect();
    if missing.is_empty() {
        Ok(())
    } else {
        Err(format!("missing:{}", missing.join("+")))
    }
}
// endregion acceptance

// region model
fn text_of(content: &Content) -> String {
    content
        .parts
        .iter()
        .filter_map(Part::text)
        .collect::<Vec<_>>()
        .join("\n")
}

/// 一段文字里出现的 README（按标题识别），按出现顺序。
fn readmes_in(text: &str) -> Vec<String> {
    let mut found = Vec::new();
    for (title, file) in [
        ("# demo-workspace", "README.md"),
        ("# member", "member/README.md"),
        ("# plugin", "plugin/README.md"),
    ] {
        if text.contains(title) {
            found.push(file.to_string());
        }
    }
    found
}

fn report(sources: &[String]) -> String {
    format!(
        "升级报告：按各 README 的要求逐项升级。\n依据：{}",
        sources.join(", ")
    )
}

/// 替身模型：只看请求决定下一步。
/// 没有工具时，按请求里出现的资料写报告；有 read_file 时，先读根 README，
/// 再按“成员：”一行补读还没读过的成员（这一步由模型决定），读完写报告。
struct ReportLlm {
    /// forbidden 场景里，模型读完根 README 后想去读一个工作区外的文件
    curious: bool,
    requests: Mutex<Vec<LlmRequest>>,
}

impl ReportLlm {
    fn decide(&self, request: &LlmRequest) -> Part {
        let all: String = request
            .contents
            .iter()
            .map(|c| serde_json::to_string(c).unwrap_or_default())
            .collect();
        if !request.tools.contains_key("read_file") {
            return Part::Text {
                text: report(&readmes_in(&all)),
            };
        }
        let results: Vec<&Value> = request
            .contents
            .iter()
            .flat_map(|c| c.parts.iter())
            .filter_map(|p| match p {
                Part::FunctionResponse {
                    function_response, ..
                } => Some(&function_response.response),
                _ => None,
            })
            .collect();
        if let Some(last) = results.last()
            && last.get("error").is_some()
        {
            return Part::Text {
                text: format!("没有完成：{}", last["error"].as_str().unwrap_or_default()),
            };
        }
        let read: Vec<String> = results
            .iter()
            .filter_map(|r| r["path"].as_str().map(str::to_owned))
            .collect();
        let next = if read.is_empty() {
            Some("README.md".to_string())
        } else if self.curious && read.len() == 1 {
            Some("../secret.txt".to_string())
        } else {
            let root = results
                .iter()
                .find(|r| r["path"] == "README.md")
                .and_then(|r| r["text"].as_str())
                .unwrap_or_default();
            required_sources(root)
                .into_iter()
                .find(|file| !read.contains(file))
        };
        match next {
            Some(path) => Part::FunctionCall {
                name: "read_file".into(),
                args: json!({ "path": path }),
                id: Some(format!("read-{}", read.len() + 1)),
                thought_signature: None,
            },
            None => Part::Text {
                text: report(&read),
            },
        }
    }
}

#[async_trait]
impl Llm for ReportLlm {
    fn name(&self) -> &str {
        "report-llm"
    }

    async fn generate_content(
        &self,
        request: LlmRequest,
        _stream: bool,
    ) -> adk_core::Result<LlmResponseStream> {
        self.requests.lock().unwrap().push(request.clone());
        let mut response = LlmResponse::new(Content {
            role: "model".into(),
            parts: vec![self.decide(&request)],
        });
        response.finish_reason = Some(FinishReason::Stop);
        response.turn_complete = true;
        Ok(Box::pin(futures::stream::iter([Ok(response)])))
    }
}
// endregion model

// region tools
/// 读工作区里的文件；路径不能跳出工作区。
fn read_file(root: Arc<PathBuf>, reads: Arc<Mutex<Vec<String>>>) -> FunctionTool {
    FunctionTool::new(
        "read_file",
        "读取工作区里的一个文件。",
        move |_ctx: Arc<dyn ToolContext>, args: Value| {
            let (root, reads) = (root.clone(), reads.clone());
            async move {
                let path = args["path"].as_str().unwrap_or_default().to_owned();
                if path.split('/').any(|part| part == ".." || part.is_empty()) {
                    return Err(AdkError::new(
                        ErrorComponent::Tool,
                        ErrorCategory::Forbidden,
                        "read.outside_workspace",
                        format!("{path} 在工作区外"),
                    ));
                }
                let text = fs::read_to_string(root.join(&path)).map_err(|_| {
                    AdkError::new(
                        ErrorComponent::Tool,
                        ErrorCategory::NotFound,
                        "read.missing",
                        format!("{path} 不存在"),
                    )
                })?;
                reads.lock().unwrap().push(path.clone());
                Ok(json!({ "path": path, "text": text }))
            }
        },
    )
    .with_effect(ToolEffect::ReadOnly)
}
// endregion tools

// region workflow
/// 固定步骤里的一步：由代码读一个文件，把内容写进会话状态。
/// 文件缺了：`stop_on_missing` 时把事件标成 escalate（上报，让外层停下），后面的步骤不再运行；
/// 否则写一个空字符串照常往下走——工作流不会知道这一步其实没读到。
fn read_step(
    name: &str,
    root: Arc<PathBuf>,
    file: &'static str,
    key: &'static str,
    reads: Arc<Mutex<Vec<String>>>,
    stop_on_missing: bool,
) -> Result<Arc<dyn Agent>> {
    let agent_name = name.to_owned();
    let agent = CustomAgent::builder(name)
        .handler(move |ctx: Arc<dyn InvocationContext>| {
            let (root, reads, author) = (root.clone(), reads.clone(), agent_name.clone());
            async move {
                let mut event = Event::new(ctx.invocation_id());
                event.author = author;
                match fs::read_to_string(root.join(file)) {
                    Ok(text) => {
                        reads.lock().unwrap().push(file.to_owned());
                        event.llm_response.content =
                            Some(Content::new("model").with_text(format!("读入 {file}")));
                        event.actions.state_delta.insert(key.into(), json!(text));
                    }
                    Err(_) if stop_on_missing => {
                        event.llm_response.content = Some(
                            Content::new("model")
                                .with_text(format!("missing_evidence: {file} 不存在，停止")),
                        );
                        event.actions.escalate = true;
                    }
                    Err(_) => {
                        event.llm_response.content =
                            Some(Content::new("model").with_text(format!("{file} 不存在，跳过")));
                        event.actions.state_delta.insert(key.into(), json!(""));
                    }
                }
                Ok(Box::pin(futures::stream::iter([Ok(event)])) as adk_core::EventStream)
            }
        })
        .build()?;
    Ok(Arc::new(agent))
}

/// 固定工作流：读根 README → 读 member README → 写报告。步骤由代码定，模型只写报告。
fn workflow(
    root: Arc<PathBuf>,
    model: Arc<ReportLlm>,
    reads: Arc<Mutex<Vec<String>>>,
    stop_on_missing: bool,
) -> Result<Arc<dyn Agent>> {
    let writer = LlmAgentBuilder::new("writer")
        .instruction(
            "根据资料写升级报告。\n根 README：\n{root_readme}\nmember README：\n{member_readme}",
        )
        .model(model)
        .build()?;
    Ok(Arc::new(SequentialAgent::new(
        "upgrade_workflow",
        vec![
            read_step(
                "read_root",
                root.clone(),
                "README.md",
                "root_readme",
                reads.clone(),
                stop_on_missing,
            )?,
            read_step(
                "read_member",
                root,
                "member/README.md",
                "member_readme",
                reads,
                stop_on_missing,
            )?,
            Arc::new(writer),
        ],
    )))
}
// endregion workflow

// region adaptive
/// 自主循环：一个带 read_file 的 LlmAgent，读什么、读几次由模型决定；
/// `max_iterations` 限制模型调用次数，文件路径由工具检查。
fn adaptive(
    root: Arc<PathBuf>,
    model: Arc<ReportLlm>,
    reads: Arc<Mutex<Vec<String>>>,
    max_iterations: u32,
) -> Result<Arc<dyn Agent>> {
    Ok(Arc::new(
        LlmAgentBuilder::new("explorer")
            .instruction("先读根 README，按需要补读成员的 README，再写升级报告。")
            .model(model)
            .tool(Arc::new(read_file(root, reads)))
            .max_iterations(max_iterations)
            .build()?,
    ))
}
// endregion adaptive

fn workspace(scenario: &str) -> Result<(tempfile::TempDir, PathBuf)> {
    let dir = tempfile::tempdir()?;
    let root = dir.path().canonicalize()?;
    let with_plugin = matches!(
        scenario,
        "workflow-new-member" | "adaptive" | "forbidden" | "budget"
    );
    fs::write(
        root.join("README.md"),
        if with_plugin {
            ROOT_WITH_PLUGIN
        } else {
            ROOT_README
        },
    )?;
    if !matches!(scenario, "workflow-missing" | "workflow-silent") {
        fs::create_dir_all(root.join("member"))?;
        fs::write(root.join("member/README.md"), MEMBER_README)?;
    }
    if with_plugin {
        fs::create_dir_all(root.join("plugin"))?;
        fs::write(root.join("plugin/README.md"), PLUGIN_README)?;
    }
    Ok((dir, root))
}

// region run
async fn run(scenario: &str) -> Result<(Vec<String>, String)> {
    let (_dir, root) = workspace(scenario)?;
    let root = Arc::new(root);
    let reads = Arc::new(Mutex::new(Vec::new()));
    let model = Arc::new(ReportLlm {
        curious: scenario == "forbidden",
        requests: Mutex::new(Vec::new()),
    });
    let (structure, agent, message) = match scenario {
        "single" => {
            let agent = LlmAgentBuilder::new("writer")
                .instruction("根据用户给的资料写升级报告。")
                .model(model.clone())
                .build()?;
            let message = format!("{TASK}\n\n{ROOT_README}\n{MEMBER_README}");
            ("single", Arc::new(agent) as Arc<dyn Agent>, message)
        }
        "single-partial" => {
            let agent = LlmAgentBuilder::new("writer")
                .instruction("根据用户给的资料写升级报告。")
                .model(model.clone())
                .build()?;
            (
                "single",
                Arc::new(agent) as Arc<dyn Agent>,
                format!("{TASK}\n\n{ROOT_README}"),
            )
        }
        "workflow" | "workflow-new-member" | "workflow-missing" | "workflow-silent" => (
            "workflow",
            workflow(
                root.clone(),
                model.clone(),
                reads.clone(),
                scenario != "workflow-silent",
            )?,
            TASK.to_string(),
        ),
        _ => (
            "adaptive",
            adaptive(
                root.clone(),
                model.clone(),
                reads.clone(),
                if scenario == "budget" { 2 } else { 8 },
            )?,
            TASK.to_string(),
        ),
    };
    let sessions = Arc::new(InMemorySessionService::new());
    sessions
        .create(CreateRequest {
            app_name: "d01".into(),
            user_id: "user".into(),
            session_id: Some("s1".into()),
            state: Default::default(),
        })
        .await?;
    let runner = Runner::builder()
        .app_name("d01")
        .agent(agent)
        .session_service(sessions)
        .tool_policy(Arc::new(
            DeclarativePolicy::builder().allow("read_file").build(),
        ))
        .without_intra_compaction()
        .build()?;
    let mut lines = vec![format!(
        "--- {structure}: {}",
        message.lines().next().unwrap_or_default()
    )];
    let (mut report_text, mut stop, mut authors) =
        (String::new(), "completed".to_string(), Vec::<String>::new());
    let mut stream = runner
        .run_with_config(
            "user".try_into()?,
            "s1".try_into()?,
            Content::new("user").with_text(&message),
            None,
        )
        .await?;
    while let Some(event) = stream.next().await {
        match event {
            Err(error) => {
                lines.push(format!("[error] {error}"));
                stop = if error.to_string().contains("Max iterations") {
                    "max_iterations".into()
                } else {
                    format!("error:{}", error.code)
                };
                break;
            }
            Ok(event) => {
                lines.extend(trace::event_lines(&event));
                if !authors.contains(&event.author) && event.author != "user" {
                    authors.push(event.author.clone());
                }
                if event.actions.escalate {
                    lines.push(format!("[{}] escalate", event.author));
                    stop = "escalated".into();
                }
                if let Some(text) = event.content().map(text_of).filter(|t| !t.is_empty()) {
                    report_text = text;
                }
            }
        }
    }
    let required = required_sources(&fs::read_to_string(root.join("README.md"))?);
    let verdict = if stop != "completed" {
        format!("rejected:{stop}")
    } else if !report_text.starts_with("升级报告") {
        "rejected:no_report".to_string()
    } else {
        match accept(&report_text, &required) {
            Ok(()) => "accepted".into(),
            Err(reason) => format!("rejected:{reason}"),
        }
    };
    let model_calls = model.requests.lock().unwrap().len();
    let reads = reads.lock().unwrap().clone();
    lines.push(format!("report: {}", report_text.replace('\n', " | ")));
    let summary = format!(
        "{scenario}: structure={structure} agents=[{}] model_calls={model_calls} reads=[{}] verdict={verdict}",
        authors.join(","),
        reads.join(",")
    );
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
        _ => Err(format!("usage: pattern-selection [{}]", CASES.join("|")).into()),
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

    #[test]
    fn the_report_must_cite_every_listed_member() {
        let required = required_sources(ROOT_WITH_PLUGIN);
        assert_eq!(
            required,
            ["README.md", "member/README.md", "plugin/README.md"]
        );
        let partial = "升级报告：…\n依据：README.md, member/README.md";
        assert_eq!(
            accept(partial, &required),
            Err("missing:plugin/README.md".into())
        );
    }

    #[tokio::test]
    async fn one_call_is_enough_only_when_the_input_is_complete() {
        assert!(
            summary("single")
                .await
                .contains("model_calls=1 reads=[] verdict=accepted")
        );
        assert!(
            summary("single-partial")
                .await
                .ends_with("verdict=rejected:missing:member/README.md")
        );
    }

    #[tokio::test]
    async fn fixed_steps_cannot_follow_a_new_member() {
        assert!(summary("workflow").await.ends_with("verdict=accepted"));
        assert!(
            summary("workflow-new-member")
                .await
                .ends_with("rejected:missing:plugin/README.md")
        );
        let silent = summary("workflow-silent").await;
        assert!(
            silent.ends_with("verdict=rejected:missing:member/README.md"),
            "{silent}"
        );
        let missing = summary("workflow-missing").await;
        assert!(
            missing.contains("agents=[read_root,read_member] model_calls=0"),
            "{missing}"
        );
    }

    #[tokio::test]
    async fn the_loop_follows_what_it_reads_within_its_limits() {
        assert!(summary("adaptive").await.contains(
            "model_calls=4 reads=[README.md,member/README.md,plugin/README.md] verdict=accepted"
        ));
        assert!(
            summary("forbidden")
                .await
                .ends_with("reads=[README.md] verdict=rejected:no_report")
        );
        assert!(
            summary("budget")
                .await
                .ends_with("verdict=rejected:max_iterations")
        );
    }
}
