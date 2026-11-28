//! D02（ADK-Rust 3.0）：提示链与条件路由。
//!
//!   cargo run --locked                 全部场景的摘要
//!   cargo run --locked -- stale        某个场景的完整轨迹（场景名见 CASES）
//!
//! 用户交来一个文件：先按类型路由到对应的处理链，链里依次“抽取 → 质量门 → 写报告”。
//! 路由有三种：模型给一个标签（`LlmConditionalAgent`）、代码按文件名判断（`ConditionalAgent`）、
//! 模型做一个带置信度的类型化决定（`DecisionAgent`）。抽取用 `output_schema` 约束成 JSON，
//! 质量门是一个 `CustomAgent`：产物必须属于这次输入的修订，否则 escalate，写报告那一步不再运行。
//! 模型是按规则回复的替身，只看自己收到的请求。
mod trace;

use std::sync::{Arc, Mutex};

use adk_agent::{
    ConditionalAgent, CustomAgent, DecisionAgent, LlmAgentBuilder, LlmConditionalAgent,
    SequentialAgent,
};
use adk_core::{
    Agent, Content, Event, FinishReason, InvocationContext, Llm, LlmRequest, LlmResponse,
    LlmResponseStream, Part,
};
use adk_runner::Runner;
use adk_session::{CreateRequest, InMemorySessionService, SessionService};
use async_trait::async_trait;
use futures::StreamExt;
use serde_json::{Value, json};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

const README: &str = "# demo\n目标版本：3.0\n";
const README_NO_VERSION: &str = "# demo\n（这一版还没写目标版本）\n";
const README_V31: &str = "# demo\n目标版本：3.1\n";
const CARGO: &str = "[package]\nname = \"demo\"\n[package.metadata.ci]\ntest = \"cargo test\"\n";
const LICENSE: &str = "MIT License\nCopyright (c) demo\n";

const CASES: &[&str] = &[
    "readme",
    "cargo",
    "unknown",
    "substring-trap",
    "rule-router",
    "rule-router-other",
    "low-confidence",
    "missing-field",
    "schema-retry",
    "stale",
];

/// 用户消息：第一行“文件：名字 修订：rN”，后面是文件内容。
fn message(file: &str, revision: &str, body: &str) -> String {
    format!("文件：{file} 修订：{revision}\n{body}")
}

fn text_of(content: &Content) -> String {
    content
        .parts
        .iter()
        .filter_map(Part::text)
        .collect::<Vec<_>>()
        .join("\n")
}

// region model
/// 替身模型，按请求判断自己在扮演哪一步：
/// 路由分类（只回一个标签）、类型化决定（回 JSON）、抽取（回 JSON）、写报告。
struct RuleLlm {
    scenario: String,
    requests: Mutex<Vec<String>>,
}

impl RuleLlm {
    fn answer(&self, request: &LlmRequest) -> String {
        let all = request
            .contents
            .iter()
            .map(text_of)
            .collect::<Vec<_>>()
            .join("\n");
        // 历史里可能有好几次运行的输入：正常取最后一个文件名和修订；
        // stale 场景里模型偷懒，照抄了历史里第一个出现的修订
        let files: Vec<&str> = all
            .lines()
            .filter_map(|l| {
                l.split_once("文件：")
                    .map(|(_, r)| r.split(' ').next().unwrap_or(""))
            })
            .collect();
        let file = files.last().copied().unwrap_or_default().to_owned();
        let revisions: Vec<String> = all
            .lines()
            .filter_map(|l| l.split_once("修订：").map(|(_, r)| r.trim().to_owned()))
            .collect();
        let revision = if self.scenario == "stale" {
            revisions.first()
        } else {
            revisions.last()
        }
        .cloned()
        .unwrap_or_default();
        if all.contains("只回答类别") {
            self.requests.lock().unwrap().push("route".into());
            // 分类：README → readme，Cargo.toml → cargo，其他 → other；
            // substring-trap 里模型把话说长了：“不是 readme，是 license”
            return match (self.scenario.as_str(), file.as_str()) {
                ("substring-trap", _) => "不是 readme，是 license".into(),
                (_, "README.md") => "readme".into(),
                (_, "Cargo.toml") => "cargo".into(),
                _ => "other".into(),
            };
        }
        if all.contains("Reply with only a JSON object") {
            self.requests.lock().unwrap().push("decide".into());
            let (choice, confidence) = match file.as_str() {
                "Cargo.toml" => ("cargo", 0.92),
                _ => ("readme", 0.3),
            };
            return json!({ "choice": choice, "rationale": format!("文件名是 {file}"), "confidence": confidence })
                .to_string();
        }
        if all.contains("抽取成 JSON") {
            self.requests.lock().unwrap().push("extract".into());
            let (kind, value) = if all.contains("[package]") {
                (
                    "cargo",
                    all.lines()
                        .find_map(|l| l.strip_prefix("test = \""))
                        .map(|v| v.trim_end_matches('"').to_owned()),
                )
            } else {
                (
                    "readme",
                    all.lines()
                        .find_map(|l| l.strip_prefix("目标版本："))
                        .map(str::to_owned),
                )
            };
            // 资料里没有要的字段，就照实不写；output_schema 会判它不合格。
            // schema-retry 场景里第一次漏写了 value，收到纠正提示后补上
            let corrected = all.contains("did not match the required schema");
            let mut artifact = json!({ "source": file, "revision": revision, "kind": kind });
            if let Some(value) = value
                && (self.scenario != "schema-retry" || corrected)
            {
                artifact["value"] = json!(value);
            }
            return artifact.to_string();
        }
        self.requests.lock().unwrap().push("render".into());
        let artifact: Value = all
            .lines()
            .find_map(|l| l.strip_prefix("产物："))
            .and_then(|l| serde_json::from_str(l).ok())
            .unwrap_or(Value::Null);
        format!(
            "报告：{} 的 {} 是 {}（修订 {}）",
            artifact["source"].as_str().unwrap_or("?"),
            if artifact["kind"] == "cargo" {
                "测试命令"
            } else {
                "目标版本"
            },
            artifact["value"].as_str().unwrap_or("?"),
            artifact["revision"].as_str().unwrap_or("?")
        )
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
        let mut response = LlmResponse::new(Content::new("model").with_text(self.answer(&request)));
        response.finish_reason = Some(FinishReason::Stop);
        response.turn_complete = true;
        Ok(Box::pin(futures::stream::iter([Ok(response)])))
    }
}
// endregion model

// region chain
/// 抽取的产物：必须带来源、修订、类别和值。`output_schema` 不通过就重试，
/// 重试用完仍不通过，`output_key` 不写，会话状态里保留的还是上一次的值。
fn artifact_schema() -> Value {
    json!({
        "type": "object",
        "properties": {
            "source": { "type": "string" },
            "revision": { "type": "string" },
            "kind": { "type": "string", "enum": ["readme", "cargo"] },
            "value": { "type": "string" }
        },
        "required": ["source", "revision", "kind", "value"]
    })
}

/// 质量门：产物必须存在，属于这次输入的文件与修订，类别与本链一致；否则把事件标成
/// escalate（上报，让链停下），写报告那一步不再运行。
/// 注意：抽取失败时这次运行已经报错结束；会话状态里留着的是上一次运行的产物，所以要比对修订。
fn gate(name: &str, kind: &'static str) -> Result<Arc<dyn Agent>> {
    let author = name.to_owned();
    Ok(Arc::new(
        CustomAgent::builder(name)
            .handler(move |ctx: Arc<dyn InvocationContext>| {
                let author = author.clone();
                async move {
                    let input = text_of(ctx.user_content());
                    let revision = input
                        .lines()
                        .find_map(|l| l.split_once("修订：").map(|(_, r)| r.trim().to_owned()))
                        .unwrap_or_default();
                    let file = input
                        .lines()
                        .find_map(|l| l.strip_prefix("文件："))
                        .and_then(|r| r.split(' ').next())
                        .unwrap_or_default()
                        .to_owned();
                    let artifact: Option<Value> = ctx
                        .session()
                        .state()
                        .get("artifact")
                        .and_then(|v| v.as_str().and_then(|s| serde_json::from_str(s).ok()));
                    let verdict = match &artifact {
                        None => Err("missing_artifact".to_string()),
                        Some(a) if a["revision"] != json!(revision) => Err(format!(
                            "stale_artifact:{}",
                            a["revision"].as_str().unwrap_or("?")
                        )),
                        Some(a) if a["source"] != json!(file) || a["kind"] != json!(kind) => Err(
                            format!("wrong_input:{}", a["source"].as_str().unwrap_or("?")),
                        ),
                        Some(_) => Ok(()),
                    };
                    let mut event = Event::new(ctx.invocation_id());
                    event.author = author;
                    let text = match verdict {
                        Ok(()) => "gate:passed".to_string(),
                        Err(reason) => {
                            event.actions.escalate = true;
                            format!("gate:{reason}")
                        }
                    };
                    event.llm_response.content = Some(Content::new("model").with_text(text));
                    Ok(Box::pin(futures::stream::iter([Ok(event)])) as adk_core::EventStream)
                }
            })
            .build()?,
    ))
}

/// 一条处理链：抽取 → 质量门 → 写报告。
fn chain(kind: &str, model: Arc<RuleLlm>) -> Result<Arc<dyn Agent>> {
    let extract = LlmAgentBuilder::new(format!("{kind}_extract"))
        .instruction("把用户给的文件抽取成 JSON：source、revision、kind、value。")
        .model(model.clone())
        .output_schema(artifact_schema())
        .output_max_retries(1)
        .output_key("artifact")
        .build()?;
    let render = LlmAgentBuilder::new(format!("{kind}_render"))
        .instruction("根据产物写一句报告。\n产物：{artifact}")
        .model(model)
        .build()?;
    Ok(Arc::new(SequentialAgent::new(
        format!("{kind}_chain"),
        vec![
            Arc::new(extract),
            gate(
                &format!("{kind}_gate"),
                if kind == "cargo" { "cargo" } else { "readme" },
            )?,
            Arc::new(render),
        ],
    )))
}

/// 兜底：不认识的输入，请用户补充，不进任何处理链。
fn needs_input() -> Result<Arc<dyn Agent>> {
    Ok(Arc::new(
        CustomAgent::builder("needs_input")
            .handler(|ctx: Arc<dyn InvocationContext>| async move {
                let mut event = Event::new(ctx.invocation_id());
                event.author = "needs_input".into();
                event.llm_response.content = Some(
                    Content::new("model").with_text("needs_input：请交 README.md 或 Cargo.toml"),
                );
                Ok(Box::pin(futures::stream::iter([Ok(event)])) as adk_core::EventStream)
            })
            .build()?,
    ))
}
// endregion chain

// region routers
fn llm_router(model: Arc<RuleLlm>) -> Result<Arc<dyn Agent>> {
    Ok(Arc::new(
        LlmConditionalAgent::builder("router", model.clone())
            .instruction("这个文件属于哪一类：readme、cargo 或 other？只回答类别。")
            .route("readme", chain("readme", model.clone())?)
            .route("cargo", chain("cargo", model)?)
            .default_route(needs_input()?)
            .build()?,
    ))
}

/// 代码按文件名路由，不调用模型。`ConditionalAgent` 只有两个分支，三路就嵌套一层：
/// Cargo.toml → cargo 链；否则再判断 README.md → readme 链，其余 → 兜底。
fn rule_router(model: Arc<RuleLlm>) -> Result<Arc<dyn Agent>> {
    let is = |name: &'static str| {
        move |ctx: &dyn InvocationContext| {
            text_of(ctx.user_content()).starts_with(&format!("文件：{name} "))
        }
    };
    let readme_or_other = ConditionalAgent::new(
        "router_readme",
        is("README.md"),
        chain("readme", model.clone())?,
    )
    .with_else(needs_input()?);
    Ok(Arc::new(
        ConditionalAgent::new("router", is("Cargo.toml"), chain("cargo", model)?)
            .with_else(Arc::new(readme_or_other)),
    ))
}

/// 模型做类型化决定：只能在列出的选项里选，并给出置信度；低于门槛走兜底。
fn decision_router(model: Arc<RuleLlm>) -> Result<Arc<dyn Agent>> {
    Ok(Arc::new(
        DecisionAgent::builder("router", model.clone())
            .instruction("这个文件该交给哪条处理链？")
            .route("readme", "项目说明 README", chain("readme", model.clone())?)
            .route("cargo", "Cargo 清单", chain("cargo", model)?)
            .fallback(needs_input()?)
            .min_confidence(0.6)
            .output_key("route")
            .build()?,
    ))
}
// endregion routers

// region run
async fn run(scenario: &str) -> Result<(Vec<String>, String)> {
    let model = Arc::new(RuleLlm {
        scenario: scenario.into(),
        requests: Mutex::new(Vec::new()),
    });
    let (kind, agent) = match scenario {
        "rule-router" | "rule-router-other" => ("rule", rule_router(model.clone())?),
        "low-confidence" => ("decision", decision_router(model.clone())?),
        _ => ("llm", llm_router(model.clone())?),
    };
    let inputs: Vec<String> = match scenario {
        "readme" | "schema-retry" => vec![message("README.md", "r1", README)],
        "cargo" | "rule-router" => vec![message("Cargo.toml", "r1", CARGO)],
        "rule-router-other" => vec![message("LICENSE", "r1", LICENSE)],
        "unknown" => vec![message("logo.png", "r1", "(二进制)")],
        "substring-trap" => vec![message("LICENSE", "r1", LICENSE)],
        "low-confidence" => vec![message("notes.md", "r1", "# 会议记录\n")],
        "missing-field" => vec![message("README.md", "r1", README_NO_VERSION)],
        // 同一个会话里先交 r1，再交 r2（目标版本改成了 3.1）
        _ => vec![
            message("README.md", "r1", README),
            message("README.md", "r2", README_V31),
        ],
    };
    let sessions = Arc::new(InMemorySessionService::new());
    sessions
        .create(CreateRequest {
            app_name: "d02".into(),
            user_id: "user".into(),
            session_id: Some("s1".into()),
            state: Default::default(),
        })
        .await?;
    let runner = Runner::builder()
        .app_name("d02")
        .agent(agent)
        .session_service(sessions)
        .without_intra_compaction()
        .build()?;
    let mut lines = Vec::new();
    let (mut route, mut gate_result, mut last, mut agents) = (
        String::from("-"),
        String::from("-"),
        String::new(),
        Vec::<String>::new(),
    );
    for input in &inputs {
        lines.push(format!(
            "--- run: {}",
            input.lines().next().unwrap_or_default()
        ));
        let (mut route_now, mut gate_now) = (String::from("-"), String::from("-"));
        agents.clear();
        let mut stream = runner
            .run_with_config(
                "user".try_into()?,
                "s1".try_into()?,
                Content::new("user").with_text(input),
                None,
            )
            .await?;
        while let Some(event) = stream.next().await {
            let event = match event {
                Ok(event) => event,
                Err(error) => {
                    lines.push(format!("[error] {error}"));
                    last = format!("error:{error}");
                    break;
                }
            };
            lines.extend(trace::event_lines(&event));
            if event.author != "user" && !agents.contains(&event.author) {
                agents.push(event.author.clone());
            }
            if let Some(chain) = event
                .author
                .strip_suffix("_extract")
                .or(event.author.strip_suffix("_gate"))
            {
                route_now = chain.to_owned();
            }
            if event.author == "needs_input" {
                route_now = "needs_input".into();
            }
            if event.actions.escalate {
                lines.push(format!("[{}] escalate", event.author));
            }
            if let Some(text) = event.content().map(text_of).filter(|t| !t.is_empty()) {
                if let Some(g) = text.strip_prefix("gate:") {
                    gate_now = g.to_owned();
                }
                last = text;
            }
        }
        route = route_now;
        gate_result = gate_now;
    }
    let calls = model.requests.lock().unwrap().clone();
    lines.push(format!("model calls: {}", calls.join(",")));
    let outcome = if last.starts_with("报告：") {
        "report".to_string()
    } else if last.starts_with("needs_input") {
        "needs_input".to_string()
    } else if last.starts_with("error:") {
        "error".to_string()
    } else if gate_result != "-" && gate_result != "passed" {
        "stopped".to_string()
    } else {
        "other".to_string()
    };
    lines.push(format!("last: {last}"));
    let summary = format!(
        "{scenario}: router={kind} route={route} agents=[{}] model_calls=[{}] gate={gate_result} outcome={outcome}",
        agents.join(","),
        calls.join(",")
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
        _ => Err(format!("usage: prompt-chaining-routing [{}]", CASES.join("|")).into()),
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
    async fn each_file_type_goes_down_its_own_chain() {
        assert!(
            summary("readme")
                .await
                .ends_with("gate=passed outcome=report")
        );
        assert!(summary("cargo").await.contains("route=cargo"));
        assert!(summary("unknown").await.ends_with("outcome=needs_input"));
        assert!(
            summary("rule-router")
                .await
                .contains("model_calls=[extract,render]")
        );
        assert!(
            summary("rule-router-other")
                .await
                .contains("model_calls=[] gate=- outcome=needs_input")
        );
    }

    #[tokio::test]
    async fn a_label_containing_a_route_name_is_routed_there() {
        let line = summary("substring-trap").await;
        assert!(line.contains("route=readme"), "{line}");
        assert!(line.ends_with("outcome=error"), "{line}");
    }

    #[tokio::test]
    async fn the_schema_retries_once_then_stops_the_chain() {
        assert!(
            summary("schema-retry")
                .await
                .contains("model_calls=[route,extract,extract,render]")
        );
        assert!(
            summary("missing-field")
                .await
                .ends_with("gate=- outcome=error")
        );
    }

    #[tokio::test]
    async fn the_gate_and_the_decision_threshold_stop_bad_inputs() {
        assert!(
            summary("stale")
                .await
                .ends_with("gate=stale_artifact:r1 outcome=stopped")
        );
        assert!(
            summary("low-confidence")
                .await
                .contains("route=needs_input")
        );
    }
}
