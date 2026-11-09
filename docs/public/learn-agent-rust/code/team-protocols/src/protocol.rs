use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::io::Write;
use std::path::Path;

pub type Check<T> = Result<T, &'static str>;

// region contracts
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Member {
    Lead,
    Core,
    Config,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Plan {
    pub revision: u32,
    pub path: String,
    pub content: String,
}

impl Plan {
    pub fn digest(&self) -> String {
        hash(&serde_json::to_vec(self).expect("serializable plan"))
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Decision {
    Approve,
    Reject,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum Message {
    PlanRequest {
        request_id: String,
        plan: Plan,
        ttl: u64,
    },
    PlanResponse {
        request_id: String,
        decision: Decision,
        feedback: String,
    },
    ShutdownRequest {
        request_id: String,
        reason: String,
        ttl: u64,
    },
    ShutdownResponse {
        request_id: String,
        decision: Decision,
        feedback: String,
    },
    Progress {
        request_id: String,
        text: String,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Kind {
    Plan,
    Shutdown,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    Pending,
    Approved,
    Rejected,
    Expired,
    Cancelled,
    Executing,
    Completed,
    Failed,
}

#[derive(Debug, Clone, Serialize)]
pub struct Request {
    pub id: String,
    pub kind: Kind,
    pub requester: Member,
    pub responder: Member,
    pub plan: Option<Plan>,
    pub digest: Option<String>,
    pub deadline: u64,
    pub status: Status,
    pub feedback: String,
}
// endregion contracts

#[derive(Debug, Clone, Serialize)]
pub struct Event {
    pub id: String,
    pub action: String,
    pub detail: String,
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct Registry {
    pub now: u64,
    pub requests: BTreeMap<String, Request>,
    pub closing: BTreeSet<Member>,
    pub events: Vec<Event>,
    pub writes: usize,
}

pub fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

pub fn decode(raw: &str) -> Check<Message> {
    if raw.len() > 4096 {
        return Err("message_size");
    }
    serde_json::from_str(raw).map_err(|_| "invalid_message")
}

impl Message {
    pub fn id(&self) -> &str {
        match self {
            Self::PlanRequest { request_id, .. }
            | Self::PlanResponse { request_id, .. }
            | Self::ShutdownRequest { request_id, .. }
            | Self::ShutdownResponse { request_id, .. }
            | Self::Progress { request_id, .. } => request_id,
        }
    }
}

impl Registry {
    pub fn log(&mut self, id: &str, action: &str, detail: &str) {
        self.events.push(Event {
            id: id.into(),
            action: action.into(),
            detail: detail.into(),
        });
    }

    // region deadlines
    pub fn advance(&mut self, now: u64) -> Check<()> {
        if now < self.now {
            return Err("clock_regression");
        }
        self.now = now;
        let ids: Vec<_> = self
            .requests
            .values()
            .filter(|r| {
                now >= r.deadline
                    && (r.status == Status::Pending
                        || (r.kind == Kind::Plan && r.status == Status::Approved))
            })
            .map(|r| r.id.clone())
            .collect();
        for id in ids {
            self.requests.get_mut(&id).unwrap().status = Status::Expired;
            self.log(&id, "expired", "deadline reached");
        }
        Ok(())
    }
    // endregion deadlines

    pub fn dispatch(&mut self, from: Member, to: Member, message: &Message) -> Check<()> {
        let id = message.id();
        if id.is_empty()
            || id.len() > 48
            || !id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
        {
            return Err("invalid_id");
        }
        if serde_json::to_vec(message).unwrap().len() > 4096 {
            return Err("message_size");
        }
        match message {
            Message::PlanRequest { plan, ttl, .. } => {
                if from == Member::Lead || to != Member::Lead {
                    return Err("wrong_direction");
                }
                if self.closing.contains(&from) {
                    return Err("member_closing");
                }
                if plan.revision == 0
                    || plan.path.is_empty()
                    || plan.path.len() > 128
                    || plan.content.is_empty()
                    || plan.content.len() > 512
                {
                    return Err("invalid_plan");
                }
                self.open(id, Kind::Plan, from, to, Some(plan.clone()), *ttl)
            }
            Message::ShutdownRequest { reason, ttl, .. } => {
                if from != Member::Lead || to == Member::Lead {
                    return Err("wrong_direction");
                }
                if reason.is_empty() || reason.len() > 512 {
                    return Err("invalid_reason");
                }
                if self.closing.contains(&to) {
                    return Err("member_closing");
                }
                self.open(id, Kind::Shutdown, from, to, None, *ttl)?;
                self.closing.insert(to);
                // Freeze new work immediately, invalidate outstanding plan grants.
                self.cancel_plans(to);
                Ok(())
            }
            Message::PlanResponse {
                decision, feedback, ..
            } => self.respond(from, to, id, Kind::Plan, *decision, feedback),
            Message::ShutdownResponse {
                decision, feedback, ..
            } => self.respond(from, to, id, Kind::Shutdown, *decision, feedback),
            Message::Progress { text, .. } => {
                let r = self.requests.get(id).ok_or("unknown_request")?;
                if r.kind != Kind::Plan || r.requester != from || r.responder != to {
                    return Err("wrong_identity");
                }
                if text.len() > 512 {
                    return Err("progress_size");
                }
                self.log(id, "progress", text);
                Ok(())
            }
        }
    }

    fn open(
        &mut self,
        id: &str,
        kind: Kind,
        requester: Member,
        responder: Member,
        plan: Option<Plan>,
        ttl: u64,
    ) -> Check<()> {
        if self.requests.contains_key(id) {
            return Err("duplicate_request");
        }
        if self.requests.len() >= 16 {
            return Err("request_limit");
        }
        if ttl == 0 || ttl > 100 {
            return Err("invalid_ttl");
        }
        let deadline = self.now.checked_add(ttl).ok_or("deadline_overflow")?;
        let digest = plan.as_ref().map(Plan::digest);
        self.requests.insert(
            id.into(),
            Request {
                id: id.into(),
                kind,
                requester,
                responder,
                plan,
                digest,
                deadline,
                status: Status::Pending,
                feedback: String::new(),
            },
        );
        self.log(
            id,
            "opened",
            &format!("{kind:?}:{requester:?}->{responder:?}"),
        );
        Ok(())
    }

    // region match-response
    fn respond(
        &mut self,
        from: Member,
        to: Member,
        id: &str,
        kind: Kind,
        decision: Decision,
        feedback: &str,
    ) -> Check<()> {
        let r = self.requests.get_mut(id).ok_or("unknown_request")?;
        if r.kind != kind {
            return Err("wrong_kind");
        }
        if r.responder != from || r.requester != to {
            return Err("wrong_identity");
        }
        if r.status != Status::Pending {
            return Err("request_not_pending");
        }
        if feedback.len() > 512 {
            return Err("feedback_size");
        }
        r.status = match decision {
            Decision::Approve => Status::Approved,
            Decision::Reject => Status::Rejected,
        };
        r.feedback = feedback.into();
        if kind == Kind::Shutdown && decision == Decision::Reject {
            self.closing.remove(&from);
        }
        self.log(id, "response", &format!("{from:?}:{decision:?}"));
        Ok(())
    }
    // endregion match-response

    pub fn cancel(&mut self, from: Member, id: &str) -> Check<()> {
        let r = self.requests.get_mut(id).ok_or("unknown_request")?;
        if from != r.requester {
            return Err("wrong_identity");
        }
        if !matches!(r.status, Status::Pending | Status::Approved) {
            return Err("request_terminal");
        }
        r.status = Status::Cancelled;
        self.log(id, "cancelled", "requester cancelled");
        Ok(())
    }

    fn cancel_plans(&mut self, member: Member) {
        let ids: Vec<_> = self
            .requests
            .values()
            .filter(|r| {
                r.kind == Kind::Plan
                    && r.requester == member
                    && matches!(r.status, Status::Pending | Status::Approved)
            })
            .map(|r| r.id.clone())
            .collect();
        for id in ids {
            self.requests.get_mut(&id).unwrap().status = Status::Cancelled;
            self.log(&id, "cancelled", "member closing");
        }
    }

    pub fn stopped(&mut self, member: Member, panicked: bool) {
        self.closing.insert(member);
        self.cancel_plans(member);
        for r in self.requests.values_mut() {
            if r.kind == Kind::Shutdown && r.responder == member && r.status == Status::Pending {
                r.status = if panicked {
                    Status::Failed
                } else {
                    Status::Cancelled
                };
            }
        }
        self.log(
            "lifecycle",
            "joined",
            &format!("{member:?}:panic={panicked}"),
        );
    }

    // region write-gate
    pub fn execute(&mut self, member: Member, id: &str, plan: &Plan, root: &Path) -> Check<()> {
        if self.closing.contains(&member) {
            return Err("member_closing");
        }
        let r = self.requests.get(id).ok_or("unknown_request")?;
        if r.kind != Kind::Plan || r.requester != member {
            return Err("wrong_identity");
        }
        if r.status != Status::Approved {
            return Err("not_approved");
        }
        if self.now >= r.deadline {
            return Err("grant_expired");
        }
        if r.digest.as_deref() != Some(plan.digest().as_str()) {
            return Err("plan_changed");
        }
        // Approval is only one condition. The tool's own ACL still applies.
        if member != Member::Core || plan.path != "review.txt" {
            return Err("permission_denied");
        }
        self.requests.get_mut(id).unwrap().status = Status::Executing;
        self.log(id, "executing", "approved exact plan; create_new");
        let result = (|| {
            let mut file = std::fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(root.join(&plan.path))?;
            file.write_all(plan.content.as_bytes())
        })();
        let status = if result.is_ok() {
            self.writes += 1;
            Status::Completed
        } else {
            Status::Failed
        };
        self.requests.get_mut(id).unwrap().status = status;
        self.log(
            id,
            if result.is_ok() {
                "completed"
            } else {
                "failed"
            },
            "local file operation",
        );
        result.map_err(|_| "write_failed")
    }
    // endregion write-gate
}
