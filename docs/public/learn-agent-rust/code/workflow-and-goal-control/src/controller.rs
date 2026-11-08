use crate::{
    fixture::{Fixture, Proposal},
    goal::{Goal, Verdict, read_bounded},
};
use serde::Serialize;
use serde_json::{Value, json};
use std::{fs, path::Path};

#[derive(Clone, Serialize)]
pub struct Limits {
    pub episodes: usize,
    pub model_calls: usize,
    pub tools: usize,
    pub write_bytes: usize,
    pub stagnant: usize,
}
impl Default for Limits {
    fn default() -> Self {
        Self {
            episodes: 4,
            model_calls: 12,
            tools: 8,
            write_bytes: 256,
            stagnant: 2,
        }
    }
}

// region budget
#[derive(Default, Serialize)]
pub struct Usage {
    pub episodes: usize,
    pub model_calls: usize,
    pub tools: usize,
    pub write_bytes: usize,
}

pub fn reserve(used: &mut usize, limit: usize, amount: usize) -> bool {
    match used.checked_add(amount) {
        Some(next) if next <= limit => {
            *used = next;
            true
        }
        _ => false,
    }
}
// endregion budget

#[derive(Serialize)]
pub struct Report {
    scenario: String,
    pub status: &'static str,
    pub reason: String,
    pub goal_verified: bool,
    pub normal_returns: usize,
    pub reads: usize,
    pub writes: usize,
    pub contract: Option<Value>,
    pub used: Usage,
    limits: Limits,
    pub verdict: Verdict,
    pub trace: Vec<Value>,
}

impl Report {
    fn event(&mut self, value: Value) {
        self.trace.push(value);
    }

    // region handoff
    fn finish(mut self, root: &Path, reason: &str, completed: bool) -> Self {
        self.status = if completed {
            "completed"
        } else {
            "needs_human"
        };
        self.reason = reason.into();
        self.goal_verified = self.verdict.kind == "satisfied";
        self.event(json!({"phase":"terminal", "status":self.status, "reason":reason}));
        if !completed {
            let handoff = json!({
                "goal":"report.txt must match the prepared source: apples, pears, total",
                "contract":self.contract,
                "reason":reason, "usage":self.used, "limits":self.limits,
                "verdict":self.verdict, "writes":self.writes,
                "instruction":"inspect source.txt and report.txt; this file does not authorize a restart"
            });
            if fs::write(
                root.join("handoff.json"),
                serde_json::to_vec_pretty(&handoff).unwrap(),
            )
            .is_err()
            {
                self.reason = "handoff_save_failed".into();
                self.event(json!({"phase":"handoff_error"}));
            }
        }
        self
    }
    // endregion handoff
}

// region execute
fn execute(
    root: &Path,
    proposal: Proposal,
    fixture: &mut Fixture,
    report: &mut Report,
) -> Result<(), &'static str> {
    if !reserve(&mut report.used.tools, fixture.limits.tools, 1) {
        return Err("tool_budget");
    }
    match proposal {
        Proposal::ReadSource => {
            let text = read_bounded(&root.join("source.txt")).map_err(|_| "tool_read_failed")?;
            fixture.observe(&text);
            report.reads += 1;
            report.event(json!({"phase":"tool", "name":"read_source", "ok":true}));
        }
        Proposal::Write { path, text } => {
            if path != "report.txt" {
                return Err("policy_denied");
            }
            if !reserve(
                &mut report.used.write_bytes,
                fixture.limits.write_bytes,
                text.len(),
            ) {
                return Err("byte_budget");
            }
            let temp = root.join("report.tmp");
            if fs::write(&temp, &text)
                .and_then(|_| fs::rename(&temp, root.join("report.txt")))
                .is_err()
            {
                let _ = fs::remove_file(temp);
                return Err("tool_write_failed");
            }
            report.writes += 1;
            fixture.after_write(root);
            report.event(
                json!({"phase":"tool", "name":"write_report", "ok":true, "bytes":text.len()}),
            );
        }
        _ => unreachable!(),
    }
    Ok(())
}
// endregion execute

// region episode
fn episode(root: &Path, fixture: &mut Fixture, report: &mut Report) -> Result<(), &'static str> {
    let mut step = 0;
    loop {
        if fixture.cancelled(&report.used) {
            return Err("cancelled");
        }
        if !reserve(&mut report.used.model_calls, fixture.limits.model_calls, 1) {
            return Err("model_budget");
        }
        let proposal = fixture.next(report.used.episodes, step, &report.verdict.feedback);
        step += 1;
        report.event(json!({"phase":"model", "call":report.used.model_calls, "episode":report.used.episodes}));
        match proposal {
            Proposal::Final(_answer) => {
                report.normal_returns += 1;
                return Ok(());
            }
            Proposal::Handoff => return Err("explicit_handoff"),
            Proposal::ModelError => return Err("model_error"),
            Proposal::InvalidResponse => return Err("invalid_response"),
            action => execute(root, action, fixture, report)?,
        }
    }
}
// endregion episode

pub fn run(root: &Path, mut fixture: Fixture) -> Report {
    let mut report = Report {
        scenario: fixture.name.clone(),
        status: "running",
        reason: String::new(),
        goal_verified: false,
        normal_returns: 0,
        reads: 0,
        writes: 0,
        contract: None,
        used: Usage::default(),
        limits: fixture.limits.clone(),
        verdict: Verdict {
            kind: "blocked",
            score: 0,
            feedback: Vec::new(),
        },
        trace: Vec::new(),
    };
    report.event(json!({"phase":"prepare"}));
    let goal = match Goal::prepare(root) {
        Ok(goal) => goal,
        Err(code) => {
            report.verdict.feedback.push(format!("source:{code}"));
            return report.finish(root, "input_blocked", false);
        }
    };
    report.contract = Some(serde_json::to_value(&goal).unwrap());
    report.verdict = goal.verify(root);
    report.event(json!({"phase":"precheck", "verdict":report.verdict}));
    if report.verdict.kind == "satisfied" {
        return report.finish(root, "already_satisfied", true);
    }
    let mut best = report.verdict.score;
    let mut stagnant = 0;
    // region control
    loop {
        if !reserve(&mut report.used.episodes, fixture.limits.episodes, 1) {
            return report.finish(root, "episode_limit", false);
        }
        let returned = episode(root, &mut fixture, &mut report);
        // Always re-read the actual artifact, even when a tool or model just failed.
        report.verdict = goal.verify(root);
        report.event(json!({"phase":"evaluate", "episode":report.used.episodes, "normal":returned.is_ok(), "verdict":report.verdict}));
        if let Err(reason) = returned {
            return report.finish(root, reason, false);
        }
        match report.verdict.kind {
            "satisfied" => return report.finish(root, "goal_satisfied", true),
            "blocked" => return report.finish(root, "goal_blocked", false),
            _ => {}
        }
        if report.verdict.score > best {
            best = report.verdict.score;
            stagnant = 0;
        } else {
            stagnant += 1;
        }
        if stagnant >= fixture.limits.stagnant {
            return report.finish(root, "no_progress", false);
        }
        if report.used.episodes >= fixture.limits.episodes {
            return report.finish(root, "episode_limit", false);
        }
        report.event(json!({"phase":"continue", "best_score":best, "stagnant":stagnant, "feedback":report.verdict.feedback}));
    }
    // endregion control
}
