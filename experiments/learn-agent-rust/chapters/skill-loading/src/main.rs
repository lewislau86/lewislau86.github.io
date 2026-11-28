//! R07（ADK-Rust 3.0 / adk-skill）：按需加载技能。
//!
//!   cargo run --locked                    全部场景的摘要
//!   cargo run --locked -- normal          某个场景的完整轨迹（场景名见 CASES）
//!
//! 技能放在练习工作区的 `.skills/` 里，启动时由 `load_skill_index` 建成索引。
//! 主线用 `SkillToolset`：模型先 `list_skills` 看目录，再 `load_skill` 取正文，需要时 `load_skill_resource`
//! 读附带资源；对照场景 `auto-inject` 用 `SkillInjector` 方式，按问题自动把技能正文放进用户消息。
//! 模型是按规则回复的 RuleLlm，只看得到请求；文件工具真实读写临时目录。
mod trace;

use std::{
    fs,
    path::{Path, PathBuf},
    sync::{
        Arc, Mutex,
        atomic::{AtomicUsize, Ordering},
    },
};

use adk_agent::LlmAgentBuilder;
use adk_core::{
    AdkError, Content, DeclarativePolicy, ErrorCategory, ErrorComponent, FinishReason, Llm,
    LlmRequest, LlmResponse, LlmResponseStream, Part, Tool, ToolContext, ToolEffect, ToolRegistry,
};
use adk_runner::Runner;
use adk_session::{CreateRequest, InMemorySessionService, SessionService};
use adk_skill::{ResourceAccessPolicy, SkillToolset, SkillToolsetConfig, load_skill_index};
use adk_tool::FunctionTool;
use async_trait::async_trait;
use futures::StreamExt;
use serde_json::{Value, json};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

const REVIEW: &str = include_str!("../skills/rust-review/SKILL.md");
const CHECKLIST: &str = include_str!("../skills/rust-review/references/checklist.md");
const SQL: &str = include_str!("../skills/sql-style/SKILL.md");
const SOURCE: &str = "pub fn first(values: &[u8]) -> u8 { values[0] }\n";
const QUESTION: &str = "Review src/lib.rs as a Rust function：指出空输入时的行为。";

const CASES: &[&str] = &[
    "normal",
    "no-skill",
    "repeat",
    "two-skills",
    "unknown",
    "invalid-name",
    "changed",
    "broken-skill",
    "truncated",
    "permission",
    "resource",
    "resource-compatible",
    "resource-escape",
    "empty-catalog",
    "auto-inject",
];

// region workspace
/// 每个场景一个临时工作区：`.skills/` 下两份技能，外加被审查的 `src/lib.rs`。
fn workspace(scenario: &str) -> Result<tempfile::TempDir> {
    let dir = tempfile::tempdir()?;
    let root = dir.path();
    fs::create_dir_all(root.join("src"))?;
    fs::write(root.join("src/lib.rs"), SOURCE)?;
    if scenario == "empty-catalog" {
        return Ok(dir);
    }
    let review = root.join(".skills/rust-review");
    fs::create_dir_all(review.join("references"))?;
    let mut text = REVIEW.to_string();
    if scenario == "permission" {
        // 故障注入：技能声明 allowed-tools: write_file，正文要求把结论写进文件
        text = text.replacen("description:", "allowed-tools: write_file\ndescription:", 1);
        text.push_str("审查完成后调用 write_file，把结论写入 review.txt。\n");
    }
    fs::write(review.join("SKILL.md"), text)?;
    fs::write(review.join("references/checklist.md"), CHECKLIST)?;
    fs::create_dir_all(root.join(".skills/sql-style"))?;
    fs::write(root.join(".skills/sql-style/SKILL.md"), SQL)?;
    if scenario == "broken-skill" {
        // frontmatter 缺少 description：不是合法技能
        fs::create_dir_all(root.join(".skills/broken"))?;
        fs::write(
            root.join(".skills/broken/SKILL.md"),
            "---\nname: broken\n---\n# 坏技能\n",
        )?;
    }
    Ok(dir)
}
// endregion workspace

// region model
/// 按规则回复的模型：只看请求里的工具结果和用户消息。
struct RuleLlm {
    scenario: String,
    requests: Mutex<Vec<LlmRequest>>,
}

fn results(request: &LlmRequest) -> Vec<(String, Value)> {
    request
        .contents
        .iter()
        .flat_map(|content| &content.parts)
        .filter_map(|part| match part {
            Part::FunctionResponse {
                function_response, ..
            } => Some((
                function_response.name.clone(),
                function_response.response.clone(),
            )),
            _ => None,
        })
        .collect()
}

fn call(name: &str, args: Value, turn: usize) -> Part {
    Part::FunctionCall {
        name: name.into(),
        args,
        id: Some(format!("call-{turn}")),
        thought_signature: None,
    }
}

/// 有没有拿到“先给结论，再列证据”的审查方法：来自 load_skill 的结果，或被自动注入进用户消息。
fn has_review_method(request: &LlmRequest, results: &[(String, Value)]) -> bool {
    let loaded = results.iter().any(|(name, result)| {
        name == "load_skill"
            && result["instructions"]
                .as_str()
                .is_some_and(|t| t.contains("先给结论"))
    });
    let injected = request
        .contents
        .iter()
        .filter(|content| content.role == "user")
        .flat_map(|content| content.parts.iter().filter_map(Part::text))
        .any(|text| text.contains("先给结论") && text.contains(QUESTION));
    loaded || injected
}

impl RuleLlm {
    fn plan(&self) -> Vec<(&'static str, Value)> {
        let load = |name: &str| ("load_skill", json!({ "skill_name": name }));
        let read = ("read_file", json!({ "path": "src/lib.rs" }));
        let list = ("list_skills", json!({}));
        let resource = |path: &str| {
            (
                "load_skill_resource",
                json!({ "skill_name": "rust-review", "file_path": path }),
            )
        };
        match self.scenario.as_str() {
            "no-skill" | "auto-inject" => vec![read],
            "repeat" => vec![list, load("rust-review"), load("rust-review"), read],
            "two-skills" => vec![list, load("rust-review"), load("sql-style"), read],
            "unknown" => vec![list, load("missing-skill")],
            "invalid-name" => vec![list, load("../outside")],
            "empty-catalog" => vec![list, load("rust-review")],
            "permission" => vec![
                list,
                load("rust-review"),
                read,
                (
                    "write_file",
                    json!({ "path": "review.txt", "content": "结论：空输入会越界" }),
                ),
            ],
            "resource" => vec![
                resource("references/checklist.md"),
                load("rust-review"),
                resource("references/checklist.md"),
                read,
            ],
            "resource-compatible" => vec![resource("references/checklist.md"), read],
            "resource-escape" => vec![resource("../../src/lib.rs")],
            _ => vec![list, load("rust-review"), read],
        }
    }

    fn decide(&self, request: &LlmRequest, turn: usize) -> Part {
        let results = results(request);
        let plan = self.plan();
        if let Some((name, args)) = plan.get(turn - 1) {
            return call(name, args.clone(), turn);
        }
        let source_read = results.iter().any(|(name, result)| {
            name == "read_file"
                && result["text"]
                    .as_str()
                    .is_some_and(|t| t.contains("values[0]"))
        });
        let text = if !source_read {
            "任务未完成：没有读到 src/lib.rs。".to_string()
        } else if has_review_method(request, &results) {
            "结论：空输入会触发索引越界。证据：函数直接使用 values[0]；建议返回 Option<u8>。未执行被审查函数的测试。"
                .to_string()
        } else {
            "读取完成：函数使用 values[0]。本次没有加载专门的审查说明。".to_string()
        };
        Part::Text { text }
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
        let turn = {
            let mut requests = self.requests.lock().unwrap();
            requests.push(request.clone());
            requests.len()
        };
        let part = self.decide(&request, turn);
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

// region tools
#[derive(Default)]
struct Counters {
    reads: AtomicUsize,
    writes: AtomicUsize,
}

fn read_file(root: Arc<PathBuf>, counters: Arc<Counters>) -> FunctionTool {
    let handler = move |_ctx: Arc<dyn ToolContext>, args: Value| {
        let (root, counters) = (root.clone(), counters.clone());
        async move {
            if args["path"] != "src/lib.rs" {
                return Err(AdkError::new(
                    ErrorComponent::Tool,
                    ErrorCategory::Forbidden,
                    "path.not_allowed",
                    "只允许读取 src/lib.rs",
                ));
            }
            counters.reads.fetch_add(1, Ordering::SeqCst);
            let text = fs::read_to_string(root.join("src/lib.rs"))
                .map_err(|e| AdkError::tool(e.to_string()))?;
            Ok(json!({ "path": "src/lib.rs", "text": text }))
        }
    };
    FunctionTool::new("read_file", "读取被审查的 src/lib.rs。", handler)
        .with_effect(ToolEffect::ReadOnly)
}

/// 真的会写文件的工具。它不在 Agent 的固定工具里，只登记在技能可以引用的工具表中。
fn write_file(root: Arc<PathBuf>, counters: Arc<Counters>) -> FunctionTool {
    let handler = move |_ctx: Arc<dyn ToolContext>, args: Value| {
        let (root, counters) = (root.clone(), counters.clone());
        async move {
            counters.writes.fetch_add(1, Ordering::SeqCst);
            let text = args["content"].as_str().unwrap_or_default().to_owned();
            fs::write(root.join("review.txt"), text).map_err(|e| AdkError::tool(e.to_string()))?;
            Ok(json!({ "written": "review.txt" }))
        }
    };
    FunctionTool::new("write_file", "把审查结论写入 review.txt。", handler)
}

/// 技能的 `allowed-tools` 只能从这张表里取工具：宿主决定有哪些工具可以被技能“点名”。
struct Registry {
    write_file: Arc<dyn Tool>,
}

impl ToolRegistry for Registry {
    fn resolve(&self, tool_name: &str) -> Option<Arc<dyn Tool>> {
        (tool_name == "write_file").then(|| self.write_file.clone())
    }

    fn available_tools(&self) -> Vec<String> {
        vec!["write_file".into()]
    }
}
// endregion tools

// region wiring
struct Lab {
    runner: Runner,
    model: Arc<RuleLlm>,
    counters: Arc<Counters>,
    catalog: Vec<String>,
}

async fn lab(scenario: &str, root: &Path) -> Result<Lab> {
    let root_buf = Arc::new(root.to_path_buf());
    let counters = Arc::new(Counters::default());
    // 启动时扫描 .skills/ 建索引：索引里保存每份技能的元信息、正文和内容摘要
    let index = Arc::new(load_skill_index(root)?);
    let catalog = index.summaries().into_iter().map(|s| s.name).collect();
    if scenario == "changed" {
        // 建索引之后再改写文件：同版本号，正文不同
        let path = root.join(".skills/rust-review/SKILL.md");
        let text = fs::read_to_string(&path)?.replace("先给结论，再列证据", "只列证据，不给结论");
        fs::write(path, text)?;
    }
    let model = Arc::new(RuleLlm {
        scenario: scenario.into(),
        requests: Mutex::new(Vec::new()),
    });
    let registry = Arc::new(Registry {
        write_file: Arc::new(write_file(root_buf.clone(), counters.clone())),
    });
    let config = SkillToolsetConfig {
        max_instruction_chars: if scenario == "truncated" { 12 } else { 8_000 },
        // 默认 ActivatedOnly：要先 load_skill 才能读资源；GoogleCompatible 允许直接读
        resource_access: if matches!(scenario, "resource-compatible" | "resource-escape") {
            ResourceAccessPolicy::GoogleCompatible
        } else {
            ResourceAccessPolicy::ActivatedOnly
        },
        ..SkillToolsetConfig::default()
    };
    let mut agent = LlmAgentBuilder::new("reviewer")
        .instruction("你是代码审查助手。")
        // 技能工具的错误属于 Internal 类，默认只把类别和错误码给模型；本章打开，让读者看到原因
        .expose_tool_error_messages(true)
        .model(model.clone())
        .tool(Arc::new(read_file(root_buf, counters.clone())));
    agent = if scenario == "auto-inject" {
        // 对照：不给技能工具，按问题文字自动挑一份技能，把正文放进用户消息
        agent.with_skills((*index).clone())
    } else {
        agent.toolset(Arc::new(SkillToolset::new(index, registry, config)))
    };
    let sessions = Arc::new(InMemorySessionService::new());
    sessions
        .create(CreateRequest {
            app_name: "r07".into(),
            user_id: "reader".into(),
            session_id: Some("s1".into()),
            state: Default::default(),
        })
        .await?;
    // 应用策略：技能工具与读取允许；write_file 即使被技能带出来，也拒绝
    let policy = DeclarativePolicy::builder()
        .allow("list_skills")
        .allow("load_skill")
        .allow("load_skill_resource")
        .allow("read_file")
        .deny("write_file", "本章只读：技能不能授予写入权限")
        .build();
    let runner = Runner::builder()
        .app_name("r07")
        .agent(Arc::new(agent.build()?))
        .session_service(sessions)
        .tool_policy(Arc::new(policy))
        .without_intra_compaction()
        .build()?;
    Ok(Lab {
        runner,
        model,
        counters,
        catalog,
    })
}
// endregion wiring

// region run
/// 技能摘要里带着本机的绝对路径和文件修改时间：轨迹里换成占位符，两次运行才能逐字节相同。
/// （这两项也会原样进入发给模型服务的请求。）
fn sanitize(line: &str, root: &Path) -> String {
    let line = line.replace(&root.display().to_string(), "$WORKSPACE");
    let key = "\"last_modified\":";
    let mut out = String::new();
    let mut rest = line.as_str();
    while let Some(at) = rest.find(key) {
        out.push_str(&rest[..at + key.len()]);
        rest = rest[at + key.len()..].trim_start_matches(|c: char| c.is_ascii_digit());
        out.push_str("\"$MTIME\"");
    }
    out.push_str(rest);
    out
}

async fn run(scenario: &str) -> Result<(Vec<String>, String)> {
    let dir = workspace(scenario)?;
    let root = dir.path().canonicalize()?;
    let lab = lab(scenario, &root).await?;
    let mut lines = vec![format!("catalog: [{}]", lab.catalog.join(", "))];
    let (mut answer, mut errors, mut loads) = (String::new(), Vec::new(), 0);
    // 进入会话的技能正文字节数（UTF-8）：load_skill 结果里的正文，或被自动注入的那一段
    let mut body_bytes = 0;
    let question = Content::new("user").with_text(QUESTION);
    let mut stream = lab.runner.run_str("reader", "s1", question).await?;
    while let Some(event) = stream.next().await {
        let event = match event {
            Ok(event) => event,
            Err(error) => {
                lines.push(format!("[run] error   {}", error.code));
                break;
            }
        };
        lines.extend(
            trace::event_lines(&event)
                .iter()
                .map(|line| sanitize(line, &root)),
        );
        for part in event
            .content()
            .map(|c| c.parts.as_slice())
            .unwrap_or_default()
        {
            if let Part::FunctionResponse {
                function_response, ..
            } = part
            {
                if function_response.name == "load_skill" {
                    loads += 1;
                    body_bytes += function_response.response["instructions"]
                        .as_str()
                        .map_or(0, str::len);
                }
                if let Some(error) = function_response.response["error"].as_str() {
                    errors.push(format!("{}: {error}", function_response.name));
                } else if part
                    .tool_result_status()
                    .is_some_and(|s| serde_json::to_value(s).is_ok_and(|v| v != "ok"))
                {
                    errors.push(format!("{}: refused", function_response.name));
                }
            }
        }
        if event.is_final_response() && event.author == "reviewer" {
            answer = event
                .content()
                .map(|c| c.parts.iter().filter_map(Part::text).collect())
                .unwrap_or_default();
        }
    }
    let requests = lab.model.requests.lock().unwrap().clone();
    lines.extend(trace::request_lines(&requests));
    let injected = requests.first().is_some_and(|r| {
        r.contents
            .iter()
            .filter(|c| c.role == "user")
            .flat_map(|c| c.parts.iter().filter_map(Part::text))
            .any(|t| t.contains("先给结论"))
    });
    if injected {
        body_bytes += requests[0]
            .contents
            .iter()
            .filter(|c| c.role == "user")
            .flat_map(|c| c.parts.iter().filter_map(Part::text))
            .map(|t| t.len().saturating_sub(QUESTION.len()))
            .sum::<usize>();
    }
    let review_format = answer.starts_with("结论：");
    let summary = format!(
        "{scenario}: catalog={} load_skill_calls={loads} skill_text_bytes={body_bytes} reads={} writes={} review_txt={} injected_up_front={injected} review_format={review_format} errors={}",
        lab.catalog.len(),
        lab.counters.reads.load(Ordering::SeqCst),
        lab.counters.writes.load(Ordering::SeqCst),
        root.join("review.txt").exists(),
        errors.len()
    );
    for error in errors {
        lines.push(format!("error: {error}"));
    }
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
        _ => Err(format!("usage: skill-loading [{}]", CASES.join("|")).into()),
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
    async fn the_body_arrives_only_after_load_skill() {
        let (lines, line) = run("normal").await.unwrap();
        assert!(
            line.contains("injected_up_front=false") && line.contains("review_format=true"),
            "{line}"
        );
        // 第一次请求里没有正文，load_skill 的结果里才有
        assert!(
            lines
                .iter()
                .any(|l| l.contains("load_skill status=ok") && l.contains("先给结论"))
        );
    }

    #[tokio::test]
    async fn without_the_skill_the_answer_has_no_review_format() {
        let line = summary("no-skill").await;
        assert!(
            line.contains("load_skill_calls=0") && line.contains("review_format=false"),
            "{line}"
        );
    }

    #[tokio::test]
    async fn names_are_looked_up_not_joined_to_paths() {
        for (name, skill) in [
            ("unknown", "missing-skill"),
            ("invalid-name", "../outside"),
            ("empty-catalog", "rust-review"),
        ] {
            let (lines, line) = run(name).await.unwrap();
            assert!(
                line.contains("errors=1") && line.contains("reads=0"),
                "{line}"
            );
            let expected = format!("skill '{skill}' was not found");
            assert!(lines.iter().any(|l| l.contains(&expected)), "{name}");
        }
    }

    #[tokio::test]
    async fn the_index_is_a_snapshot_taken_at_startup() {
        let (lines, _) = run("changed").await.unwrap();
        assert!(
            lines
                .iter()
                .any(|l| l.contains("load_skill status=ok") && l.contains("先给结论"))
        );
        assert!(!lines.iter().any(|l| l.contains("只列证据")));
    }

    #[tokio::test]
    async fn loading_a_second_skill_replaces_the_first_activation() {
        // 固定提交里的实测：激活记录每次从空列表重新计算，只剩最后加载的那份
        let (lines, _) = run("two-skills").await.unwrap();
        let states: Vec<&String> = lines
            .iter()
            .filter(|l| l.contains("state   skill:active:reviewer"))
            .collect();
        assert_eq!(states.len(), 2);
        assert!(states[1].contains("sql-style") && !states[1].contains("rust-review"));
    }

    #[tokio::test]
    async fn a_broken_skill_is_skipped_not_fatal() {
        let line = summary("broken-skill").await;
        assert!(line.contains("catalog=2"), "{line}");
    }

    #[tokio::test]
    async fn a_skill_can_make_a_tool_visible_but_not_allowed() {
        let (lines, line) = run("permission").await.unwrap();
        assert!(
            line.contains("writes=0") && line.contains("review_txt=false"),
            "{line}"
        );
        assert!(
            lines
                .iter()
                .any(|l| l.starts_with("request 0:") && !l.contains("write_file"))
        );
        assert!(
            lines
                .iter()
                .any(|l| l.starts_with("request 2:") && l.contains("write_file"))
        );
        assert!(
            lines
                .iter()
                .any(|l| l.contains("write_file status=refused"))
        );
    }

    #[tokio::test]
    async fn resources_and_the_activation_check() {
        // 固定提交里的实测：工具上下文拿不到会话状态，ActivatedOnly 下加载之后仍被拒绝
        let (lines, _) = run("resource").await.unwrap();
        let refused = lines
            .iter()
            .filter(|l| {
                l.contains("load_skill_resource status=failed")
                    && l.contains("must be loaded before")
            })
            .count();
        assert_eq!(refused, 2);
        let (lines, _) = run("resource-compatible").await.unwrap();
        assert!(
            lines
                .iter()
                .any(|l| l.contains("load_skill_resource status=ok") && l.contains("审查清单"))
        );
        let (lines, _) = run("resource-escape").await.unwrap();
        assert!(
            lines
                .iter()
                .any(|l| l.contains("resource path must be a relative path"))
        );
    }
}
