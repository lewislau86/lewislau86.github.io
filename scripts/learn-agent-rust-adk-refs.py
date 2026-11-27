"""Generate the “在 ADK-Rust 源码里” section of Learn Agent by Rust chapters (ADK-Rust 3.0).

每个已迁移到 ADK-Rust 3.0 的章节有一小节，把本章用到的框架行为对应到固定提交的源码行，
让读者看到 Runner、受控工具路径等“框架替你做的事”具体写在哪里。
正文里 `<!-- adk-refs:start -->` 与 `<!-- adk-refs:end -->` 之间的内容由本脚本整段重写，不要手改；
标记不存在时插在“## 本章结论”之前。只处理 lessons.json 里 stack 为 adk3 的章节。

用法：
    python3 scripts/fetch-adk-rust.py .cache/adk-rust          # 先取固定提交的源码（只需一次）
    python3 scripts/learn-agent-rust-adk-refs.py --check       # 只检查每个名字找不找得到、正文是否过期
    python3 scripts/learn-agent-rust-adk-refs.py               # 生成
源码目录用环境变量 ADK_RUST_SRC 或 --src 指定，默认 .cache/adk-rust。

SPEC 每章：导语，以及若干行 (本章内容, 文件, 定位, 对照要点)。定位写法：
    "fn 名字" / "struct 名字" / "enum 名字" / "trait 名字" / "const 名字"   顶层或任意缩进的第一个定义
    "类型::方法"                                                           impl 类型 之后的第一个 fn 方法
    ("grep", 正则)                                                         第一处匹配的行
找不到的名字不会中断：其余照常生成，结束时列出问题并以状态码 1 退出；有问题的章节保留原来的一节。
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import learn_agent_rust_adk as adk  # noqa: E402

DOCS = adk.ROOT / "docs/learn-agent-rust"
LESSONS = adk.ROOT / "scripts/learn-agent-rust-lessons.json"
START, END = "<!-- adk-refs:start -->", "<!-- adk-refs:end -->"
BLOB = f"{adk.BASELINE['repository']}/blob/{adk.BASELINE['rev']}/"

SPEC = {
    "tools-and-graph": ("本章用到的工具注册、调用 ID 配对和循环上限，在 ADK-Rust 里分布在这几处：", [
        ("把普通异步函数注册成工具", "adk-tool/src/function_tool.rs", "FunctionTool::new",
         "名字、描述和处理函数组成一个 `Tool`；参数 schema 由 `with_parameters_schema` 另行声明"),
        ("工具的副作用声明", "adk-core/src/tool.rs", "enum ToolEffect",
         "只有 `ReadOnly` / `Idempotent` 会被重试；未声明的工具按 `NonIdempotent` 只执行一次"),
        ("同一轮多个调用怎样执行", "adk-core/src/tool.rs", "enum ToolExecutionStrategy",
         "默认 `Sequential` 按模型给出的顺序逐个执行；`Auto` 只重叠相邻的只读且可并发的调用"),
        ("模型往返的次数上限", "adk-agent/src/llm_agent.rs", "LlmAgentBuilder::max_iterations",
         "对应本章循环的停止条件；默认 100"),
        ("每次工具调用都经过的一条受控路径", "adk-core/src/governance.rs", "fn authorize_tool_call",
         "策略、审批、预算都在这里依次检查，第 3、4 章展开"),
        ("从用户输入开始一次运行", "adk-runner/src/runner.rs", "Runner::run",
         "运行入口（再交给 `run_with_config`）：加载会话、运行 Agent、逐条保存事件；本章的轨迹就是它产出的事件流"),
        ("工具失败时交给模型多少细节", "adk-core/src/tool_response.rs", "fn tool_error_response",
         "参数错误和拒绝类错误带消息；其余默认只给类别和错误码，`expose_message` 为真时才带原文"),
        ("把 Agent 变成图节点", "adk-graph/src/node.rs", "AgentNode::new",
         "默认从 `messages` / `input` 取输入；本章用 `with_output_mapper` 把回答写进图状态"),
    ]),
    "architecture-and-setup": ("本章接线用到的几个部件，在 ADK-Rust 里的位置：", [
        ("脚本模型", "adk-model/src/scripted.rs", ("grep", r"^    async fn generate_content\("),
         "每次调用模型时先记下收到的请求，再取出下一条预先写好的回复；脚本用完就报错"),
        ("工具", "adk-tool/src/function_tool.rs", "FunctionTool::new",
         "名字、说明和处理函数组成一个工具"),
        ("Agent", "adk-agent/src/llm_agent.rs", "LlmAgentBuilder::build",
         "把模型、指令和工具组装成 `LlmAgent`"),
        ("应用策略", "adk-core/src/policy.rs", "struct DeclarativePolicy",
         "规则按顺序匹配，第一条命中的规则决定允许、拒绝还是等待审批；都不命中就拒绝（见结构体上方的说明）"),
        ("内存会话", "adk-session/src/inmemory.rs", "struct InMemorySessionService",
         "会话事件只放在进程内存里"),
        ("运行入口", "adk-runner/src/runner.rs", "Runner::run_with_config",
         "加载会话、运行 Agent、逐条保存事件"),
    ]),
    "hooks": ("本章观察到的回调顺序与失败后果，在 ADK-Rust 里分布在这几处：", [
        ("工具前回调的签名", "adk-core/src/callbacks.rs", ("grep", r"pub type BeforeToolCallback"),
         "返回 `None` 继续，返回内容表示拦下并用它代替结果，返回错误表示回调自己失败"),
        ("Agent 结束回调的签名", "adk-core/src/callbacks.rs", ("grep", r"pub type AfterAgentCallback"),
         "返回内容会追加一条最终回答；返回错误会让运行以错误结束"),
        ("注册工具前回调", "adk-agent/src/llm_agent.rs", "LlmAgentBuilder::before_tool_callback",
         "可以注册多个，按注册顺序运行；有一个给出内容，后面的同类回调就不再运行"),
        ("回调 panic 的处理", "adk-core/src/callbacks.rs", "fn guard_callback",
         "把 panic 变成 `callback.panicked` 错误；只有工具前回调经过它，其他回调里的 panic 框架不接"),
        ("执行后流水线失败时交给模型的结果", "adk-core/src/tool_response.rs", ("grep", r"ran, but its after-tool pipeline failed"),
         "结果被扣下（withheld），并告诉模型不要再调用这个工具"),
        ("工具调用的受控路径", "adk-core/src/governance.rs", "fn authorize_tool_call",
         "策略、护栏、审批在这里依次检查；它在工具前回调之后运行"),
    ]),
    "permissions": ("本章的策略、挂起与审批，在 ADK-Rust 里分布在这几处：", [
        ("应用的策略接口", "adk-core/src/policy.rs", "trait ToolPolicy",
         "只需实现 `evaluate`：给一个请求，回答允许、拒绝或需要批准；受控路径调用的 `evaluate_call` 默认转给它"),
        ("三种决定", "adk-core/src/policy.rs", "enum PolicyDecision",
         "`Allow` / `Deny` / `RequireApproval`，后两种带理由"),
        ("每次工具调用都经过的受控路径", "adk-core/src/governance.rs", "fn authorize_tool_call",
         "熔断器在它之前；它内部依次检查总开关、同意、恢复绑定、出口、策略、护栏、确认（审批），没通过就不执行"),
        ("请求的指纹", "adk-core/src/context.rs", "ToolConfirmationRequest::fingerprint",
         "由执行的 Agent、工具来源与声明、工具名和规范化参数合成；参数变了，指纹就变"),
        ("审批记录的接口", "adk-core/src/governance.rs", "trait ApprovalStore",
         "记下等待的请求、按指纹记录决定、取走决定（取走即用掉）"),
        ("找出等待中的调用", "adk-core/src/governance.rs", "fn held_tool_calls",
         "每次运行开始时，从会话事件里找出挂起的调用，有决定的就恢复"),
        ("需要批准时先查审批记录", "adk-core/src/governance.rs", "fn resolve_confirmation",
         "调用第一次需要批准时就先取审批记录里的决定，所以预先写入的决定会直接生效"),
    ]),
    "agent-loop": ("本章观察到的循环，在 ADK-Rust 里分布在这几处（按一次运行的先后）：", [
        ("运行入口", "adk-runner/src/runner.rs", "Runner::run_with_config",
         "加载会话、交给 Agent 运行，并把 Agent 产生的每个事件逐条写进会话"),
        ("从会话取出历史", "adk-agent/src/llm_agent.rs", "fn prepare_conversation",
         "运行开始时把会话事件整理成本次运行在内存里维护的对话历史"),
        ("循环本身", "adk-agent/src/llm_agent.rs", ("grep", r"'model_calls: loop \{"),
         "每一轮：检查上限与预算 → 组装请求 → 调用模型 → 执行工具 → 结果写回历史"),
        ("循环上限", "adk-agent/src/llm_agent.rs", ("grep", r"if iteration > max_iterations"),
         "每次调用模型前先加一，超过 `max_iterations` 就以错误结束（`agent.legacy`）"),
        ("组装一次请求", "adk-agent/src/llm_agent.rs", ("grep", r"let mut request = LlmRequest \{"),
         "把对话历史和工具声明放进 `LlmRequest`；本章记录的 `request` 行就是它"),
        ("模型的回复写进历史", "adk-agent/src/llm_agent.rs", ("grep", r"conversation_history\.push\(Self::augment_content_for_history"),
         "带调用的回复先写进历史，下一次请求里的 `model` 角色就是它"),
        ("执行这一批调用", "adk-agent/src/llm_agent.rs", ("grep", r"let dispatch = executor\.dispatch\(strategy, fc_parts\)"),
         "按策略执行同一条回复里的全部调用"),
        ("工具结果写回历史", "adk-agent/src/llm_agent.rs", ("grep", r"conversation_history\.push\(result\.content\)"),
         "结果带原调用 ID 写回历史，下一次请求里的 `function` 角色就是它"),
        ("模型的边界", "adk-core/src/model.rs", ("grep", r"async fn generate_content\(&self, req: LlmRequest"),
         "必需的只有 `name` 和这个 `generate_content`；本章的 RuleLlm 就实现它"),
        ("模型调用预算", "adk-core/src/budget.rs", "BudgetTracker::begin_model_call",
         "在请求模型之前计数；用完就返回 `budget.model_calls`"),
        ("整批申请工具额度", "adk-core/src/budget.rs", "BudgetTracker::begin_tool_calls",
         "一条回复里的全部调用一起申请：要么全部计入，要么一个都不计入，不够时每个调用得到 `not_run`"),
    ]),
    "side-effect-reliability": ("第 9 节用到的动作账本与恢复，在 ADK-Rust 里分布在这几处：", [
        ("工具的副作用声明", "adk-core/src/tool.rs", "enum ToolEffect",
         "没有声明的工具按 `NonIdempotent` 对待：只执行一次，不自动重试"),
        ("每次调用的幂等键", "adk-agent/src/llm_agent.rs", "fn idempotency_key",
         "普通调用为应用 / 用户 / 会话 / 本次运行 / 调用 ID，换一轮运行就是新键（`retry-call-key` 出现第二张工单的原因）；等待批准后恢复的调用沿用第一次的键"),
        ("动作账本的接口", "adk-core/src/action_ledger.rs", "trait ActionLedger",
         "调用前记开始、调用后记结果；恢复时按键查询"),
        ("SQLite 上的账本", "adk-session/src/sqlite_action_ledger.rs", "struct SqliteActionLedger",
         "本章把它和会话放在同一个 SQLite 文件；`InMemoryActionLedger` 进程退出即丢"),
        ("恢复没有结果的调用", "adk-runner/src/runner.rs", "Runner::recover_unanswered_calls",
         "按账本回答 `already_succeeded` / `already_failed` / `outcome_unknown`，不执行任何工具"),
        ("结果未知时交给模型的答案", "adk-core/src/action_ledger.rs", "fn outcome_unknown_response",
         "提醒“可能已经生效，再调用前先核对”；判断用 `is_outcome_unknown`"),
    ]),
    "graph-state-routing": ("本章观察到的状态通道、路由和步数上限，在 adk-graph 里分布在这几处：", [
        ("通道的三种归并规则", "adk-graph/src/state.rs", "StateSchema::apply_update",
         "覆盖、追加、求和；求和按浮点数算，写 1 读回来是 `1.0`（`counter_channel n=2.0` 的来历）"),
        ("条件边", "adk-graph/src/graph.rs", "StateGraph::add_conditional_edges",
         "路由函数返回一个键，按映射表找到目标节点"),
        ("建图检查", "adk-graph/src/graph.rs", "StateGraph::compile",
         "悬空的边、缺少起点在这里被拒绝；路由函数返回什么要到运行时才知道"),
        ("运行时选出下一批节点", "adk-graph/src/graph.rs", "CompiledGraph::get_next_nodes",
         "映射表里没有的键报 `UnknownRouteTarget`；没有出边的节点只结束自己这一支"),
        ("节点自己指定后继", "adk-graph/src/node.rs", "NodeOutput::with_goto",
         "替换这个节点声明的边；目标不存在同样报 `UnknownRouteTarget`"),
        ("超步上限", "adk-graph/src/graph.rs", "CompiledGraph::with_recursion_limit",
         "默认 100；超出时报 `RecursionLimitExceeded`，检查点保留已经走到的状态"),
        ("每个超步开始前检查上限", "adk-graph/src/executor.rs", ("grep", r"return Err\(GraphError::RecursionLimitExceeded\(steps_taken\)\)"),
         "数的是这次运行从头开始的步数：暂停或失败后恢复，之前走过的步也算在内"),
        ("只允许写声明过的通道", "adk-graph/src/graph.rs", "CompiledGraph::with_strict_channels",
         "不打开时，拼错名字的通道会被当成新通道直接覆盖写入"),
    ]),
    "graph-pause-resume": ("本章的暂停、检查点与严格恢复，在 adk-graph 里分布在这几处：", [
        ("节点请求暂停", "adk-graph/src/node.rs", "NodeOutput::interrupt_with_data",
         "带上给审批人看的数据；`with_response_schema` 再声明答案格式"),
        ("暂停 ID 怎样算出", "adk-graph/src/interrupt.rs", "fn interrupt_id",
         "线程、步号、节点、问题、数据、答案格式一起取哈希：同一个问题 ID 不变，问题变了 ID 就变"),
        ("严格恢复", "adk-graph/src/node.rs", "ExecutionConfig::strict_resume",
         "只接受按暂停 ID 给出的回答，不接受按节点名回答"),
        ("恢复前核对回答", "adk-graph/src/executor.rs", "fn check_resume_answers",
         "ID 对不上或答案不符合格式，报 `ResumeRejected`，任何节点都不运行"),
        ("节点读到回答", "adk-graph/src/node.rs", "NodeContext::resume_value",
         "只在恢复的那一步有值；暂停的节点在这一步重新运行"),
        ("检查点版本只增不减", "adk-graph/src/checkpoint.rs", "fn ensure_newer",
         "同一线程已有不低于本次的版本时报 `CheckpointConflict`；两个写入者只有一个成功"),
        ("SQLite 检查点", "adk-graph/src/checkpoint.rs", "struct SqliteCheckpointer",
         "需要 `sqlite` 特性；表名 `graph_checkpoints`。框架不核对图的版本，这一步由宿主做"),
    ]),
    "graph-parallel-subgraphs": ("本章的并行、归并、失败恢复、超时与子图，在 adk-graph 里分布在这几处：", [
        ("多条入边的节点自动等待", "adk-graph/src/graph.rs", "StateGraph::defer_unconditional_fan_in",
         "编译时把有多条无条件入边的节点标成汇合节点：上游都到齐才运行，而且只运行一次"),
        ("同一步的更新按什么顺序应用", "adk-graph/src/executor.rs", ("grep", r"all_updates\.sort_by\("),
         "按节点名、通道名排序后逐个经过归并规则，与谁先完成无关"),
        ("失败的一步里已完成的节点", "adk-graph/src/executor.rs", ("grep", r"applying pending write instead of re-running node"),
         "重试这一步时直接应用保存下来的结果，只重跑失败的节点"),
        ("超时策略", "adk-graph/src/timeout.rs", "struct TimeoutPolicy",
         "运行时长与空闲时长两种上限，超时后按 `OnTimeout` 失败、重试或跳过"),
        ("超时后的三种处理", "adk-graph/src/timeout.rs", "enum OnTimeout",
         "`Skip` 让节点以空输出继续，缺失要由下游归并规则识别"),
        ("子图节点只交换声明的通道", "adk-graph/src/subgraph.rs", "SubgraphNode::isolated",
         "不加时，两边同名的通道自动互通；加上后只交换 `with_input` / `with_output` 声明的通道，子图的草稿通道不会带回父图"),
        ("通道映射在父图编译时检查", "adk-graph/src/subgraph.rs", ("grep", r"^    fn validate_against\("),
         "映射到对方没有声明的通道时报 `SubgraphChannelMismatch`，不会等到运行"),
    ]),
}

ITEM = r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?(?:const\s+)?{kind}\s+{name}\b"


def find(lines, locator):
    """Return (start, end) 1-based line numbers, or None."""
    if isinstance(locator, tuple):
        pattern = re.compile(locator[1])
        start = next((i for i, line in enumerate(lines) if pattern.search(line)), None)
        return None if start is None else (start + 1, start + 1)
    if "::" in locator:
        owner, method = locator.split("::", 1)
        impl = re.compile(rf"^\s*impl\b[^{{;]*\b{re.escape(owner)}\b(?:<[^{{]*>)?\s*(?:where[^{{]*)?\{{")
        fn = re.compile(ITEM.format(kind="fn", name=re.escape(method)))
        for i, line in enumerate(lines):
            if impl.search(line) and " for " not in line.split(owner)[0]:
                for j in range(i + 1, len(lines)):
                    if fn.search(lines[j]):
                        return j + 1, block_end(lines, j) + 1
        return None
    kind, name = locator.split(" ", 1)
    pattern = re.compile(ITEM.format(kind=kind, name=re.escape(name)))
    start = next((i for i, line in enumerate(lines) if pattern.search(line)), None)
    return None if start is None else (start + 1, block_end(lines, start) + 1)


def block_end(lines, start):
    """Line index where the item starting at `start` closes its braces (rough, ignores strings)."""
    depth, opened = 0, False
    for i in range(start, len(lines)):
        code = lines[i].split("//", 1)[0]
        depth += code.count("{") - code.count("}")
        opened = opened or "{" in code
        if opened and depth <= 0:
            return i
        if not opened and code.rstrip().endswith(";"):
            return i
    return start


def render(slug, source):
    intro, rows = SPEC[slug]
    out, problems = [START, "", "## 在 ADK-Rust 源码里", "", intro, "",
                     "| 本章内容 | 源码位置 | 对照要点 |", "| --- | --- | --- |"], []
    for label, file, locator, note in rows:
        path = source / file
        if not path.exists():
            problems.append(f"{slug}: 文件不存在 {file}")
            continue
        span = find(path.read_text(encoding="utf-8").splitlines(), locator)
        if span is None:
            problems.append(f"{slug}: {file} 里找不到 {locator}")
            continue
        name = locator[1] if isinstance(locator, tuple) else locator.split(" ", 1)[-1]
        anchor = f"#L{span[0]}" if span[0] == span[1] else f"#L{span[0]}-L{span[1]}"
        shown = f"`{file}` · `{name}`" if not isinstance(locator, tuple) else f"`{file}` 第 {span[0]} 行"
        out.append(f"| {label} | [{shown}]({BLOB}{file}{anchor}) | {note} |")
    out += ["", f"源码固定在 ADK-Rust `{adk.BASELINE['rev'][:12]}`（{adk.BASELINE['version']}，"
            f"{adk.BASELINE['rev_date']}，尚未发布到 crates.io）。本节由 `scripts/learn-agent-rust-adk-refs.py` 生成。",
            "", END]
    return "\n".join(out), problems


def apply(text, section):
    if START in text and END in text:
        before, rest = text.split(START, 1)
        return before + section + rest.split(END, 1)[1]
    marker = "\n## 本章结论"
    if marker not in text:
        raise adk.VerifyError("找不到“## 本章结论”，无法插入")
    before, after = text.split(marker, 1)
    return before.rstrip("\n") + "\n\n" + section + "\n" + marker + after


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--src", type=Path)
    args = parser.parse_args()
    source = args.src.resolve() if args.src else adk.adk_source()
    lessons = json.loads(LESSONS.read_text(encoding="utf-8"))["lessons"]
    stacks = {row["slug"]: row["stack"] for row in lessons}
    problems, changed = [], []
    for slug in SPEC:
        if slug not in stacks:
            problems.append(f"{slug}: SPEC 里的章节不在 lessons.json")
            continue
        section, found = render(slug, source)
        problems += found
        if stacks[slug] != "adk3":
            print(f"{slug}: 仍是 v1，只检查 SPEC，不写正文")
            continue
        if found:
            continue
        page = DOCS / f"{slug}.md"
        text = page.read_text(encoding="utf-8")
        new = apply(text, section)
        if new != text:
            changed.append(page)
            if not args.check:
                page.write_text(new, encoding="utf-8")
    for problem in problems:
        print(problem)
    verb = "过期" if args.check else "已更新"
    print(f"{len(SPEC)} 章 SPEC，{len(changed)} 个页面{verb}，{len(problems)} 个问题")
    sys.exit(1 if problems or (args.check and changed) else 0)


if __name__ == "__main__":
    main()
