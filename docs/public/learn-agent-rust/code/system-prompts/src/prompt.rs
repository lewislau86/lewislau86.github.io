use langchain_rust::schemas::{Message, MessageType, ToolCall};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    io::Read,
    path::PathBuf,
};

pub type PromptResult<T> = Result<T, &'static str>;
pub const TEMPLATE: &str = "r10-prompt-v1";
pub const MAX_SOURCE_BYTES: usize = 8192;

pub fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

// region sources
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Record {
    pub id: String,
    pub version: String,
    pub text: String,
}

#[derive(Clone)]
pub struct Pin {
    pub path: PathBuf,
    pub id: String,
    pub version: String,
    pub sha256: String,
}

impl Pin {
    pub fn load(&self) -> PromptResult<Record> {
        let mut bytes = Vec::new();
        fs::File::open(&self.path)
            .map_err(|_| "missing_source")?
            .take((MAX_SOURCE_BYTES + 1) as u64)
            .read_to_end(&mut bytes)
            .map_err(|_| "source_io")?;
        if bytes.len() > MAX_SOURCE_BYTES {
            return Err("source_too_large");
        }
        if digest(&bytes) != self.sha256 {
            return Err("stale_source");
        }
        let record: Record = serde_json::from_slice(&bytes).map_err(|_| "invalid_source")?;
        if record.id != self.id
            || record.version != self.version
            || record.version.trim().is_empty()
            || record.text.trim().is_empty()
        {
            return Err("invalid_source");
        }
        Ok(record)
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Environment {
    pub workspace: String,
    pub locale: String,
    pub read_only: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SourceAudit {
    pub id: String,
    pub version: String,
    pub sha256: String,
    pub text_bytes: usize,
    pub placement: String,
}

#[derive(Clone)]
pub struct Config {
    pub policy: Pin,
    pub references: BTreeMap<String, Pin>,
    pub selected: Vec<String>,
    pub environment: Environment,
    pub max_request_bytes: usize,
}
// endregion sources

#[derive(Clone)]
pub struct Registry {
    pub read_enabled: bool,
}

impl Registry {
    // region registry
    pub fn descriptions(&self) -> Value {
        if !self.read_enabled {
            return json!([]);
        }
        json!([{
            "name": "read_file",
            "description": "读取当前练习工作区的 README.md",
            "parameters": {"type": "object", "properties": {"path": {"type": "string", "enum": ["README.md"]}},
                "required": ["path"], "additionalProperties": false}
        }])
    }
    // endregion registry
}

// region history
pub fn validate_history(history: &[Message]) -> PromptResult<()> {
    let mut pending = BTreeSet::new();
    let mut seen = BTreeSet::new();
    for message in history {
        match message.message_type {
            MessageType::SystemMessage => return Err("history_system"),
            MessageType::AIMessage => {
                if !pending.is_empty() {
                    return Err("unpaired_tool");
                }
                if let Some(calls) = &message.tool_calls {
                    let calls: Vec<ToolCall> =
                        serde_json::from_value(calls.clone()).map_err(|_| "invalid_history")?;
                    for call in calls {
                        if call.id.is_empty() || !seen.insert(call.id.clone()) {
                            return Err("invalid_call_id");
                        }
                        pending.insert(call.id);
                    }
                }
            }
            MessageType::ToolMessage => {
                if !message.id.as_ref().is_some_and(|id| pending.remove(id)) {
                    return Err("unpaired_tool");
                }
            }
            MessageType::HumanMessage if !pending.is_empty() => return Err("unpaired_tool"),
            _ => {}
        }
    }
    if !pending.is_empty() {
        return Err("unpaired_tool");
    }
    Ok(())
}
// endregion history

#[derive(Clone)]
struct Prefix {
    key: String,
    messages: Vec<Message>,
    sources: Vec<SourceAudit>,
}

#[derive(Default)]
pub struct Assembler {
    cache: Option<Prefix>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ModelInput {
    pub template: String,
    pub prefix_sha256: String,
    pub input_sha256: String,
    pub cache_hit: bool,
    pub serialized_bytes: usize,
    pub sources: Vec<SourceAudit>,
    pub messages: Vec<Message>,
}

impl Assembler {
    // region assemble
    pub fn build(
        &mut self,
        config: &Config,
        registry: &Registry,
        history: &[Message],
    ) -> PromptResult<ModelInput> {
        validate_history(history)?;
        if config.selected.len() > 8 {
            return Err("source_count");
        }
        let policy = config.policy.load()?;
        let mut sources = vec![audit(&config.policy, &policy, "system")];
        let mut references = Vec::new();
        let selected: BTreeSet<_> = config.selected.iter().collect();
        if selected.len() != config.selected.len() {
            return Err("duplicate_source");
        }
        for id in selected {
            let pin = config.references.get(id).ok_or("unknown_source")?;
            let record = pin.load()?;
            sources.push(audit(pin, &record, "human/reference-data"));
            references.push(json!({"source": sources.last().unwrap(), "text": record.text}));
        }
        let tools = registry.descriptions();
        let material = json!({"template": TEMPLATE, "policy": policy, "sources": sources,
            "environment": config.environment, "tools": tools, "references": references});
        let key = digest(&serde_json::to_vec(&material).unwrap());
        let cache_hit = self.cache.as_ref().is_some_and(|old| old.key == key);
        if !cache_hit {
            let system = json!({"template": TEMPLATE, "policy": material["policy"],
                "environment": config.environment, "tools": tools});
            let mut messages = vec![Message::new_system_message(system)];
            if !references.is_empty() {
                messages.push(Message::new_human_message(
                    json!({"reference_data": references}),
                ));
            }
            self.cache = Some(Prefix {
                key: key.clone(),
                messages,
                sources,
            });
        }
        let prefix = self.cache.as_ref().unwrap();
        let mut messages = prefix.messages.clone();
        messages.extend_from_slice(history);
        let bytes = serde_json::to_vec(&messages).unwrap();
        if bytes.len() > config.max_request_bytes {
            return Err("request_budget");
        }
        Ok(ModelInput {
            template: TEMPLATE.into(),
            prefix_sha256: key,
            input_sha256: digest(&bytes),
            cache_hit,
            serialized_bytes: bytes.len(),
            sources: prefix.sources.clone(),
            messages,
        })
    }
    // endregion assemble
}

fn audit(pin: &Pin, record: &Record, placement: &str) -> SourceAudit {
    SourceAudit {
        id: record.id.clone(),
        version: record.version.clone(),
        sha256: pin.sha256.clone(),
        text_bytes: record.text.len(),
        placement: placement.into(),
    }
}
