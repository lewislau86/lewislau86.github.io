use crate::{
    connection::{Connection, REQUEST_MS},
    schema::{self, Check},
};
use rmcp::model::*;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    time::Duration,
};

#[derive(Clone)]
pub struct Entry {
    pub server: Option<String>,
    pub remote: String,
    pub input_schema: Value,
    pub description: String,
}
#[derive(Default)]
pub struct Registry(pub BTreeMap<String, Entry>);

pub fn alias(server: &str, name: &str) -> Check<String> {
    if server.is_empty()
        || server.len() > 16
        || !server.bytes().all(|b| b.is_ascii_alphanumeric())
        || name.is_empty()
        || name.len() > 40
        || !name
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
    {
        return Err("unsupported_name");
    }
    Ok(format!("mcp_{server}__{name}"))
}

impl Registry {
    pub fn local() -> Self {
        Self(BTreeMap::from([(
            "local_status".into(),
            Entry {
                server: None,
                remote: "local_status".into(),
                input_schema: schema::schema("path"),
                description: "读取宿主状态，固定本地处理函数".into(),
            },
        )]))
    }

    // region discovery
    pub async fn discover(&mut self, namespace: &str, connection: &mut Connection) -> Check<()> {
        if !connection.usable {
            return Err("connection_unavailable");
        }
        let service = connection
            .service
            .as_ref()
            .ok_or("connection_unavailable")?;
        let mut cursor: Option<String> = None;
        let mut cursors = BTreeSet::new();
        let mut candidate = self.0.clone();
        for _ in 0..3 {
            let params = cursor
                .clone()
                .map(|c| PaginatedRequestParams::default().with_cursor(Some(c)));
            let page = match tokio::time::timeout(
                Duration::from_millis(REQUEST_MS),
                service.list_tools(params),
            )
            .await
            {
                Ok(Ok(page)) => page,
                _ => {
                    connection.usable = false;
                    return Err("discovery_failed");
                }
            };
            if candidate.len() + page.tools.len() > 24 {
                return Err("tool_limit");
            }
            for tool in page.tools {
                let name = alias(namespace, &tool.name)?;
                let input_schema = Value::Object((*tool.input_schema).clone());
                schema::admit(&input_schema)?;
                if tool.output_schema.is_some() {
                    return Err("unsupported_output_schema");
                }
                let description = tool.description.unwrap_or_default().to_string();
                if description.len() > 512 {
                    return Err("description_limit");
                }
                let entry = Entry {
                    server: Some(namespace.into()),
                    remote: tool.name.into_owned(),
                    input_schema,
                    description,
                };
                if candidate.insert(name, entry).is_some() {
                    return Err("duplicate_alias");
                }
            }
            match page.next_cursor {
                None => {
                    self.0 = candidate;
                    return Ok(());
                }
                Some(next) if next.len() <= 128 && cursors.insert(next.clone()) => {
                    cursor = Some(next)
                }
                Some(_) => return Err("cursor_loop"),
            }
        }
        Err("page_limit")
    }
    // endregion discovery

    // region definitions
    pub fn definitions(&self) -> Vec<Value> {
        self.0
            .iter()
            .map(|(name, entry)| {
                json!({"type":"function", "function":{
            "name":name,"description":entry.description,"parameters":entry.input_schema}})
            })
            .collect()
    }
    pub fn invalidate(&mut self, server: &str) {
        self.0
            .retain(|_, entry| entry.server.as_deref() != Some(server));
    }
    // endregion definitions
}

#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Invocation {
    pub call_id: String,
    pub name: String,
    pub arguments: Value,
}
#[derive(Clone)]
pub struct Approval(pub Invocation);

pub fn allowed(entry: &Entry, request: &Invocation, approval: Option<&Approval>) -> Check<()> {
    if entry.server.is_none()
        || entry.remote == "read_note"
        || entry.remote == "slow_note"
        || entry.remote == "crash_note"
        || entry.remote == "fail_note"
        || entry.remote == "rpc_error"
        || entry.remote == "big_note"
    {
        return Ok(());
    }
    if entry.server.as_deref() == Some("notes") && entry.remote == "append_note" {
        return if approval.is_some_and(|a| a.0 == *request) {
            Ok(())
        } else {
            Err("approval_required")
        };
    }
    Err("permission_denied")
}

#[derive(Default)]
pub struct Dispatcher {
    seen: BTreeSet<String>,
    pub dispatched: u32,
}
impl Dispatcher {
    // region dispatch
    pub async fn invoke(
        &mut self,
        registry: &Registry,
        connections: &mut BTreeMap<String, Connection>,
        request: Invocation,
        approval: Option<Approval>,
    ) -> Value {
        let id = request.call_id.clone();
        let result = self
            .execute(registry, connections, request, approval.as_ref())
            .await;
        json!({"role":"tool","tool_call_id":id,"content":result})
    }

    async fn execute(
        &mut self,
        registry: &Registry,
        connections: &mut BTreeMap<String, Connection>,
        request: Invocation,
        approval: Option<&Approval>,
    ) -> Value {
        let checked = || -> Check<&Entry> {
            if request.call_id.is_empty() || request.call_id.len() > 48 {
                return Err("invalid_call_id");
            }
            let entry = registry.0.get(&request.name).ok_or("unknown_tool")?;
            schema::validate(&entry.input_schema, &request.arguments)?;
            allowed(entry, &request, approval)?;
            Ok(entry)
        };
        let entry = match checked() {
            Ok(entry) => entry,
            Err(code) => return json!({"ok":false,"error":code}),
        };
        if self.dispatched >= 8 {
            return json!({"ok":false,"error":"call_budget"});
        }
        if !self.seen.insert(request.call_id.clone()) {
            return json!({"ok":false,"error":"duplicate_call"});
        }
        let Some(namespace) = &entry.server else {
            return json!({"ok":true,"data":{"status":"local_ready"}});
        };
        let Some(connection) = connections.get_mut(namespace).filter(|c| c.usable) else {
            return json!({"ok":false,"error":"connection_unavailable"});
        };
        self.dispatched += 1; // Count before send; failures still consume the attempt.
        let params = CallToolRequestParams::new(entry.remote.clone())
            .with_arguments(request.arguments.as_object().unwrap().clone());
        let service = connection.service.as_ref().unwrap();
        match tokio::time::timeout(Duration::from_millis(REQUEST_MS), service.call_tool(params))
            .await
        {
            Ok(Ok(result)) => {
                let data = serde_json::to_value(result).unwrap();
                if data.to_string().len() > 4096 {
                    return json!({"ok":false,"error":"result_limit"});
                }
                json!({"ok":data["isError"] != true,"data":data})
            }
            Ok(Err(error)) => match error {
                rmcp::ServiceError::McpError(_) => json!({"ok":false,"error":"protocol_error"}),
                _ => {
                    connection.usable = false;
                    json!({"ok":false,"error":"transport_error","reconcile":entry.remote == "append_note"})
                }
            },
            Err(_) => {
                connection.usable = false;
                json!({"ok":false,"error":if entry.remote == "append_note" {"outcome_unknown"} else {"timeout"}})
            }
        }
    }
    // endregion dispatch
}
