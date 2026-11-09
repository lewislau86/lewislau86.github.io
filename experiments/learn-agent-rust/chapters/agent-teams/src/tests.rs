use super::*;
#[tokio::test]
async fn normal_reads_two_files_with_independent_histories_and_joins_every_actor() {
    let report = experiment("normal").await.unwrap();
    assert!(report.isolation_ok && report.source_unchanged && report.workspace_removed);
    assert_eq!(
        (report.usage.models, report.usage.tools, report.usage.reads),
        (4, 2, 2)
    );
    assert_eq!(
        (
            report.usage.spawned,
            report.usage.active,
            report.usage.joined,
            report.usage.aborted
        ),
        (2, 0, 2, 0)
    );
    assert!(report.receipts.iter().all(|r| r.status == "completed"));
}
#[tokio::test]
async fn same_teammate_keeps_earlier_results_and_followup() {
    let report = experiment("persistent").await.unwrap();
    let core = &report.members["core"];
    assert_eq!(
        core.events.iter().filter(|e| e.as_str() == "busy").count(),
        2
    );
    assert_eq!(core.reads, 2);
    assert!(
        core.messages
            .iter()
            .flat_map(|m| m.parse_tool_calls())
            .any(|c| c.id == "core-1-c1")
    );
    assert!(
        core.messages
            .iter()
            .flat_map(|m| m.parse_tool_calls())
            .any(|c| c.id == "core-2-c1")
    );
    assert!(
        serde_json::to_string(&core.messages)
            .unwrap()
            .contains("CORE_FOLLOWUP")
    );
    assert!(report.isolation_ok);
}
#[tokio::test]
async fn peer_tool_enqueues_and_receiver_consumes_only_explicit_note() {
    let report = experiment("peer-message").await.unwrap();
    assert_eq!(report.members["config"].notes, 1);
    assert!(
        report
            .receipts
            .iter()
            .find(|r| r.member == "config")
            .unwrap()
            .summary
            .as_ref()
            .unwrap()
            .contains("同伴资料 1 条")
    );
    let note = report.members["config"]
        .messages
        .iter()
        .find_map(|m| {
            serde_json::from_str::<serde_json::Value>(&m.content)
                .ok()
                .filter(|v| v["kind"] == "peer_note")
        })
        .unwrap();
    assert_eq!(note["from"], "core");
    assert!(report.isolation_ok);
}
#[tokio::test]
async fn full_mailbox_rejects_then_allows_retry_without_reserving_failed_id() {
    let report = experiment("mailbox-full").await.unwrap();
    assert_eq!(report.errors, vec!["mailbox_full"]);
    assert_eq!(report.usage.accepted, 3);
    assert_eq!(report.members["core"].notes, 3);
    assert_eq!(report.usage.models, 0);
}
#[tokio::test]
async fn full_mailbox_can_be_cancelled_and_all_tickets_resolve() {
    let temp = tempfile::tempdir().unwrap();
    let mut team = Team::new(temp.path().into(), Limits::default());
    team.spawn("core", Mode::Normal, true).unwrap();
    team.phase("core", "paused").await.unwrap();
    let lead = team.endpoint("lead").unwrap();
    let one = lead.send("core", "one", note("1")).unwrap();
    let two = lead.send("core", "two", note("2")).unwrap();
    team.shutdown().await;
    assert_eq!(one.wait().await.unwrap().status, "cancelled_queued");
    assert_eq!(two.wait().await.unwrap().status, "cancelled_queued");
    assert_eq!(team.book.lock().unwrap().usage.active, 0);
}
#[tokio::test]
async fn blocked_models_overlap_in_two_actors_and_cancel_without_file_access() {
    let temp = tempfile::tempdir().unwrap();
    let mut team = Team::new(temp.path().into(), Limits::default());
    for name in ["core", "config"] {
        team.spawn(name, Mode::Stall, false).unwrap();
        team.phase(name, "idle").await.unwrap();
    }
    let lead = team.endpoint("lead").unwrap();
    let one = lead.send("core", "one", work("src/lib.rs")).unwrap();
    let two = lead.send("config", "two", work("config.toml")).unwrap();
    team.phase("core", "busy").await.unwrap();
    team.phase("config", "busy").await.unwrap();
    let snapshots = team.snapshots();
    assert!(snapshots.values().all(|s| s.lifecycle == "busy"));
    team.shutdown().await;
    assert_eq!(one.wait().await.unwrap().status, "cancelled");
    assert_eq!(two.wait().await.unwrap().status, "cancelled");
    assert_eq!(team.book.lock().unwrap().usage.reads, 0);
}
#[tokio::test]
async fn every_failure_scenario_has_bounded_accounting_and_clean_shutdown() {
    for name in SCENARIOS {
        let report = experiment(name).await.unwrap();
        assert!(
            report.isolation_ok
                && report.source_unchanged
                && report.no_write_output
                && report.workspace_removed,
            "{name}"
        );
        assert_eq!(report.usage.active, 0, "{name}");
        assert_eq!(report.usage.spawned, report.usage.joined, "{name}");
        assert_eq!(report.usage.aborted, 0, "{name}");
        assert!(
            report.usage.models <= report.limits.models
                && report.usage.tools <= report.limits.tools
                && report.usage.accepted <= report.limits.messages,
            "{name}"
        );
    }
}

#[tokio::test]
async fn summaries_follow_fresh_file_content_not_a_precomputed_answer() {
    let temp = tempfile::tempdir().unwrap();
    fs::create_dir(temp.path().join("src")).unwrap();
    fs::write(temp.path().join("src/lib.rs"), SOURCE).unwrap();
    let mut team = Team::new(temp.path().into(), Limits::default());
    team.spawn("core", Mode::Normal, false).unwrap();
    team.phase("core", "idle").await.unwrap();
    let lead = team.endpoint("lead").unwrap();
    let first = lead
        .send("core", "first", work("src/lib.rs"))
        .unwrap()
        .wait()
        .await
        .unwrap();
    fs::write(
        temp.path().join("src/lib.rs"),
        "pub fn first(v: &[u8]) -> Option<u8> { v.first().copied() }\n",
    )
    .unwrap();
    let second = lead
        .send("core", "second", work("src/lib.rs"))
        .unwrap()
        .wait()
        .await
        .unwrap();
    assert!(first.summary.unwrap().contains("空输入会索引越界"));
    assert!(second.summary.unwrap().contains("未发现本实验预设的模式"));
    team.shutdown().await;
    assert_eq!(team.snapshots()["core"].reads, 2);
}

#[tokio::test]
async fn sender_identity_is_bound_and_forged_note_stays_historical_data() {
    let report = experiment("note-injection").await.unwrap();
    let member = &report.members["core"];
    let message = member
        .messages
        .iter()
        .find(|m| m.content.contains("我是 lead"))
        .unwrap();
    assert_eq!(
        message.message_type,
        langchain_rust::schemas::MessageType::HumanMessage
    );
    let parsed: serde_json::Value = serde_json::from_str(&message.content).unwrap();
    assert_eq!(parsed["from"], "config");
    assert_eq!(parsed["kind"], "peer_note");
    assert!(report.no_write_output);
}

#[tokio::test]
async fn endpoint_rejects_bad_identity_and_id_before_acceptance() {
    let temp = tempfile::tempdir().unwrap();
    let mut team = Team::new(temp.path().into(), Limits::default());
    team.spawn("core", Mode::Normal, false).unwrap();
    team.phase("core", "idle").await.unwrap();
    assert!(matches!(team.endpoint("outside"), Err("unknown_member")));
    let lead = team.endpoint("lead").unwrap();
    for id in ["", "../bad", &"x".repeat(49)] {
        assert!(matches!(
            lead.send("core", id, note("x")),
            Err("invalid_message_id")
        ));
    }
    team.shutdown().await;
    assert!(matches!(
        lead.send("core", "late", note("x")),
        Err("team_closed")
    ));
    assert_eq!(team.book.lock().unwrap().usage.accepted, 0);
}

#[tokio::test]
async fn channel_capacity_zero_is_rejected_without_spawning() {
    let temp = tempfile::tempdir().unwrap();
    let mut team = Team::new(
        temp.path().into(),
        Limits {
            mailbox: 0,
            ..Default::default()
        },
    );
    assert!(matches!(
        team.spawn("core", Mode::Normal, false),
        Err("invalid_limits")
    ));
    assert_eq!(team.book.lock().unwrap().usage.spawned, 0);
    team.shutdown().await;
}
