use crate::{
    agent::{State, grade},
    provider::{HttpModel, parse_response, wire_messages},
};
use langchain_rust::schemas::{Message, ToolCall};
use serde_json::{Value, json};
fn response() -> Value {
    json!({"id":"r1","object":"chat.completion","model":"fixture-v1","choices":[{"index":0,"message":{"role":"assistant","content":"answer"},"finish_reason":"stop"}],"usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5}})
}
#[test]
fn accepts_complete_answer_and_usage() {
    let p = parse_response(&response(), "fixture-v1").unwrap();
    assert_eq!(p.generated.generation, "answer");
    assert_eq!(p.usage.unwrap()["total_tokens"], 5);
}
#[test]
fn missing_usage_is_unknown_not_zero() {
    let mut v = response();
    v.as_object_mut().unwrap().remove("usage");
    assert!(parse_response(&v, "fixture-v1").unwrap().usage.is_none());
}
#[test]
fn incomplete_and_filtered_generations_stop() {
    for (reason, error) in [
        ("length", "generation_incomplete"),
        ("content_filter", "filtered"),
    ] {
        let mut v = response();
        v["choices"][0]["finish_reason"] = json!(reason);
        assert_eq!(parse_response(&v, "fixture-v1").err(), Some(error));
    }
}
#[test]
fn usage_must_be_unsigned_and_consistent() {
    for value in [json!(-1), json!(1.5), json!("3"), json!(4)] {
        let mut v = response();
        v["usage"]["completion_tokens"] = value;
        assert_eq!(
            parse_response(&v, "fixture-v1").err(),
            Some("invalid_usage")
        );
    }
}
#[test]
fn rejects_ambiguous_choice_and_identity_drift() {
    let mut v = response();
    v["choices"] = json!([]);
    assert_eq!(
        parse_response(&v, "fixture-v1").err(),
        Some("invalid_choices")
    );
    assert_eq!(
        parse_response(&response(), "other").err(),
        Some("model_mismatch")
    );
}
#[test]
fn call_arguments_and_identity_survive_wire_roundtrip() {
    let call = ToolCall::from_value("c1", "read_file", &json!({"path":"README.md"}));
    let messages = [
        Message::new_ai_message_with_tool_calls("", &[call]),
        Message::new_tool_message(json!({"ok":true}), "c1"),
    ];
    let wire = wire_messages(&messages).unwrap();
    assert_eq!(wire[0]["tool_calls"][0]["id"], wire[1]["tool_call_id"]);
    assert_eq!(
        wire[0]["tool_calls"][0]["function"]["arguments"],
        "{\"path\":\"README.md\"}"
    );
}
#[test]
fn rejects_orphan_missing_and_duplicate_tool_results() {
    let c = ToolCall::from_value("c1", "read_file", &json!({}));
    let a = Message::new_ai_message_with_tool_calls("", &[c]);
    let t = Message::new_tool_message(json!({}), "c1");
    assert_eq!(
        wire_messages(std::slice::from_ref(&t)).err(),
        Some("orphan_tool")
    );
    assert_eq!(
        wire_messages(std::slice::from_ref(&a)).err(),
        Some("missing_tool_result")
    );
    assert_eq!(
        wire_messages(&[a.clone(), t.clone(), a, t]).err(),
        Some("duplicate_call")
    );
}
#[test]
fn correct_answer_without_observed_read_does_not_pass() {
    let mut s = State {
        stop: Some("answered".into()),
        answer: Some("{\"command\":\"npm start\",\"source\":\"README.md\"}".into()),
        ..Default::default()
    };
    let g = grade(&s, &json!("npm start"));
    assert_eq!(g["answer_correct"], true);
    assert_eq!(g["task_pass"], false);
    s.reads = 1;
    s.read_result = Some(json!({"ok":true,"text":"Startup: npm start\n"}));
    assert_eq!(grade(&s, &json!("npm start"))["task_pass"], true);
}
#[test]
fn grader_requires_exact_fields_and_label() {
    let mut s = State {
        stop: Some("answered".into()),
        reads: 1,
        read_result: Some(json!({})),
        ..Default::default()
    };
    for answer in [
        "npm start",
        "{\"command\":null}",
        "{\"command\":\"wrong\",\"source\":\"README.md\"}",
        "{\"command\":null,\"source\":\"README.md\",\"extra\":1}",
    ] {
        s.answer = Some(answer.into());
        assert_eq!(grade(&s, &json!(null))["task_pass"], false);
    }
}
#[test]
fn endpoint_scope_excludes_external_http_and_url_credentials() {
    for url in [
        "http://example.com/fixture/x",
        "http://key@127.0.0.1:1234/fixture/x",
        "https://other.test/chat/completions",
        "http://127.0.0.1:1234/fixture/x?key=abc",
    ] {
        assert!(HttpModel::new(url.into(), "secret".into(), "fixture-v1".into(), false).is_err());
    }
}
