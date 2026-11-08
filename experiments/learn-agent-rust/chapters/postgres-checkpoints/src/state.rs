use serde::{Deserialize, Serialize};

pub type Result<T> = std::result::Result<T, Error>;
#[derive(Debug, PartialEq, Eq)]
pub struct Error(pub &'static str);

// region state
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Phase {
    Model,
    ModelInFlight,
    Tools,
    ToolInFlight,
    Reconcile,
    Done,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Granularity {
    Tool,
    Batch,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "role", rename_all = "snake_case", deny_unknown_fields)]
pub enum Message {
    User { text: String },
    AssistantCalls { ids: Vec<String> },
    Tool { call_id: String, content: String },
    Assistant { text: String },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct State {
    pub format_version: u32,
    pub workflow_version: String,
    pub profile: String,
    pub granularity: Granularity,
    pub phase: Phase,
    pub messages: Vec<Message>,
    pub cursor: usize,
    pub model_turns: u32,
    pub tool_dispatches: u32,
    pub max_model_turns: u32,
    pub max_tool_dispatches: u32,
    pub uncertain: Option<String>,
}
// endregion state

pub fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 40
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}

impl State {
    pub fn new(profile: String, granularity: Granularity) -> Result<Self> {
        if !matches!(profile.as_str(), "read_only" | "effect")
            || (profile == "effect" && granularity == Granularity::Batch)
        {
            return Err(Error("invalid_profile"));
        }
        Ok(Self {
            format_version: 1,
            workflow_version: "p01-v1".into(),
            profile,
            granularity,
            phase: Phase::Model,
            messages: vec![Message::User {
                text: "读取说明并核对启动命令".into(),
            }],
            cursor: 0,
            model_turns: 0,
            tool_dispatches: 0,
            max_model_turns: 2,
            max_tool_dispatches: 2,
            uncertain: None,
        })
    }

    pub fn calls(&self) -> [&'static str; 2] {
        [
            "read-1",
            if self.profile == "effect" {
                "append-1"
            } else {
                "read-2"
            },
        ]
    }

    // region validate
    pub fn validate(&self) -> Result<()> {
        if self.format_version != 1 {
            return Err(Error("format_version"));
        }
        if self.workflow_version != "p01-v1" {
            return Err(Error("workflow_version"));
        }
        if !matches!(self.profile.as_str(), "read_only" | "effect")
            || (self.profile == "effect" && self.granularity == Granularity::Batch)
        {
            return Err(Error("invalid_profile"));
        }
        if self.max_model_turns != 2
            || self.max_tool_dispatches != 2
            || self.model_turns > 2
            || self.tool_dispatches > 2
            || self.cursor > 2
        {
            return Err(Error("invalid_budget"));
        }
        if serde_json::to_vec(self)
            .map_err(|_| Error("encode_failed"))?
            .len()
            > 16384
        {
            return Err(Error("state_limit"));
        }
        let calls = self.calls();
        let mut expected = vec![Message::User {
            text: "读取说明并核对启动命令".into(),
        }];
        let has_calls = self
            .messages
            .iter()
            .any(|m| matches!(m, Message::AssistantCalls { .. }));
        if has_calls {
            expected.push(Message::AssistantCalls {
                ids: calls.iter().map(|id| (*id).into()).collect(),
            });
            for (index, id) in calls.iter().enumerate().take(self.cursor) {
                let Some(Message::Tool { call_id, content }) = self.messages.get(index + 2) else {
                    return Err(Error("message_pairing"));
                };
                if call_id != id || content.trim().is_empty() || content.len() > 4096 {
                    return Err(Error("message_pairing"));
                }
                expected.push(self.messages[index + 2].clone());
            }
        } else if self.cursor != 0 {
            return Err(Error("message_pairing"));
        }
        if self.phase == Phase::Done {
            expected.push(Message::Assistant {
                text: "已核对启动命令 cargo run".into(),
            });
        }
        if self.messages != expected {
            return Err(Error("message_pairing"));
        }
        let valid = match self.phase {
            Phase::Model => {
                (self.model_turns == 0
                    && !has_calls
                    && self.cursor == 0
                    && self.tool_dispatches == 0)
                    || (self.model_turns == 1
                        && has_calls
                        && self.cursor == 2
                        && self.tool_dispatches == 2)
            }
            Phase::ModelInFlight => {
                (self.model_turns == 1
                    && !has_calls
                    && self.cursor == 0
                    && self.tool_dispatches == 0)
                    || (self.model_turns == 2
                        && has_calls
                        && self.cursor == 2
                        && self.tool_dispatches == 2)
            }
            Phase::Tools => {
                self.model_turns == 1
                    && has_calls
                    && self.cursor < 2
                    && self.tool_dispatches == self.cursor as u32
            }
            Phase::ToolInFlight => {
                self.model_turns == 1
                    && has_calls
                    && self.cursor < 2
                    && self.tool_dispatches
                        == if self.granularity == Granularity::Batch {
                            2
                        } else {
                            self.cursor as u32 + 1
                        }
            }
            Phase::Done => {
                self.model_turns == 2 && has_calls && self.cursor == 2 && self.tool_dispatches == 2
            }
            Phase::Reconcile => match self.uncertain.as_deref() {
                Some("model") => {
                    let mut copy = self.clone();
                    copy.phase = Phase::ModelInFlight;
                    copy.uncertain = None;
                    copy.validate().is_ok()
                }
                Some("tool") => {
                    let mut copy = self.clone();
                    copy.phase = Phase::ToolInFlight;
                    copy.uncertain = None;
                    copy.validate().is_ok()
                }
                _ => false,
            },
        };
        if !valid || (self.phase != Phase::Reconcile && self.uncertain.is_some()) {
            return Err(Error("invalid_state"));
        }
        Ok(())
    }
    // endregion validate
}
