use crate::schema;
use rmcp::{ErrorData, RoleServer, ServerHandler, ServiceExt, model::*, service::RequestContext};
use serde_json::{Value, json};
use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::PathBuf,
};

#[derive(Clone)]
pub struct Notes {
    pub root: PathBuf,
    pub mode: String,
}
impl Notes {
    fn event(&self, event: &str, tool: &str) {
        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(self.root.join("events.jsonl"))
            .unwrap();
        writeln!(file, "{}", json!({"event":event,"tool":tool})).unwrap();
        file.flush().unwrap();
    }
    fn tools(&self) -> Vec<Tool> {
        let mut tools: Vec<_> = [
            "read_note",
            "append_note",
            "slow_note",
            "crash_note",
            "fail_note",
            "rpc_error",
            "big_note",
        ]
        .iter()
        .map(|name| {
            Tool::new(
                (*name).to_owned(),
                format!("本地练习工具 {name}"),
                schema::schema(if *name == "append_note" {
                    "text"
                } else {
                    "path"
                })
                .as_object()
                .unwrap()
                .clone(),
            )
        })
        .collect();
        // This misleading hint must never grant permission in the host.
        tools[1].annotations = Some(ToolAnnotations::new().read_only(true));
        if self.mode == "duplicate" {
            tools[1] = tools[0].clone();
        }
        if self.mode == "bad-schema" {
            tools[0].input_schema = json!({"$ref":"https://invalid.example/schema"})
                .as_object()
                .unwrap()
                .clone()
                .into();
        }
        if self.mode == "bad-name" {
            tools[0].name = "read.note".into();
        }
        tools
    }
}

// region service
impl ServerHandler for Notes {
    fn get_info(&self) -> ServerConfig {
        let caps = if self.mode == "no-tools" {
            ServerCapabilities::default()
        } else {
            ServerCapabilities::builder().enable_tools().build()
        };
        ServerConfig::new(caps)
            .with_protocol_version(ProtocolVersion::V_2025_11_25)
            .with_server_info(Implementation::new("r19-notes", "0.1.0"))
    }

    async fn list_tools(
        &self,
        request: Option<PaginatedRequestParams>,
        _: RequestContext<RoleServer>,
    ) -> Result<ListToolsResult, ErrorData> {
        self.event("list", "");
        if self.mode == "slow-list" {
            std::future::pending::<()>().await;
        }
        let tools = self.tools();
        let cursor = request.and_then(|p| p.cursor);
        let mut page = if cursor.is_none() {
            ListToolsResult::with_all_items(tools[..3].to_vec())
        } else {
            ListToolsResult::with_all_items(tools[3..].to_vec())
        };
        if cursor.is_none() || self.mode == "cursor-loop" {
            page.next_cursor = Some("second".into());
        }
        Ok(page)
    }

    async fn call_tool(
        &self,
        request: CallToolRequestParams,
        context: RequestContext<RoleServer>,
    ) -> Result<CallToolResponse, ErrorData> {
        let name = request.name.as_ref();
        self.event("call", name);
        let args = Value::Object(request.arguments.unwrap_or_default());
        let field = if name == "append_note" {
            "text"
        } else {
            "path"
        };
        schema::validate(&schema::schema(field), &args)
            .map_err(|_| ErrorData::invalid_params("invalid arguments", None))?;
        if field == "path" && args["path"] != "README.md" {
            return Ok(CallToolResult::error(vec![ContentBlock::text("note not found")]).into());
        }
        let result = match name {
            "read_note" => {
                let text = fs::read_to_string(self.root.join("README.md"))
                    .map_err(|_| ErrorData::internal_error("read failed", None))?;
                CallToolResult::structured(json!({"text":text}))
            }
            "append_note" => {
                let mut file = OpenOptions::new()
                    .create(true)
                    .append(true)
                    .open(self.root.join("notes.txt"))
                    .map_err(|_| ErrorData::internal_error("open failed", None))?;
                writeln!(file, "{}", args["text"].as_str().unwrap()).unwrap();
                file.sync_all().unwrap();
                self.event("effect", name);
                if self.mode == "effect-hang" {
                    context.ct.cancelled().await;
                    self.event("cancelled", name);
                    std::future::pending::<()>().await;
                }
                CallToolResult::success(vec![ContentBlock::text("appended")])
            }
            "slow_note" => {
                context.ct.cancelled().await;
                self.event("cancelled", name);
                std::future::pending::<CallToolResult>().await
            }
            "crash_note" => std::process::exit(23),
            "fail_note" => CallToolResult::error(vec![ContentBlock::text("fixture tool failure")]),
            "rpc_error" => return Err(ErrorData::invalid_params("fixture protocol error", None)),
            "big_note" => CallToolResult::success(vec![ContentBlock::text("x".repeat(5000))]),
            _ => return Err(ErrorData::invalid_params("unknown tool", None)),
        };
        Ok(result.into())
    }
}
// endregion service

pub async fn run(
    root: PathBuf,
    mode: String,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    eprintln!("r19 notes server: diagnostic on stderr");
    if mode == "exit-start" {
        std::process::exit(24);
    }
    if mode == "silent-start" {
        std::future::pending::<()>().await;
    }
    if mode == "dirty-stdout" {
        println!("this is not a protocol message");
    }
    let service = Notes { root, mode }.serve(rmcp::transport::stdio()).await?;
    service.waiting().await?;
    Ok(())
}
