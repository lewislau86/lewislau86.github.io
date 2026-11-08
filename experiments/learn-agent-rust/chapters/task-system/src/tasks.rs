use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

pub type Result<T> = std::result::Result<T, Error>;

#[derive(Debug, PartialEq, Eq)]
pub struct Error {
    pub code: &'static str,
    pub committed: bool,
}

impl Error {
    pub fn before(code: &'static str) -> Self {
        Self {
            code,
            committed: false,
        }
    }
    pub fn after(code: &'static str) -> Self {
        Self {
            code,
            committed: true,
        }
    }
}

// region model
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    Pending,
    Running,
    Completed,
    Failed,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Task {
    pub id: String,
    pub title: String,
    pub depends_on: Vec<String>,
    pub status: Status,
    pub attempts: u32,
    pub max_attempts: u32,
    pub result: Option<String>,
    pub last_error: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Board {
    pub schema: u32,
    pub revision: u64,
    pub tasks: Vec<Task>,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
pub enum Update {
    Add {
        id: String,
        title: String,
        depends_on: Vec<String>,
        max_attempts: u32,
    },
    SetDependencies {
        id: String,
        depends_on: Vec<String>,
    },
    Start {
        id: String,
    },
    Complete {
        id: String,
        attempt: u32,
        result: String,
    },
    Fail {
        id: String,
        attempt: u32,
        error: String,
    },
    Retry {
        id: String,
    },
}
// endregion model

fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 40
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}

fn text(value: &str, limit: usize) -> bool {
    !value.trim().is_empty() && value.len() <= limit
}

impl Board {
    pub fn empty() -> Self {
        Self {
            schema: 1,
            revision: 0,
            tasks: vec![],
        }
    }

    pub fn task(&self, id: &str) -> Result<&Task> {
        self.tasks
            .iter()
            .find(|t| t.id == id)
            .ok_or(Error::before("task_missing"))
    }

    fn task_mut(&mut self, id: &str) -> Result<&mut Task> {
        self.tasks
            .iter_mut()
            .find(|t| t.id == id)
            .ok_or(Error::before("task_missing"))
    }

    fn dependencies_done(&self, task: &Task) -> bool {
        task.depends_on
            .iter()
            .all(|id| self.task(id).is_ok_and(|t| t.status == Status::Completed))
    }

    // region graph
    fn visit<'a>(
        &'a self,
        id: &'a str,
        visiting: &mut BTreeSet<&'a str>,
        done: &mut BTreeSet<&'a str>,
    ) -> Result<()> {
        if done.contains(id) {
            return Ok(());
        }
        if !visiting.insert(id) {
            return Err(Error::before("dependency_cycle"));
        }
        for dependency in &self.task(id)?.depends_on {
            self.visit(dependency, visiting, done)?;
        }
        visiting.remove(id);
        done.insert(id);
        Ok(())
    }

    pub fn validate(&self) -> Result<()> {
        if self.schema != 1 {
            return Err(Error::before("schema_version"));
        }
        if self.tasks.len() > 32 {
            return Err(Error::before("task_limit"));
        }
        let mut ids = BTreeSet::new();
        for task in &self.tasks {
            if !identifier(&task.id) || !text(&task.title, 160) {
                return Err(Error::before("invalid_task"));
            }
            if !ids.insert(task.id.as_str()) {
                return Err(Error::before("duplicate_id"));
            }
            if task.depends_on.len() > 8 {
                return Err(Error::before("dependency_limit"));
            }
            let mut dependencies = BTreeSet::new();
            for id in &task.depends_on {
                if !dependencies.insert(id) {
                    return Err(Error::before("duplicate_dependency"));
                }
                self.task(id)
                    .map_err(|_| Error::before("dependency_missing"))?;
            }
        }
        let mut visiting = BTreeSet::new();
        let mut done = BTreeSet::new();
        for task in &self.tasks {
            self.visit(&task.id, &mut visiting, &mut done)?;
        }
        let mut running = 0;
        for task in &self.tasks {
            if !(1..=5).contains(&task.max_attempts) || task.attempts > task.max_attempts {
                return Err(Error::before("invalid_attempts"));
            }
            if task.result.as_ref().is_some_and(|s| !text(s, 512))
                || task.last_error.as_ref().is_some_and(|s| !text(s, 512))
            {
                return Err(Error::before("invalid_detail"));
            }
            match task.status {
                Status::Pending => {
                    if task.result.is_some()
                        || (task.attempts == 0 && task.last_error.is_some())
                        || (task.attempts > 0
                            && (task.last_error.is_none() || task.attempts == task.max_attempts))
                    {
                        return Err(Error::before("invalid_state"));
                    }
                }
                Status::Running => {
                    running += 1;
                    if task.attempts == 0 || task.result.is_some() {
                        return Err(Error::before("invalid_state"));
                    }
                }
                Status::Completed => {
                    if task.attempts == 0 || task.result.is_none() {
                        return Err(Error::before("invalid_state"));
                    }
                }
                Status::Failed => {
                    if task.attempts == 0 || task.result.is_some() || task.last_error.is_none() {
                        return Err(Error::before("invalid_state"));
                    }
                }
            }
            if task.status != Status::Pending && !self.dependencies_done(task) {
                return Err(Error::before("dependency_incomplete"));
            }
        }
        if running > 1 {
            return Err(Error::before("multiple_running"));
        }
        Ok(())
    }
    // endregion graph

    // region transition
    pub fn propose(&self, expected: u64, update: Update) -> Result<Self> {
        self.validate()?;
        if expected != self.revision {
            return Err(Error::before("revision_conflict"));
        }
        let mut next = self.clone();
        match update {
            Update::Add {
                id,
                title,
                depends_on,
                max_attempts,
            } => {
                if next.tasks.iter().any(|t| t.id == id) {
                    return Err(Error::before("duplicate_id"));
                }
                next.tasks.push(Task {
                    id,
                    title,
                    depends_on,
                    max_attempts,
                    status: Status::Pending,
                    attempts: 0,
                    result: None,
                    last_error: None,
                });
            }
            Update::SetDependencies { id, depends_on } => {
                let task = next.task_mut(&id)?;
                if task.status != Status::Pending || task.attempts != 0 {
                    return Err(Error::before("dependencies_frozen"));
                }
                task.depends_on = depends_on;
            }
            Update::Start { id } => {
                let task = next.task(&id)?;
                if task.status != Status::Pending {
                    return Err(Error::before("illegal_transition"));
                }
                if next.tasks.iter().any(|t| t.status == Status::Running) {
                    return Err(Error::before("executor_busy"));
                }
                if !next.dependencies_done(task) {
                    return Err(Error::before("dependency_incomplete"));
                }
                if task.attempts >= task.max_attempts {
                    return Err(Error::before("attempt_limit"));
                }
                let task = next.task_mut(&id)?;
                task.status = Status::Running;
                task.attempts += 1; // Persist this reservation before dispatching external work.
            }
            Update::Complete {
                id,
                attempt,
                result,
            } => {
                let task = next.task_mut(&id)?;
                if task.status != Status::Running {
                    return Err(Error::before("illegal_transition"));
                }
                if task.attempts != attempt {
                    return Err(Error::before("attempt_conflict"));
                }
                if !text(&result, 512) {
                    return Err(Error::before("invalid_detail"));
                }
                task.status = Status::Completed;
                task.result = Some(result);
            }
            Update::Fail { id, attempt, error } => {
                let task = next.task_mut(&id)?;
                if task.status != Status::Running {
                    return Err(Error::before("illegal_transition"));
                }
                if task.attempts != attempt {
                    return Err(Error::before("attempt_conflict"));
                }
                if !text(&error, 512) {
                    return Err(Error::before("invalid_detail"));
                }
                task.status = Status::Failed;
                task.last_error = Some(error);
            }
            Update::Retry { id } => {
                let task = next.task_mut(&id)?;
                if task.status != Status::Failed {
                    return Err(Error::before("illegal_transition"));
                }
                if task.attempts >= task.max_attempts {
                    return Err(Error::before("attempt_limit"));
                }
                task.status = Status::Pending; // Preserve attempts and last_error.
            }
        }
        next.revision = next
            .revision
            .checked_add(1)
            .ok_or(Error::before("revision_limit"))?;
        next.validate()?;
        Ok(next)
    }
    // endregion transition

    // region queries
    pub fn ready(&self) -> Vec<&str> {
        if self.tasks.iter().any(|t| t.status == Status::Running) {
            return vec![];
        }
        self.tasks
            .iter()
            .filter(|t| {
                t.status == Status::Pending
                    && t.attempts < t.max_attempts
                    && self.dependencies_done(t)
            })
            .map(|t| t.id.as_str())
            .collect()
    }

    pub fn reconcile(&self) -> Vec<&str> {
        self.tasks
            .iter()
            .filter(|t| t.status == Status::Running)
            .map(|t| t.id.as_str())
            .collect()
    }
    // endregion queries
}
