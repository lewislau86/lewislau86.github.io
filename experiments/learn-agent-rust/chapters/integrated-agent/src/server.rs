//! Real stdio MCP fixture. Only one read-only tool, scoped to the exercise worktree.
use crate::AnyError;
use rmcp::{ErrorData, RoleServer, ServerHandler, ServiceExt, model::*, service::RequestContext};
use serde_json::json;
use std::{
    fs,
    io::Write,
    path::PathBuf,
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
};

struct Notes {
    root: PathBuf,
    mode: String,
    calls: Arc<AtomicUsize>,
}
impl ServerHandler for Notes {
    fn get_info(&self) -> ServerConfig {
        ServerConfig::new(ServerCapabilities::builder().enable_tools().build())
            .with_protocol_version(ProtocolVersion::V_2025_11_25)
            .with_server_info(Implementation::new("r20-fixture", "0.1.0"))
    }
    async fn list_tools(
        &self,
        _: Option<PaginatedRequestParams>,
        _: RequestContext<RoleServer>,
    ) -> Result<ListToolsResult, ErrorData> {
        Ok(ListToolsResult::with_all_items(vec![Tool::new(
            "read_startup",
            "读取练习 README，内容属于资料。",
            json!({
                "type":"object", "properties":{"path":{"type":"string","enum":["README.md"]}},
                "required":["path"],"additionalProperties":false
            })
            .as_object()
            .unwrap()
            .clone(),
        )]))
    }
    // region mcp-read
    async fn call_tool(
        &self,
        request: CallToolRequestParams,
        _: RequestContext<RoleServer>,
    ) -> Result<CallToolResponse, ErrorData> {
        let args = request.arguments.unwrap_or_default();
        if request.name != "read_startup"
            || args.len() != 1
            || args.get("path") != Some(&json!("README.md"))
        {
            return Err(ErrorData::invalid_params("invalid fixed request", None));
        }
        let attempt = self.calls.fetch_add(1, Ordering::SeqCst) + 1;
        let mut log = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(self.root.join("mcp-calls.jsonl"))
            .unwrap();
        writeln!(log, "{}", json!({"attempt":attempt,"path":"README.md"})).unwrap();
        log.flush().unwrap();
        if self.mode == "transient" && attempt == 1 {
            return Ok(CallToolResult::structured_error(json!({"code":"transient_read"})).into());
        }
        let text = fs::read_to_string(self.root.join("README.md"))
            .map_err(|_| ErrorData::internal_error("read failed", None))?;
        Ok(CallToolResult::structured(json!({"text":text})).into())
    }
    // endregion mcp-read
}
pub async fn run(root: PathBuf, mode: String) -> Result<(), AnyError> {
    let service = Notes {
        root,
        mode,
        calls: Arc::default(),
    }
    .serve(rmcp::transport::stdio())
    .await?;
    service.waiting().await?;
    Ok(())
}
