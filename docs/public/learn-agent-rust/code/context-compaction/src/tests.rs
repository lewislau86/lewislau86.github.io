use super::*;

fn pins() -> Vec<Item> {
    vec![
        item("s", Message::new_system_message("system")),
        item("u", Message::new_human_message("user")),
    ]
}
fn pair() -> Vec<Item> {
    let mut history = pins();
    history.extend([
        item(
            "call",
            Message::new_ai_message_with_tool_calls(
                "",
                &[
                    ToolCall::new("a", "read", "{}"),
                    ToolCall::new("b", "read", "{}"),
                ],
            ),
        ),
        result("rb", "b", json!({})),
        result("ra", "a", json!({})),
    ]);
    history
}
#[test]
fn parallel_calls_form_one_indivisible_group() {
    assert_eq!(groups(&pair()).unwrap(), vec![(2, 5)]);
}
#[test]
fn orphan_duplicate_and_reused_results_are_rejected() {
    let mut history = pair();
    history[3].message.id = Some("absent".into());
    assert_eq!(groups(&history).unwrap_err(), "invalid_history");
    let mut history = pair();
    history[4].message.id = Some("b".into());
    assert_eq!(groups(&history).unwrap_err(), "invalid_history");
    let mut history = pair();
    history.push(item(
        "reuse",
        Message::new_ai_message_with_tool_calls("", &[ToolCall::new("a", "read", "{}")]),
    ));
    assert_eq!(groups(&history).unwrap_err(), "invalid_history");
}
#[test]
fn unfinished_batch_is_deferred_before_any_edit() {
    let mut history = pair();
    history.pop();
    assert_eq!(groups(&history).unwrap_err(), "pending_tools");
}
#[test]
fn malformed_tool_calls_are_not_silently_ignored() {
    let mut history = pins();
    history.push(item(
        "bad",
        Message::new_ai_message("").with_tool_calls(json!({"not": "an array"})),
    ));
    assert_eq!(groups(&history).unwrap_err(), "invalid_history");
}
#[test]
fn unsupported_multimodal_content_fails_explicitly() {
    let mut history = pins();
    history[1].message =
        Message::new_human_message("x").with_images(vec!["https://example.org/x.png"]);
    assert_eq!(groups(&history).unwrap_err(), "unsupported_content");
}
#[test]
fn summary_sources_are_checked_independently_of_values() {
    let fact = Fact {
        key: "target".into(),
        value: "src/first.rs".into(),
        source: "m4".into(),
        sha256: "wrong".into(),
    };
    let summary = Summary {
        version: 1,
        facts: vec![fact.clone()],
    };
    assert_eq!(
        compact::validate_summary(
            &summary,
            &[fact],
            &BTreeMap::from([("m4".into(), "actual".into())])
        ),
        Err("summary_source")
    );
}
#[test]
fn artifact_reads_are_bounded_registered_and_unicode_safe() {
    let temp = tempfile::tempdir().unwrap();
    let mut store = Store::new(temp.path().into());
    assert_eq!(store.read("../outside").unwrap_err(), "unknown_artifact");
    let saved = store.put("tool_output", "甲乙丙丁".as_bytes()).unwrap();
    assert_eq!(store.chunk(&saved.id, 1, 2).unwrap()["chunk"], "乙丙");
    assert_eq!(store.chunk(&saved.id, 1, 129).unwrap_err(), "invalid_chunk");
    assert_eq!(store.chunk(&saved.id, 5, 1).unwrap_err(), "invalid_chunk");
    fs::write(temp.path().join(&saved.id), "戊己庚辛").unwrap();
    assert_eq!(store.read(&saved.id).unwrap_err(), "stale_artifact");
    fs::remove_file(temp.path().join(&saved.id)).unwrap();
    assert_eq!(store.read(&saved.id).unwrap_err(), "missing_artifact");
}
#[tokio::test]
async fn normal_flow_restores_skill_and_preserves_pairs_and_facts() {
    let report = experiment("normal").await.unwrap();
    assert_eq!(report.state.stop.as_deref(), Some("completed"));
    assert_eq!(
        (
            report.summary_calls,
            report.state.reloads,
            report.state.reads
        ),
        (1, 1, 1)
    );
    assert!(
        report.pairs_valid
            && report.pinned_unchanged
            && report.transcript_roundtrip
            && report.source_unchanged
    );
    let stage = &report.state.stages[0];
    assert!(
        stage.before > stage.externalized
            && stage.externalized > stage.micro
            && stage.micro > stage.after
    );
    assert!(
        report
            .state
            .model_inputs
            .iter()
            .all(|size| size + report.budget.reserve <= report.budget.hard)
    );
    assert!(
        report
            .state
            .items
            .last()
            .unwrap()
            .message
            .content
            .contains("src/first.rs")
    );
}
#[tokio::test]
async fn rejected_compaction_never_mutates_history_or_calls_agent() {
    for name in [
        "omit-fact",
        "invent-fact",
        "bad-json",
        "summary-error",
        "summary-large",
        "summary-input-budget",
        "archive-error",
        "hard-budget",
    ] {
        let report = experiment(name).await.unwrap();
        assert_eq!(report.state.model_calls, 0, "{name}");
        assert!(
            report.original_unchanged_on_failure
                && report.pinned_unchanged
                && report.source_unchanged,
            "{name}"
        );
        assert!(report.summary_calls <= 1, "{name}");
    }
}
#[tokio::test]
async fn naive_trimming_loses_target_despite_valid_protocol() {
    let report = experiment("naive-trim").await.unwrap();
    assert!(report.pairs_valid);
    assert_eq!(report.state.stop.as_deref(), Some("missing_evidence"));
    assert_eq!(report.state.reads, 0);
}
#[tokio::test]
async fn small_history_bypasses_archiving_and_summary() {
    let report = experiment("small").await.unwrap();
    assert!(report.artifacts.is_empty());
    assert_eq!(report.summary_calls, 0);
    assert_eq!(report.state.reloads, 0);
    assert_eq!(report.state.stop.as_deref(), Some("completed"));
}
#[tokio::test]
async fn micro_compaction_can_avoid_summary_call() {
    let report = experiment("micro-only").await.unwrap();
    assert_eq!(report.summary_calls, 0);
    assert_eq!(report.state.stages[0].decision, "micro_only");
    assert!(report.state.reads > 0);
}
#[tokio::test]
async fn registered_archived_output_can_be_retrieved_after_summary() {
    let report = experiment("retrieve").await.unwrap();
    assert_eq!(report.state.retrievals, 1);
    assert_eq!(report.state.stop.as_deref(), Some("completed"));
    assert!(report.artifact_integrity.values().all(|ok| *ok));
}
#[tokio::test]
async fn same_size_artifact_corruption_is_reported_as_tool_error() {
    let report = experiment("artifact-tamper").await.unwrap();
    assert_eq!(report.state.stop.as_deref(), Some("tool_error"));
    assert_eq!(report.state.reads, 0);
    assert_eq!(
        report
            .artifact_integrity
            .values()
            .filter(|ok| !**ok)
            .count(),
        1
    );
    assert!(report.pairs_valid && report.source_unchanged);
}

#[tokio::test]
async fn later_user_corrections_survive_prefix_replacement() {
    let temp = tempfile::tempdir().unwrap();
    let mut items = pins();
    items.extend([
        item("early", Message::new_ai_message("历史资料".repeat(100))),
        item(
            "correction",
            Message::new_human_message("新增约束：只输出建议，不要执行测试。"),
        ),
        item("more", Message::new_ai_message("较长过程资料".repeat(100))),
        item("recent", Message::new_ai_message("当前进度")),
        item("continue", Message::new_human_message("继续")),
    ]);
    let mut compactor = Compactor {
        budget: Budget::default(),
        required: vec![],
        sources: BTreeMap::new(),
        store: Store::new(temp.path().into()),
        summary_calls: 0,
    };
    let model = ScriptedModel {
        scenario: "normal".into(),
        summarize: true,
    };
    let prepared = compactor
        .prepare(&items, &model, true, false)
        .await
        .unwrap();
    let kept = prepared
        .items
        .iter()
        .find(|i| i.key == "correction")
        .unwrap();
    assert_eq!(kept.message.content, items[3].message.content);
    assert_eq!(kept.message.message_type, MessageType::HumanMessage);
    assert!(groups(&prepared.items).is_ok());
}

#[tokio::test]
async fn summary_calls_have_a_cumulative_limit() {
    let temp = tempfile::tempdir().unwrap();
    let mut items = pins();
    for n in 0..4 {
        items.push(Item::new(
            format!("m{n}"),
            Message::new_ai_message("已结束的历史".repeat(30)),
        ));
    }
    let original = serde_json::to_value(&items).unwrap();
    let mut compactor = Compactor {
        budget: Budget::default(),
        required: vec![],
        sources: BTreeMap::new(),
        store: Store::new(temp.path().into()),
        summary_calls: 0,
    };
    let model = ScriptedModel {
        scenario: "normal".into(),
        summarize: true,
    };
    compactor
        .prepare(&items, &model, true, false)
        .await
        .unwrap();
    compactor
        .prepare(&items, &model, true, false)
        .await
        .unwrap();
    assert!(matches!(
        compactor.prepare(&items, &model, true, false).await,
        Err("summary_call_budget")
    ));
    assert_eq!(compactor.summary_calls, 2);
    assert_eq!(serde_json::to_value(&items).unwrap(), original);
}

#[test]
fn summary_schema_rejects_duplicate_fields_and_policy_fields() {
    assert!(serde_json::from_str::<Summary>(r#"{"version":1,"version":1,"facts":[]}"#).is_err());
    assert!(
        serde_json::from_str::<Summary>(r#"{"version":1,"facts":[],"allow_write":true}"#).is_err()
    );
}
