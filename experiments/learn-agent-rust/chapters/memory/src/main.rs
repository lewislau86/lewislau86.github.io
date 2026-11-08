use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
};

type Result<T> = std::result::Result<T, &'static str>;
const MAX_BYTES: u64 = 65_536;
const MAX_EVENTS: usize = 64;

// region records
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Source {
    session: String,
    turn: u64,
    role: String,
    quote: String,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Action {
    Set { value: String },
    Forget,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Event {
    revision: u64,
    scope: String,
    key: String,
    action: Action,
    source: Source,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Store {
    schema: u32,
    events: Vec<Event>,
}

type Facts = BTreeMap<(String, String), Event>;
// endregion records

fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"-_.".contains(&b))
}

fn read_bounded(path: &Path, limit: u64, error: &'static str) -> Result<Vec<u8>> {
    let mut bytes = Vec::new();
    File::open(path)
        .map_err(|_| error)?
        .take(limit + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| error)?;
    if bytes.len() as u64 > limit {
        return Err("size_limit");
    }
    Ok(bytes)
}

// region extract
fn extract(scope: &str, source: Source) -> Result<Event> {
    if !identifier(scope) || !identifier(&source.session) || source.turn == 0 {
        return Err("invalid_source");
    }
    if source.role != "user" {
        return Err("untrusted_origin");
    }
    if source.quote.len() > 512 || source.quote.chars().any(char::is_control) {
        return Err("invalid_quote");
    }
    let (key, action) = if let Some(body) = source.quote.strip_prefix("请记住：") {
        let (key, value) = body.split_once('=').ok_or("invalid_fact")?;
        if value.is_empty() || value.len() > 160 {
            return Err("invalid_fact");
        }
        (
            key.to_owned(),
            Action::Set {
                value: value.to_owned(),
            },
        )
    } else if let Some(key) = source.quote.strip_prefix("请忘记：") {
        (key.to_owned(), Action::Forget)
    } else {
        return Err("no_memory_intent");
    };
    if !matches!(key.as_str(), "reply_language" | "run_command") {
        return Err("unknown_key");
    }
    Ok(Event {
        revision: 0,
        scope: scope.to_owned(),
        key,
        action,
        source,
    })
}
// endregion extract

// region replay
fn replay(store: &Store) -> Result<Facts> {
    if store.schema != 1 {
        return Err("unsupported_schema");
    }
    if store.events.len() > MAX_EVENTS {
        return Err("event_limit");
    }
    let mut facts = Facts::new();
    for (index, event) in store.events.iter().enumerate() {
        if event.revision != index as u64 + 1 {
            return Err("invalid_revision");
        }
        let mut parsed =
            extract(&event.scope, event.source.clone()).map_err(|_| "invalid_record")?;
        parsed.revision = event.revision;
        if parsed != *event {
            return Err("invalid_record");
        }
        let identity = (event.scope.clone(), event.key.clone());
        match event.action {
            Action::Set { .. } => {
                facts.insert(identity, event.clone());
            }
            Action::Forget => {
                if facts.remove(&identity).is_none() {
                    return Err("invalid_tombstone");
                }
            }
        }
    }
    Ok(facts)
}

fn load(root: &Path) -> Result<Store> {
    let path = root.join("memory.json");
    match fs::symlink_metadata(&path) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return Ok(Store {
                schema: 1,
                events: vec![],
            });
        }
        Err(_) => return Err("read_failed"),
        Ok(meta) if !meta.file_type().is_file() => return Err("invalid_store_file"),
        Ok(_) => {}
    }
    let bytes = read_bounded(&path, MAX_BYTES, "read_failed")?;
    let store: Store = serde_json::from_slice(&bytes).map_err(|_| "corrupt_store")?;
    replay(&store)?;
    Ok(store)
}
// endregion replay

struct OwnedFile(PathBuf);
impl Drop for OwnedFile {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

// region persist
fn save(root: &Path, store: &Store, fail_before_rename: bool) -> Result<()> {
    let mut bytes = serde_json::to_vec_pretty(store).map_err(|_| "encode_failed")?;
    bytes.push(b'\n');
    if bytes.len() as u64 > MAX_BYTES {
        return Err("size_limit");
    }
    let pending = root.join(".memory.pending");
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&pending)
        .map_err(|_| "pending_unavailable")?;
    let _cleanup = OwnedFile(pending.clone());
    file.write_all(&bytes).map_err(|_| "save_failed")?;
    file.sync_all().map_err(|_| "save_failed")?;
    drop(file);
    if fail_before_rename {
        return Err("injected_before_rename");
    }
    fs::rename(&pending, root.join("memory.json")).map_err(|_| "rename_failed")?;
    // On Unix, also synchronize the directory entry. A failure here is after commit.
    #[cfg(unix)]
    File::open(root)
        .and_then(|dir| dir.sync_all())
        .map_err(|_| "durability_unknown")?;
    Ok(())
}
// endregion persist

// region apply
fn apply(root: &Path, mut candidate: Event, expected: u64, fail: bool) -> Result<Value> {
    fs::create_dir_all(root).map_err(|_| "store_unavailable")?;
    let lock = root.join(".memory.lock");
    OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&lock)
        .map_err(|_| "store_busy")?;
    let _unlock = OwnedFile(lock);
    let mut store = load(root)?;
    let facts = replay(&store)?;
    let revision = store.events.len() as u64;
    if expected != revision {
        return Err("revision_conflict");
    }
    let identity = (candidate.scope.clone(), candidate.key.clone());
    let previous = facts.get(&identity);
    match &candidate.action {
        Action::Set { .. } if previous.is_some_and(|old| old.action == candidate.action) => {
            return Ok(json!({"status":"unchanged", "revision":revision}));
        }
        Action::Forget if previous.is_none() => return Err("fact_missing"),
        _ => {}
    }
    if store.events.len() >= MAX_EVENTS {
        return Err("event_limit");
    }
    candidate.revision = revision + 1;
    store.events.push(candidate);
    replay(&store)?;
    save(root, &store, fail)?;
    Ok(json!({"status":"saved", "revision":revision + 1}))
}
// endregion apply

// region recall
fn recall(root: &Path, scope: &str, key: &str) -> Result<Value> {
    if !identifier(scope) {
        return Err("invalid_scope");
    }
    if !matches!(key, "reply_language" | "run_command") {
        return Err("unknown_key");
    }
    let store = load(root)?;
    let facts = replay(&store)?;
    let fact = facts.get(&(scope.to_owned(), key.to_owned()));
    Ok(
        json!({"status":if fact.is_some() {"found"} else {"missing"},
        "revision":store.events.len(), "fact":fact}),
    )
}
// endregion recall

// region cli
fn execute(args: &[String]) -> Result<Value> {
    match args.first().map(String::as_str) {
        Some("recall") if args.len() == 4 => recall(Path::new(&args[1]), &args[2], &args[3]),
        Some("apply")
            if args.len() == 9 || (args.len() == 10 && args[9] == "--fail-before-rename") =>
        {
            let quote = String::from_utf8(read_bounded(
                Path::new(&args[8]),
                4096,
                "message_read_failed",
            )?)
            .map_err(|_| "invalid_utf8")?;
            let source = Source {
                session: args[3].clone(),
                turn: args[4].parse().map_err(|_| "invalid_turn")?,
                role: args[6].clone(),
                quote: quote.trim_end_matches('\n').to_owned(),
            };
            if args[7] != "--message" {
                return Err("usage");
            }
            let candidate = extract(&args[2], source)?;
            apply(
                Path::new(&args[1]),
                candidate,
                args[5].parse().map_err(|_| "invalid_expected")?,
                args.len() == 10,
            )
        }
        _ => Err("usage"),
    }
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match execute(&args) {
        Ok(value) => println!("{}", value),
        Err(error) => {
            println!("{}", json!({"status":"error", "error":error}));
            std::process::exit(1);
        }
    }
}
// endregion cli

#[cfg(test)]
mod tests {
    use super::*;
    fn event(quote: &str) -> Event {
        extract(
            "demo",
            Source {
                session: "A".into(),
                turn: 1,
                role: "user".into(),
                quote: quote.into(),
            },
        )
        .unwrap()
    }
    fn store(events: Vec<Event>) -> Store {
        Store { schema: 1, events }
    }
    fn numbered(mut event: Event, n: u64) -> Event {
        event.revision = n;
        event
    }

    #[test]
    fn update_and_forget_replay() {
        let a = numbered(event("请记住：reply_language=中文"), 1);
        let b = numbered(event("请记住：reply_language=English"), 2);
        let c = numbered(event("请忘记：reply_language"), 3);
        let facts = replay(&store(vec![a.clone(), b.clone()])).unwrap();
        assert_eq!(facts.values().next().unwrap(), &b);
        assert!(replay(&store(vec![a, b, c])).unwrap().is_empty());
    }
    #[test]
    fn rejects_revision_gap() {
        assert_eq!(
            replay(&store(vec![numbered(
                event("请记住：run_command=cargo run"),
                2
            )])),
            Err("invalid_revision")
        );
    }
    #[test]
    fn rejects_forged_quote() {
        let mut a = numbered(event("请记住：reply_language=中文"), 1);
        a.action = Action::Set {
            value: "English".into(),
        };
        assert_eq!(replay(&store(vec![a])), Err("invalid_record"));
    }
    #[test]
    fn rejects_orphan_tombstone() {
        assert_eq!(
            replay(&store(vec![numbered(event("请忘记：run_command"), 1)])),
            Err("invalid_tombstone")
        );
    }
    #[test]
    fn rejects_unknown_fields() {
        assert!(serde_json::from_str::<Store>(r#"{"schema":1,"events":[],"extra":1}"#).is_err());
    }
    #[test]
    fn scope_keeps_facts_separate() {
        let a = numbered(event("请记住：reply_language=中文"), 1);
        let mut b = numbered(event("请记住：reply_language=English"), 2);
        b.scope = "other".into();
        assert_eq!(replay(&store(vec![a, b])).unwrap().len(), 2);
    }
    #[test]
    fn rejects_control_characters() {
        let mut source = event("请记住：reply_language=中文").source;
        source.quote.push('\n');
        assert_eq!(extract("demo", source), Err("invalid_quote"));
    }
    #[test]
    fn schema_is_not_revision() {
        assert_eq!(
            replay(&Store {
                schema: 2,
                events: vec![]
            }),
            Err("unsupported_schema")
        );
    }
}
