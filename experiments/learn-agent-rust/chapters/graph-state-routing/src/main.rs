//! G01（ADK-Rust 3.0 / adk-graph）：图状态、条件路由与有界循环。
//!
//! 升级审查：准备初稿 → 检查等级 → 不够就修复再检查；达到要求就接受，修复额度用完就转人工。
//! 节点是确定性的业务规则，不调用模型。用法：graph-state-lab normal|exhausted|runaway|probes
mod trace;

use adk_graph::{
    checkpoint::MemoryCheckpointer,
    edge::{END, START},
    error::{GraphError, Result},
    graph::{CompiledGraph, StateGraph},
    node::{ExecutionConfig, NodeContext, NodeOutput},
    state::{State, StateSchema},
    stream::{StreamEvent, StreamMode},
};
use futures::StreamExt;
use serde_json::{Value, json};

const MAX_REPAIRS: u64 = 2;

// region state
/// 图状态由“通道”组成。每个通道有一个归并规则（reducer），决定节点写入的新值怎样与旧值合并：
/// 默认是覆盖；trace 用列表通道，每次写入追加一项；repairs 用计数通道，每次写入加到原值上。
fn schema() -> StateSchema {
    StateSchema::builder()
        .channel("draft")
        .channel("required")
        .counter_channel("repairs")
        .channel("outcome")
        .list_channel("trace")
        .build()
}

/// 读取一个等级字段。值不存在或不是非负整数都算契约错误，拒绝继续，
/// 而不是悄悄当成 0 走下去。计数通道按浮点数累加（写入 1，读出 1.0），所以这里按数值读取。
fn level(state: &State, key: &str) -> Result<u64> {
    let value = state
        .get(key)
        .ok_or_else(|| GraphError::NodeExecutionFailed {
            node: "state".into(),
            message: format!("{key} missing"),
        })?;
    match value.as_f64() {
        Some(n) if n >= 0.0 && n.fract() == 0.0 => Ok(n as u64),
        _ => Err(GraphError::NodeExecutionFailed {
            node: "state".into(),
            message: format!("{key} is not a level: {value}"),
        }),
    }
}
// endregion state

// region nodes
/// 每个节点：读取并校验输入，完成本步的业务变更，只通过 NodeOutput 写回更新。
async fn prepare(_ctx: NodeContext) -> Result<NodeOutput> {
    Ok(NodeOutput::new()
        .with_update("draft", json!(1))
        .with_update("trace", json!("prepare")))
}

async fn check(ctx: NodeContext) -> Result<NodeOutput> {
    // 只读状态、写一条轨迹；去哪里由条件边决定
    level(&ctx.state, "draft")?;
    level(&ctx.state, "required")?;
    Ok(NodeOutput::new().with_update("trace", json!("check")))
}

/// 修复节点自己决定下一步：额度还有就修复并回到 check，用完就转人工（with_goto）。
/// `improves=false` 模拟修复无效；`counts=false` 模拟忘了计数的 bug。
fn repair(
    improves: bool,
    counts: bool,
) -> impl Fn(NodeContext) -> std::pin::Pin<Box<dyn Future<Output = Result<NodeOutput>> + Send>>
+ Send
+ Sync {
    move |ctx: NodeContext| {
        Box::pin(async move {
            let draft = level(&ctx.state, "draft")?;
            let repairs = level(&ctx.state, "repairs").unwrap_or(0);
            let out = NodeOutput::new().with_update("trace", json!("repair"));
            if repairs >= MAX_REPAIRS {
                return Ok(out.with_goto(["handoff"]));
            }
            let out = if counts {
                out.with_update("repairs", json!(1))
            } else {
                out
            };
            let out = if improves {
                out.with_update("draft", json!(draft + 1))
            } else {
                out
            };
            Ok(out.with_goto(["check"]))
        })
    }
}

async fn finish(outcome: &'static str, node: &'static str) -> Result<NodeOutput> {
    Ok(NodeOutput::new()
        .with_update("outcome", json!(outcome))
        .with_update("trace", json!(node)))
}
// endregion nodes

// region graph
/// check 用条件边选择 accept / repair；repair 用 with_goto 选择 check / handoff。
fn review_graph(improves: bool, counts: bool) -> Result<CompiledGraph> {
    StateGraph::new(schema())
        .add_node_fn("prepare", prepare)
        .add_node_fn("check", check)
        .add_node_fn("repair", repair(improves, counts))
        .add_node_fn("accept", |_| finish("accepted", "accept"))
        .add_node_fn("handoff", |_| finish("needs_human", "handoff"))
        .add_edge(START, "prepare")
        .add_edge("prepare", "check")
        .add_conditional_edges(
            "check",
            |state: &State| {
                // 两个等级都有效且达到要求才接受；读不出等级时不能落到 accept
                match (level(state, "draft"), level(state, "required")) {
                    (Ok(draft), Ok(required)) if draft >= required => "accept".into(),
                    _ => "repair".into(),
                }
            },
            [("accept", "accept"), ("repair", "repair")],
        )
        .add_edge("accept", END)
        .add_edge("handoff", END)
        .compile()
}
// endregion graph

// region run
/// 用流式执行观察每个超步跑了哪些节点；结束后读最终状态。
async fn run(
    graph: &CompiledGraph,
    required: u64,
    thread: &str,
) -> (Vec<String>, std::result::Result<State, GraphError>) {
    let mut input = State::new();
    input.insert("required".into(), json!(required));
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
// endregion run

fn summary(name: &str, state: &State) -> String {
    let trace: Vec<&str> = state["trace"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .collect();
    format!(
        "scenario={name} outcome={} repairs={} draft={}\ntrace={}",
        state["outcome"].as_str().unwrap_or("none"),
        level(state, "repairs").unwrap_or(0),
        level(state, "draft").unwrap_or(0),
        trace.join(">")
    )
}

async fn scenario(name: &str) -> Result<String> {
    let mut out = Vec::new();
    match name {
        "normal" | "exhausted" => {
            let (required, improves) = if name == "normal" {
                (2, true)
            } else {
                (4, false)
            };
            let graph = review_graph(improves, true)?;
            let (lines, result) = run(&graph, required, name).await;
            out.extend(lines);
            out.push(summary(name, &result?));
        }
        "runaway" => {
            // 忘了计数的 bug：业务额度永远到不了，只能靠框架的超步上限停下
            let graph = review_graph(false, false)?
                .with_recursion_limit(12)
                .with_checkpointer(MemoryCheckpointer::new());
            let (lines, result) = run(&graph, 4, name).await;
            out.push(format!("steps_run={}", lines.len()));
            match result {
                Err(GraphError::RecursionLimitExceeded(limit)) => {
                    let saved = graph.get_state(name).await?.unwrap_or_default();
                    out.push(format!(
                        "recursion_limit={limit} error=RecursionLimitExceeded"
                    ));
                    out.push(format!(
                        "saved_state trace_len={} repairs={} outcome={}",
                        saved["trace"].as_array().map_or(0, Vec::len),
                        level(&saved, "repairs").unwrap_or(0),
                        saved
                            .get("outcome")
                            .and_then(Value::as_str)
                            .unwrap_or("none")
                    ));
                }
                other => out.push(format!("unexpected {other:?}")),
            }
        }
        "probes" => out.extend(probes().await?),
        other => {
            return Err(GraphError::InvalidGraph(format!(
                "unknown scenario {other}"
            )));
        }
    }
    Ok(out.join("\n"))
}

// region probes
fn noop(_ctx: NodeContext) -> std::pin::Pin<Box<dyn Future<Output = Result<NodeOutput>> + Send>> {
    Box::pin(async { Ok(NodeOutput::new()) })
}

fn write(
    key: &'static str,
    value: Value,
) -> impl Fn(NodeContext) -> std::pin::Pin<Box<dyn Future<Output = Result<NodeOutput>> + Send>>
+ Send
+ Sync {
    move |_ctx| {
        let value = value.clone();
        Box::pin(async move { Ok(NodeOutput::new().with_update(key, value)) })
    }
}

async fn probes() -> Result<Vec<String>> {
    let mut out = Vec::new();
    let cfg = |t: &str| ExecutionConfig::new(t);
    // 1. 建图时能发现的：悬空边、缺少起点
    let dangling = StateGraph::with_channels(&["x"])
        .add_node_fn("a", noop)
        .add_edge(START, "a")
        .add_edge("a", "missing")
        .compile();
    out.push(format!(
        "probe=dangling_edge rejected_at_compile={}",
        dangling.is_err()
    ));
    let no_start = StateGraph::with_channels(&["x"])
        .add_node_fn("a", noop)
        .add_edge("a", END)
        .compile();
    out.push(format!(
        "probe=missing_start rejected_at_compile={}",
        no_start.is_err()
    ));
    // 2. 运行时才能发现的：with_goto 指向不存在的节点、条件路由返回未声明的键
    let bad_goto = StateGraph::with_channels(&["x"])
        .add_node_fn("a", |_| async {
            Ok(NodeOutput::new()
                .with_update("x", json!(1))
                .with_goto(["chek"]))
        })
        .add_edge(START, "a")
        .compile()?;
    let r = bad_goto.invoke(State::new(), cfg("bad_goto")).await;
    out.push(format!(
        "probe=bad_goto rejected_at_run={}",
        matches!(r, Err(GraphError::UnknownRouteTarget { .. }))
    ));
    let unmapped = StateGraph::with_channels(&["x"])
        .add_node_fn("a", noop)
        .add_node_fn("b", noop)
        .add_edge(START, "a")
        .add_conditional_edges("a", |_: &State| "c".to_string(), [("b", "b")])
        .add_edge("b", END)
        .compile()?;
    let r = unmapped.invoke(State::new(), cfg("unmapped")).await;
    out.push(format!(
        "probe=unmapped_route rejected_at_run={}",
        matches!(r, Err(GraphError::UnknownRouteTarget { .. }))
    ));
    // 3. 没有出边的节点：这条分支就此结束，运行正常完成
    let no_edge = StateGraph::with_channels(&["x"])
        .add_node_fn("a", write("x", json!(1)))
        .add_edge(START, "a")
        .compile()?;
    let s = no_edge.invoke(State::new(), cfg("no_edge")).await?;
    out.push(format!("probe=no_edge completed=true x={}", s["x"]));
    // 4. 一个节点两条普通出边：两个后继在下一个超步都运行（并行），不是二选一
    let two = StateGraph::new(StateSchema::builder().list_channel("ran").build())
        .add_node_fn("a", write("ran", json!("a")))
        .add_node_fn("b", write("ran", json!("b")))
        .add_node_fn("c", write("ran", json!("c")))
        .add_edge(START, "a")
        .add_edge("a", "b")
        .add_edge("a", "c")
        .add_edge("b", END)
        .add_edge("c", END)
        .compile()?;
    let s = two.invoke(State::new(), cfg("two_edges")).await?;
    out.push(format!("probe=two_edges ran={}", s["ran"]));
    // 5. 写错通道名：默认按“覆盖”收下，不报错；打开严格通道才拒绝
    let typo = || {
        StateGraph::new(StateSchema::builder().list_channel("trace").build())
            .add_node_fn("a", |_| async {
                Ok(NodeOutput::new().with_update("trace", json!("a")))
            })
            .add_node_fn("b", |_| async {
                // 把 trace 拼成了 traces：这一项进了一个新的覆盖通道，列表里少了 b
                Ok(NodeOutput::new().with_update("traces", json!("b")))
            })
            .add_edge(START, "a")
            .add_edge("a", "b")
            .add_edge("b", END)
    };
    let s = typo().compile()?.invoke(State::new(), cfg("typo")).await?;
    out.push(format!(
        "probe=typo_channel trace={} traces={}",
        s["trace"], s["traces"]
    ));
    let r = typo()
        .compile()?
        .with_strict_channels()
        .invoke(State::new(), cfg("strict"))
        .await;
    out.push(format!(
        "probe=strict_channels rejected={}",
        matches!(r, Err(GraphError::UndeclaredChannel { .. }))
    ));
    // 6. 节点拿到的是状态的副本：改本地副本不影响图状态，只有 NodeOutput 里的更新才生效
    let local = StateGraph::with_channels(&["x"])
        .add_node_fn("a", |mut ctx: NodeContext| async move {
            ctx.state.insert("x".into(), json!("changed locally"));
            Ok(NodeOutput::new())
        })
        .add_edge(START, "a")
        .add_edge("a", END)
        .compile()?;
    let mut input = State::new();
    input.insert("x".into(), json!("original"));
    let s = local.invoke(input, cfg("local")).await?;
    out.push(format!("probe=local_mutation x={}", s["x"]));
    // 7. 输入不符合契约：节点拒绝继续，运行以错误结束
    let graph = review_graph(true, true)?;
    let mut input = State::new();
    input.insert("required".into(), json!("high"));
    let r = graph.invoke(input, cfg("malformed")).await;
    out.push(format!(
        "probe=malformed_required rejected={}",
        matches!(r, Err(GraphError::NodeExecutionFailed { .. }))
    ));
    // 8. 计数通道按浮点数累加
    let counter = StateGraph::new(StateSchema::builder().counter_channel("n").build())
        .add_node_fn("a", write("n", json!(1)))
        .add_node_fn("b", write("n", json!(1)))
        .add_edge(START, "a")
        .add_edge("a", "b")
        .add_edge("b", END)
        .compile()?;
    let s = counter.invoke(State::new(), cfg("counter")).await?;
    out.push(format!("probe=counter_channel n={}", s["n"]));
    Ok(out)
}
// endregion probes

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let name = std::env::args().nth(1).unwrap_or_else(|| "normal".into());
    if !["normal", "exhausted", "runaway", "probes"].contains(&name.as_str()) {
        eprintln!("usage: graph-state-lab normal|exhausted|runaway|probes");
        std::process::exit(2);
    }
    match scenario(&name).await {
        Ok(text) => println!("{text}"),
        Err(error) => {
            eprintln!("error: {error}");
            std::process::exit(1);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    async fn final_state(required: u64, improves: bool) -> State {
        let graph = review_graph(improves, true).unwrap();
        run(&graph, required, "test").await.1.unwrap()
    }

    #[tokio::test]
    async fn one_repair_reaches_the_requirement() {
        let s = final_state(2, true).await;
        assert_eq!(s["outcome"], "accepted");
        assert_eq!(level(&s, "repairs").unwrap(), 1);
    }

    #[tokio::test]
    async fn the_business_budget_hands_off_and_the_graph_still_completes() {
        let s = final_state(4, false).await;
        assert_eq!(
            (s["outcome"].as_str(), level(&s, "repairs").unwrap()),
            (Some("needs_human"), 2)
        );
    }

    #[tokio::test]
    async fn only_the_recursion_limit_stops_a_loop_that_never_counts() {
        let graph = review_graph(false, false).unwrap().with_recursion_limit(12);
        let (_, r) = run(&graph, 4, "runaway").await;
        assert!(matches!(r, Err(GraphError::RecursionLimitExceeded(12))));
    }

    #[tokio::test]
    async fn every_probe_reports_its_expected_boundary() {
        let lines = probes().await.unwrap().join("\n");
        for expected in [
            "dangling_edge rejected_at_compile=true",
            "missing_start rejected_at_compile=true",
            "bad_goto rejected_at_run=true",
            "unmapped_route rejected_at_run=true",
            "no_edge completed=true",
            "two_edges ran=[\"a\",\"b\",\"c\"]",
            "strict_channels rejected=true",
            "local_mutation x=\"original\"",
            "malformed_required rejected=true",
            "counter_channel n=2.0",
        ] {
            assert!(lines.contains(expected), "{expected}\n{lines}");
        }
    }
}
