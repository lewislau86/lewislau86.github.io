//! G03（ADK-Rust 3.0 / adk-graph）：图并行、归并与子图。
//!
//! 发布前的两项检查（安全、许可证）并行运行，归并节点等两项都到齐后给出结论。
//! 节点是确定性规则，不调用模型。用法：graph-parallel-lab normal|failure|collision|subgraph|timeout
mod trace;

use std::{
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
    time::Duration,
};

use adk_graph::{
    checkpoint::MemoryCheckpointer,
    edge::{END, START},
    error::{GraphError, Result},
    graph::{CompiledGraph, NodeDefaults, StateGraph},
    node::{ExecutionConfig, NodeContext, NodeOutput},
    state::{State, StateSchema},
    stream::{StreamEvent, StreamMode},
    subgraph::SubgraphNode,
    timeout::{OnTimeout, TimeoutPolicy},
};
use futures::StreamExt;
use serde_json::{Value, json};

/// 记录每个检查节点真正执行了几次，用来观察失败后恢复时哪些节点重跑。
#[derive(Default)]
struct Runs {
    security: AtomicUsize,
    license: AtomicUsize,
}

/// 检查节点的行为：正常通过、第一次执行失败、或者执行得很慢。
#[derive(Clone, Copy, PartialEq)]
enum Mode {
    Pass,
    FailOnce,
    Slow,
}

// region checks
fn schema() -> StateSchema {
    StateSchema::builder()
        .channel("release")
        .channel("security")
        .channel("license")
        .channel("verdict")
        .list_channel("trace")
        .build()
}

/// 每项检查只写自己的通道，互不覆盖；归并节点读两个通道。
fn security(
    runs: Arc<Runs>,
    mode: Mode,
) -> impl Fn(NodeContext) -> std::pin::Pin<Box<dyn Future<Output = Result<NodeOutput>> + Send>>
+ Send
+ Sync {
    move |_ctx| {
        let runs = runs.clone();
        Box::pin(async move {
            let attempt = runs.security.fetch_add(1, Ordering::SeqCst) + 1;
            if mode == Mode::FailOnce && attempt == 1 {
                return Err(GraphError::NodeExecutionFailed {
                    node: "security".into(),
                    message: "scanner unavailable".into(),
                });
            }
            Ok(NodeOutput::new()
                .with_update(
                    "security",
                    json!({ "ok": true, "detail": "no known advisories" }),
                )
                .with_update("trace", json!("security")))
        })
    }
}

fn license(
    runs: Arc<Runs>,
    mode: Mode,
) -> impl Fn(NodeContext) -> std::pin::Pin<Box<dyn Future<Output = Result<NodeOutput>> + Send>>
+ Send
+ Sync {
    move |_ctx| {
        let runs = runs.clone();
        Box::pin(async move {
            runs.license.fetch_add(1, Ordering::SeqCst);
            if mode == Mode::Slow {
                tokio::time::sleep(Duration::from_millis(300)).await;
            }
            Ok(NodeOutput::new()
                .with_update("license", json!({ "ok": true, "detail": "Apache-2.0" }))
                .with_update("trace", json!("license")))
        })
    }
}
// endregion checks

// region merge
/// 归并是业务规则：两项都通过才是 ready；有一项不通过是 blocked；缺了一项是 incomplete，
/// 不能把“没有结果”当成“通过”。
async fn merge(ctx: NodeContext) -> Result<NodeOutput> {
    let ok = |key: &str| {
        ctx.get(key)
            .and_then(|v| v.get("ok"))
            .and_then(Value::as_bool)
    };
    let verdict = match (ok("security"), ok("license")) {
        (Some(true), Some(true)) => "ready",
        (Some(false), _) | (_, Some(false)) => "blocked",
        _ => "incomplete",
    };
    Ok(NodeOutput::new()
        .with_update("verdict", json!(verdict))
        .with_update("trace", json!("merge")))
}
// endregion merge

// region graph
/// plan 有两条出边：security 和 license 在同一个超步里并行运行；
/// merge 有两条入边，框架把它标成“等待节点”，两项都到齐后只运行一次。
fn release_graph(
    runs: Arc<Runs>,
    security_mode: Mode,
    license_mode: Mode,
) -> Result<CompiledGraph> {
    StateGraph::new(schema())
        .add_node_fn("plan", |_| async {
            Ok(NodeOutput::new().with_update("trace", json!("plan")))
        })
        .add_node_fn("security", security(runs.clone(), security_mode))
        .add_node_fn("license", license(runs, license_mode))
        .add_node_fn("merge", merge)
        .add_edge(START, "plan")
        .add_edge("plan", "security")
        .add_edge("plan", "license")
        .add_edge("security", "merge")
        .add_edge("license", "merge")
        .add_edge("merge", END)
        .compile()
}
// endregion graph

async fn run(
    graph: &CompiledGraph,
    thread: &str,
) -> (Vec<String>, std::result::Result<State, GraphError>) {
    let mut input = State::new();
    input.insert("release".into(), json!("v3.0.0"));
    let mut lines = Vec::new();
    let mut last = None;
    let mut stream =
        Box::pin(graph.stream(input, ExecutionConfig::new(thread), StreamMode::Updates));
    while let Some(event) = stream.next().await {
        match event {
            Ok(StreamEvent::StepComplete {
                step,
                nodes_executed,
            }) => lines.push(format!("step={step} ran={}", nodes_executed.join(","))),
            Ok(StreamEvent::Done { state, .. }) => last = Some(Ok(state)),
            Ok(_) => {}
            Err(error) => last = Some(Err(error)),
        }
    }
    (
        lines,
        last.unwrap_or_else(|| Err(GraphError::InvalidGraph("no result".into()))),
    )
}

fn verdict(result: &std::result::Result<State, GraphError>) -> String {
    match result {
        Ok(state) => format!(
            "verdict={}",
            state
                .get("verdict")
                .and_then(Value::as_str)
                .unwrap_or("none")
        ),
        Err(GraphError::NodeExecutionFailed { node, .. }) => {
            format!("error=node_failed node={node}")
        }
        Err(GraphError::NodeTimedOut { node, .. }) => format!("error=node_timed_out node={node}"),
        Err(error) => format!("error={error}"),
    }
}

fn counts(runs: &Runs) -> String {
    format!(
        "security_runs={} license_runs={}",
        runs.security.load(Ordering::SeqCst),
        runs.license.load(Ordering::SeqCst)
    )
}

async fn scenario(name: &str) -> Result<Vec<String>> {
    let mut out = Vec::new();
    let runs = Arc::new(Runs::default());
    match name {
        "normal" => {
            let graph = release_graph(runs.clone(), Mode::Pass, Mode::Pass)?;
            let (lines, result) = run(&graph, name).await;
            out.extend(lines);
            out.push(format!("{} {}", verdict(&result), counts(&runs)));
        }
        // region failure
        "failure" => {
            // 安全检查第一次失败：这一步的运行以错误结束，merge 没有运行；
            // 已经完成的许可证检查作为“待写入”记进检查点。同一线程再运行一次，只重跑失败的节点。
            let graph = release_graph(runs.clone(), Mode::FailOnce, Mode::Pass)?
                .with_checkpointer(MemoryCheckpointer::new());
            let (lines, first) = run(&graph, name).await;
            out.extend(lines);
            out.push(format!("first_run {} {}", verdict(&first), counts(&runs)));
            let resumed = graph.invoke(State::new(), ExecutionConfig::new(name)).await;
            out.push(format!("resumed {} {}", verdict(&resumed), counts(&runs)));
        }
        // endregion failure
        // region collision
        "collision" => {
            // 两个并行节点各自读到 count=0、各写 old+1：覆盖通道只留下一个值，丢了一次更新
            for (channel_kind, label) in [("overwrite", "overwrite"), ("counter", "counter")] {
                let schema = if channel_kind == "overwrite" {
                    StateSchema::builder().channel("count").build()
                } else {
                    StateSchema::builder().counter_channel("count").build()
                };
                let add_one = move |ctx: NodeContext| async move {
                    let old = ctx.get("count").and_then(Value::as_f64).unwrap_or(0.0);
                    let write = if channel_kind == "overwrite" {
                        json!(old + 1.0)
                    } else {
                        json!(1)
                    };
                    Ok(NodeOutput::new().with_update("count", write))
                };
                let graph = StateGraph::new(schema)
                    .add_node_fn("a", add_one)
                    .add_node_fn("b", add_one)
                    .add_edge(START, "a")
                    .add_edge(START, "b")
                    .add_edge("a", END)
                    .add_edge("b", END)
                    .compile()?;
                let mut input = State::new();
                input.insert("count".into(), json!(0));
                let state = graph.invoke(input, ExecutionConfig::new(label)).await?;
                out.push(format!("{label}: count={} expected=2", state["count"]));
            }
        }
        // endregion collision
        // region subgraph
        "subgraph" => {
            // 子图有自己的通道；isolated() 以后只交换显式写出的通道
            let inner = StateGraph::with_channels(&["text", "scratch", "score"])
                .add_node_fn("tokenize", |ctx: NodeContext| async move {
                    let text = ctx
                        .get("text")
                        .and_then(Value::as_str)
                        .unwrap_or_default()
                        .to_string();
                    Ok(NodeOutput::new()
                        .with_update("scratch", json!(text.split_whitespace().count())))
                })
                .add_node_fn("score", |ctx: NodeContext| async move {
                    let words = ctx.get("scratch").and_then(Value::as_u64).unwrap_or(0);
                    Ok(NodeOutput::new()
                        .with_update("score", json!(if words > 3 { "high" } else { "low" })))
                })
                .add_edge(START, "tokenize")
                .add_edge("tokenize", "score")
                .add_edge("score", END)
                .compile()?;
            let inner = Arc::new(inner);
            let parent = |output: &'static str| {
                StateGraph::with_channels(&["notes", "risk", "scratch"])
                    .add_node(
                        SubgraphNode::new("assess", inner.clone())
                            .isolated()
                            .with_input("notes", "text")
                            .with_output(output, "risk"),
                    )
                    .add_edge(START, "assess")
                    .add_edge("assess", END)
                    .compile()
            };
            let mut input = State::new();
            input.insert(
                "notes".into(),
                json!("breaking change in tool authorization path"),
            );
            let state = parent("score")?
                .invoke(input, ExecutionConfig::new("subgraph"))
                .await?;
            out.push(format!(
                "parent risk={} scratch_exported={}",
                state["risk"],
                state.get("scratch").is_some_and(|v| !v.is_null())
            ));
            // 输出映射写错了子图的通道名：父图编译时就被拒绝，不会等到运行时才发现值是空的
            let wrong = parent("scor");
            out.push(format!(
                "wrong_mapping rejected_at_compile={}",
                matches!(wrong, Err(GraphError::SubgraphChannelMismatch { .. }))
            ));
        }
        // endregion subgraph
        // region timeout
        "timeout" => {
            for (on_timeout, label) in [(OnTimeout::Fail, "fail"), (OnTimeout::Skip, "skip")] {
                let policy = TimeoutPolicy {
                    run_timeout: Some(Duration::from_millis(50)),
                    idle_timeout: None,
                    on_timeout,
                };
                let graph = release_graph(Arc::new(Runs::default()), Mode::Pass, Mode::Slow)?
                    .with_node_defaults(NodeDefaults::new().with_timeout(policy));
                let (_, result) = run(&graph, label).await;
                out.push(format!("on_timeout={label} {}", verdict(&result)));
            }
        }
        // endregion timeout
        other => {
            return Err(GraphError::InvalidGraph(format!(
                "unknown scenario {other}"
            )));
        }
    }
    Ok(out)
}

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let name = std::env::args().nth(1).unwrap_or_else(|| "normal".into());
    if !["normal", "failure", "collision", "subgraph", "timeout"].contains(&name.as_str()) {
        eprintln!("usage: graph-parallel-lab normal|failure|collision|subgraph|timeout");
        std::process::exit(2);
    }
    match scenario(&name).await {
        Ok(lines) => println!("{}", lines.join("\n")),
        Err(error) => {
            eprintln!("error: {error}");
            std::process::exit(1);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    async fn text(name: &str) -> String {
        scenario(name).await.unwrap().join("\n")
    }

    #[tokio::test]
    async fn both_checks_run_in_one_step_and_merge_runs_once() {
        let t = text("normal").await;
        assert!(t.contains("ran=license,security"), "{t}");
        assert!(
            t.contains("verdict=ready security_runs=1 license_runs=1"),
            "{t}"
        );
    }

    #[tokio::test]
    async fn a_failed_step_keeps_the_finished_sibling_and_reruns_only_the_failed_node() {
        let t = text("failure").await;
        assert!(
            t.contains("first_run error=node_failed node=security security_runs=1 license_runs=1"),
            "{t}"
        );
        assert!(
            t.contains("resumed verdict=ready security_runs=2 license_runs=1"),
            "{t}"
        );
    }

    #[tokio::test]
    async fn an_overwrite_channel_loses_a_parallel_update() {
        let t = text("collision").await;
        assert!(t.contains("overwrite: count=1.0 expected=2"), "{t}");
        assert!(t.contains("counter: count=2.0 expected=2"), "{t}");
    }

    #[tokio::test]
    async fn the_subgraph_exports_only_its_declared_outputs() {
        let t = text("subgraph").await;
        assert!(
            t.contains("parent risk=\"high\" scratch_exported=false"),
            "{t}"
        );
        assert!(t.contains("wrong_mapping rejected_at_compile=true"), "{t}");
    }

    #[tokio::test]
    async fn a_timeout_fails_or_skips_and_merge_does_not_mistake_absence_for_success() {
        let t = text("timeout").await;
        assert!(
            t.contains("on_timeout=fail error=node_timed_out node=license"),
            "{t}"
        );
        assert!(t.contains("on_timeout=skip verdict=incomplete"), "{t}");
    }
}
