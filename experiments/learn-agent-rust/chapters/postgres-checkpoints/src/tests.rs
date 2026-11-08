use crate::state::{Granularity, Message, Phase, State, identifier};

fn pending() -> State {
    let mut s = State::new("read_only".into(), Granularity::Tool).unwrap();
    s.model_turns = 1;
    s.phase = Phase::Tools;
    s.messages.push(Message::AssistantCalls {
        ids: vec!["read-1".into(), "read-2".into()],
    });
    s
}
#[test]
fn initial_state_roundtrip() {
    let s = State::new("read_only".into(), Granularity::Tool).unwrap();
    s.validate().unwrap();
    let value = serde_json::to_string(&s).unwrap();
    assert_eq!(serde_json::from_str::<State>(&value).unwrap(), s);
}
#[test]
fn versions_are_independent() {
    let mut s = pending();
    s.format_version = 2;
    assert_eq!(s.validate().unwrap_err().0, "format_version");
    s.format_version = 1;
    s.workflow_version = "p01-v2".into();
    assert_eq!(s.validate().unwrap_err().0, "workflow_version");
}
#[test]
fn budget_is_cumulative_and_fixed() {
    let mut s = pending();
    s.tool_dispatches = 3;
    assert_eq!(s.validate().unwrap_err().0, "invalid_budget");
    s.tool_dispatches = 0;
    s.max_tool_dispatches = 200;
    assert_eq!(s.validate().unwrap_err().0, "invalid_budget");
}
#[test]
fn rejects_wrong_call_pairing() {
    let mut s = pending();
    s.cursor = 1;
    s.tool_dispatches = 1;
    s.messages.push(Message::Tool {
        call_id: "read-2".into(),
        content: "cargo run".into(),
    });
    assert_eq!(s.validate().unwrap_err().0, "message_pairing");
}
#[test]
fn partial_history_has_one_result() {
    let mut s = pending();
    s.cursor = 1;
    s.tool_dispatches = 1;
    s.messages.push(Message::Tool {
        call_id: "read-1".into(),
        content: "cargo run".into(),
    });
    s.validate().unwrap();
    s.messages.push(Message::Tool {
        call_id: "read-1".into(),
        content: "duplicate".into(),
    });
    assert_eq!(s.validate().unwrap_err().0, "message_pairing");
}
#[test]
fn inflight_reserves_budget() {
    let mut s = pending();
    s.phase = Phase::ToolInFlight;
    assert_eq!(s.validate().unwrap_err().0, "invalid_state");
    s.tool_dispatches = 1;
    s.validate().unwrap();
    s.granularity = Granularity::Batch;
    assert_eq!(s.validate().unwrap_err().0, "invalid_state");
    s.tool_dispatches = 2;
    s.validate().unwrap();
}
#[test]
fn reconcile_keeps_uncertain_identity() {
    let mut s = pending();
    s.phase = Phase::Reconcile;
    s.tool_dispatches = 1;
    s.uncertain = Some("tool".into());
    s.validate().unwrap();
    s.uncertain = Some("model".into());
    assert_eq!(s.validate().unwrap_err().0, "invalid_state");
}
#[test]
fn rejects_unsupported_profiles_and_extra_fields() {
    assert!(State::new("effect".into(), Granularity::Batch).is_err());
    let s = pending();
    let mut value = serde_json::to_value(s).unwrap();
    value["unknown"] = serde_json::json!(true);
    assert!(serde_json::from_value::<State>(value).is_err());
}
#[test]
fn bounded_results_and_ids() {
    let mut s = pending();
    s.cursor = 1;
    s.tool_dispatches = 1;
    s.messages.push(Message::Tool {
        call_id: "read-1".into(),
        content: "中".repeat(1400),
    });
    assert_eq!(s.validate().unwrap_err().0, "message_pairing");
    assert!(identifier("session_1"));
    assert!(!identifier("../session"));
    assert!(!identifier(&"a".repeat(41)));
}
#[test]
fn model_inflight_and_done_invariants() {
    let mut s = State::new("read_only".into(), Granularity::Tool).unwrap();
    s.phase = Phase::ModelInFlight;
    s.model_turns = 1;
    s.validate().unwrap();
    s.phase = Phase::Done;
    assert!(s.validate().is_err());
}
