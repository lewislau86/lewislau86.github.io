// Learn Agent by Rust（ADK-Rust 3.0 版）各章共用的轨迹打印。
// 使用方法：把下面 region 标记之间的整段（含标记）原样复制到章节工程的 `src/trace.rs`，
// 在 main.rs 里 `mod trace;`。scripts/check-learn-agent-rust-snippets.py 核对各章副本与本文件一致。
// 轨迹只写可比较的内容（作者、调用 ID、工具名、参数、结果状态、状态变化、文本），
// 不写事件 ID、时间戳等每次运行都会变的字段，所以同一脚本连跑多次应逐字节相同。

// region adk-trace
#![allow(dead_code)] // 各章只用到其中一部分函数

use adk_core::{Event, LlmRequest, Part};

/// 把一条事件写成若干行轨迹；没有可观察内容的事件返回空列表。
pub fn event_lines(event: &Event) -> Vec<String> {
    let mut lines = Vec::new();
    let who = if event.author.is_empty() {
        "-"
    } else {
        event.author.as_str()
    };
    if let Some(content) = event.content() {
        for part in &content.parts {
            match part {
                Part::FunctionCall { name, args, id, .. } => lines.push(format!(
                    "[{who}] call    id={} {name} {args}",
                    id.as_deref().unwrap_or("-")
                )),
                Part::FunctionResponse {
                    function_response,
                    id,
                    ..
                } => lines.push(format!(
                    "[{who}] result  id={} {} status={}{} {}",
                    id.as_deref().unwrap_or("-"),
                    function_response.name,
                    part.tool_result_status()
                        .and_then(|s| serde_json::to_value(s).ok())
                        .and_then(|v| v.as_str().map(str::to_owned))
                        .unwrap_or_else(|| "ok".to_owned()),
                    // 错误码记在结果的注解里，不一定出现在模型读到的文字中
                    part.tool_result_error_code()
                        .map(|code| format!(" code={code}"))
                        .unwrap_or_default(),
                    function_response.response
                )),
                Part::Text { text } if !event.llm_response.partial => {
                    lines.push(format!("[{who}] text    {text:?}"))
                }
                _ => {}
            }
        }
    }
    let mut keys: Vec<_> = event.actions.state_delta.keys().collect();
    keys.sort();
    for key in keys {
        lines.push(format!(
            "[{who}] state   {key} = {}",
            event.actions.state_delta[key]
        ));
    }
    if let Some(request) = &event.actions.tool_confirmation {
        lines.push(format!("[{who}] held    {request:?}"));
    }
    // 预算用完等原因停止时，框架会写一条带错误码、没有内容的事件，说明为什么停
    if let Some(code) = &event.llm_response.error_code {
        lines.push(format!("[{who}] stop    code={code}"));
    }
    // 用户输入和停止说明的事件也算“最终”，只标记 Agent 一侧真正的最终回答
    let stopped = event.llm_response.error_code.is_some();
    if event.is_final_response() && event.author != "user" && !stopped && !lines.is_empty() {
        lines.push(format!("[{who}] final"));
    }
    lines
}

/// 把脚本模型收到的每次请求写成一行：消息角色序列与工具声明，供断言“模型看到了什么”。
pub fn request_lines(requests: &[LlmRequest]) -> Vec<String> {
    requests
        .iter()
        .enumerate()
        .map(|(i, request)| {
            let roles: Vec<&str> = request.contents.iter().map(|c| c.role.as_str()).collect();
            let tools: Vec<&str> = request.tools.keys().map(String::as_str).collect();
            format!(
                "request {i}: roles={} tools=[{}]",
                roles.join(","),
                tools.join(",")
            )
        })
        .collect()
}
// endregion adk-trace
