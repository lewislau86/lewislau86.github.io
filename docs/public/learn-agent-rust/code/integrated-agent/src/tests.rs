use crate::{
    agent::validate_history,
    runtime::{Book, Usage},
    store::Store,
};
use langchain_rust::schemas::{Message, ToolCall};
use serde_json::json;

#[test]
fn due_identity_deduplicates_and_claim_is_compare_and_set() {
    let dir = tempfile::tempdir().unwrap();
    let store = Store::open(&dir.path().join("db")).unwrap();
    assert_eq!(store.trigger().unwrap(), 1);
    assert_eq!(store.trigger().unwrap(), 0);
    store.claim().unwrap();
    assert!(store.claim().is_err());
    assert!(store.owned());
}
#[test]
fn success_and_memory_are_committed_together_and_reopen() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("db");
    let mut store = Store::open(&path).unwrap();
    store.trigger().unwrap();
    store.claim().unwrap();
    store.terminal(true, false).unwrap();
    drop(store);
    let snapshot = Store::open(&path).unwrap().snapshot();
    assert_eq!(snapshot["status"], "completed");
    assert_eq!(snapshot["memory_records"], 1);
    assert_eq!(snapshot["events"][0]["kind"], "terminal");
}
#[test]
fn terminal_fault_rolls_back_status_memory_and_event() {
    let dir = tempfile::tempdir().unwrap();
    let mut store = Store::open(&dir.path().join("db")).unwrap();
    store.trigger().unwrap();
    store.claim().unwrap();
    assert!(store.terminal(true, true).is_err());
    let snapshot = store.snapshot();
    assert_eq!(snapshot["status"], "running");
    assert_eq!(snapshot["memory_records"], 0);
    assert_eq!(snapshot["events"].as_array().unwrap().len(), 0);
}
#[test]
fn stale_owner_cannot_finalize_or_publish_memory() {
    let dir = tempfile::tempdir().unwrap();
    let mut store = Store::open(&dir.path().join("db")).unwrap();
    store.trigger().unwrap();
    store.claim().unwrap();
    store
        .0
        .execute("UPDATE task SET owner='new',epoch=2", [])
        .unwrap();
    assert!(!store.owned());
    assert!(store.terminal(true, false).is_err());
    assert_eq!(store.snapshot()["memory_records"], 0);
}
#[test]
fn failed_task_does_not_promote_report_to_memory() {
    let dir = tempfile::tempdir().unwrap();
    let mut store = Store::open(&dir.path().join("db")).unwrap();
    store.trigger().unwrap();
    store.claim().unwrap();
    store.terminal(false, false).unwrap();
    assert_eq!(store.snapshot()["status"], "failed");
    assert_eq!(store.snapshot()["memory_records"], 0);
}
fn book() -> Book {
    Book {
        usage: Usage::default(),
        model_limit: 2,
        tool_limit: 1,
        events: vec![],
    }
}
#[test]
fn parent_and_reviewer_share_model_budget() {
    let mut b = book();
    b.model("lead").unwrap();
    b.model("reviewer").unwrap();
    assert_eq!(b.model("lead"), Err("model_budget"));
    assert_eq!(b.usage.models, 2);
    assert_eq!(
        b.events
            .iter()
            .map(|e| e.actor.as_str())
            .collect::<Vec<_>>(),
        ["lead", "reviewer"]
    );
}
#[test]
fn retry_attempts_share_tool_budget_without_recharging_logical_result() {
    let mut b = book();
    b.tool("lead", "same-call").unwrap();
    assert_eq!(b.tool("lead", "same-call"), Err("tool_budget"));
    assert_eq!(b.usage.tools, 1);
    assert_eq!(b.events.len(), 1);
}
fn pair() -> Vec<Message> {
    let call = ToolCall::from_value("c1", "read", &json!({}));
    vec![
        Message::new_ai_message_with_tool_calls("", &[call]),
        Message::new_tool_message(json!({"ok":true}), "c1"),
    ]
}
#[test]
fn compaction_must_remove_whole_tool_groups() {
    let history = pair();
    assert!(validate_history(&history).is_ok());
    assert_eq!(validate_history(&history[1..]), Err("orphan_tool"));
    assert_eq!(
        validate_history(&history[..1]),
        Err("incomplete_tool_group")
    );
    let compacted = vec![
        Message::new_human_message("archive receipt"),
        Message::new_ai_message("continue"),
    ];
    assert!(validate_history(&compacted).is_ok());
}
#[test]
fn duplicate_ids_are_rejected_even_after_previous_call_resolved() {
    let mut history = pair();
    history.extend(pair());
    assert_eq!(validate_history(&history), Err("duplicate_call"));
}
#[test]
fn ledger_sequence_correlates_actors_and_calls() {
    let mut b = book();
    b.event("lead", Some("c1"), "pre", "read");
    b.tool("lead", "c1").unwrap();
    b.event("lead", Some("c1"), "result", "ok");
    assert_eq!(
        b.events.iter().map(|e| e.seq).collect::<Vec<_>>(),
        [1, 2, 3]
    );
    assert!(b.events.iter().all(|e| e.call_id.as_deref() == Some("c1")));
}
