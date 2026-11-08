use crate::{
    controller::{Limits, Usage},
    goal::{self, Counts},
};
use std::{fs, io, path::Path};

pub const SOURCE: &str = "apples=7\npears=11\n";
pub const VALID: &str = "apples=7\npears=11\ntotal=18\n";
pub const PARTIAL: &str = "apples=7\npears=11\n";
pub const NAMES: &[&str] = &[
    "normal",
    "false-final",
    "continue-success",
    "wrong-total",
    "no-progress",
    "episode-limit",
    "model-budget",
    "tool-budget",
    "byte-budget",
    "cancelled-after-read",
    "explicit-handoff",
    "missing-source",
    "malformed-source",
    "denied-path",
    "tool-write-failed",
    "model-error",
    "valid-then-model-error",
    "invalid-report",
    "changed-source",
    "already-satisfied",
    "missing-final",
    "exact-budget",
];

// region proposals
pub enum Proposal {
    ReadSource,
    Write { path: String, text: String },
    Final(String),
    Handoff,
    ModelError,
    InvalidResponse,
}

pub struct Fixture {
    pub name: String,
    pub limits: Limits,
    pub observed: Option<Counts>,
}
// endregion proposals

impl Fixture {
    pub fn new(name: &str) -> Option<Self> {
        if !NAMES.contains(&name) {
            return None;
        }
        let mut limits = Limits::default();
        match name {
            "episode-limit" | "false-final" | "invalid-report" => limits.episodes = 2,
            "model-budget" => limits.model_calls = 3,
            "tool-budget" => limits.tools = 2,
            "byte-budget" => limits.write_bytes = PARTIAL.len(),
            "exact-budget" => {
                limits = Limits {
                    episodes: 1,
                    model_calls: 3,
                    tools: 2,
                    write_bytes: VALID.len(),
                    stagnant: 2,
                }
            }
            _ => {}
        }
        Some(Self {
            name: name.into(),
            limits,
            observed: None,
        })
    }

    pub fn prepare(&self, root: &Path) -> io::Result<()> {
        if self.name != "missing-source" {
            fs::write(
                root.join("source.txt"),
                if self.name == "malformed-source" {
                    "apples=-7\npears=11\n"
                } else {
                    SOURCE
                },
            )?;
        }
        if self.name == "already-satisfied" {
            fs::write(root.join("report.txt"), VALID)?;
        }
        if self.name == "tool-write-failed" {
            fs::create_dir(root.join("report.txt"))?;
        }
        Ok(())
    }

    fn report(&self, complete: bool, wrong: bool) -> String {
        let values = self
            .observed
            .as_ref()
            .expect("script requires successful source observation");
        let mut result = format!("apples={}\npears={}\n", values["apples"], values["pears"]);
        if complete {
            result.push_str(&format!(
                "total={}\n",
                values.values().sum::<u32>() + u32::from(wrong)
            ));
        }
        result
    }

    // region model
    pub fn next(&self, episode: usize, step: usize, feedback: &[String]) -> Proposal {
        if self.name == "false-final" {
            return Proposal::Final("目标完成，验收通过！".into());
        }
        if self.name == "explicit-handoff" && step == 1 {
            return Proposal::Handoff;
        }
        if self.name == "model-error" && step == 1 {
            return Proposal::ModelError;
        }
        if episode == 1 && step == 0 {
            return Proposal::ReadSource;
        }
        let write_step = if episode == 1 { 1 } else { 0 };
        if step == write_step {
            if self.name == "denied-path" {
                return Proposal::Write {
                    path: "../escape.txt".into(),
                    text: "forged".into(),
                };
            }
            if self.name == "invalid-report" {
                return Proposal::Write {
                    path: "report.txt".into(),
                    text: "apples=7\napples=7\npears=11\ntotal=18\n".into(),
                };
            }
            let mut complete = !matches!(self.name.as_str(), "no-progress" | "episode-limit");
            if matches!(
                self.name.as_str(),
                "continue-success" | "model-budget" | "tool-budget" | "byte-budget"
            ) {
                complete = episode > 1 && feedback == ["missing:total"];
            }
            let wrong = self.name == "wrong-total" && episode == 1;
            if self.name == "wrong-total" && episode > 1 && feedback != ["wrong:total"] {
                return Proposal::InvalidResponse;
            }
            return Proposal::Write {
                path: "report.txt".into(),
                text: self.report(complete, wrong),
            };
        }
        if self.name == "valid-then-model-error" {
            return Proposal::ModelError;
        }
        if self.name == "missing-final" {
            return Proposal::InvalidResponse;
        }
        Proposal::Final("库存核对表已生成".into())
    }
    // endregion model

    pub fn observe(&mut self, text: &str) {
        self.observed = goal::parse(text, &["apples", "pears"]).ok();
    }
    pub fn cancelled(&self, used: &Usage) -> bool {
        self.name == "cancelled-after-read" && used.tools >= 1
    }
    pub fn after_write(&self, root: &Path) {
        // Trusted host fault fixture: emulate another process changing the input, not an agent tool.
        if self.name == "changed-source" {
            fs::write(root.join("source.txt"), "apples=8\npears=11\n").unwrap();
        }
    }
}
