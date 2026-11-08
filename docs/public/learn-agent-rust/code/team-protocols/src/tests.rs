use crate::*;
use protocol::{Kind, Status};

fn registry() -> Registry {
    let mut r = Registry::default();
    r.dispatch(
        Member::Core,
        Member::Lead,
        &Message::PlanRequest {
            request_id: "p".into(),
            plan: plan(),
            ttl: 10,
        },
    )
    .unwrap();
    r
}

#[tokio::test]
async fn normal_creates_exact_file_and_joins_both_handshakes() {
    let r = scenario("normal").await;
    let a = r.artifact.unwrap();
    assert_eq!(a.content, plan().content);
    assert_eq!(a.sha256, hash(a.content.as_bytes()));
    assert_eq!(
        r.before_cleanup.requests["plan-1"].status,
        Status::Completed
    );
    assert_eq!(
        r.before_cleanup.requests["stop-core"].status,
        Status::Approved
    );
    assert!(
        r.joined
            .iter()
            .all(|j| j.outcome == "graceful" && !j.aborted)
    );
    assert!(r.workspace_removed && r.escape_absent);
}

#[test]
fn wrong_sender_recipient_kind_and_unknown_id_cannot_resolve() {
    let r = registry();
    let shutdown = Message::ShutdownResponse {
        request_id: "p".into(),
        decision: Decision::Approve,
        feedback: "x".into(),
    };
    for (from, to, message, expected) in [
        (
            Member::Config,
            Member::Core,
            response("p", Decision::Approve),
            "wrong_identity",
        ),
        (
            Member::Lead,
            Member::Config,
            response("p", Decision::Approve),
            "wrong_identity",
        ),
        (Member::Lead, Member::Core, shutdown, "wrong_kind"),
        (
            Member::Lead,
            Member::Core,
            response("unknown", Decision::Approve),
            "unknown_request",
        ),
    ] {
        let mut candidate = r.clone();
        assert_eq!(candidate.dispatch(from, to, &message), Err(expected));
        assert_eq!(
            serde_json::to_value(candidate).unwrap(),
            serde_json::to_value(&r).unwrap()
        );
    }
}

#[test]
fn duplicate_id_cannot_replace_plan_and_resolved_reply_cannot_flip_decision() {
    let mut r = registry();
    assert_eq!(
        r.dispatch(
            Member::Core,
            Member::Lead,
            &Message::PlanRequest {
                request_id: "p".into(),
                plan: Plan {
                    revision: 2,
                    ..plan()
                },
                ttl: 10
            }
        ),
        Err("duplicate_request")
    );
    assert_eq!(r.requests["p"].plan, Some(plan()));
    r.dispatch(Member::Lead, Member::Core, &response("p", Decision::Reject))
        .unwrap();
    assert_eq!(
        r.dispatch(
            Member::Lead,
            Member::Core,
            &response("p", Decision::Approve)
        ),
        Err("request_not_pending")
    );
    assert_eq!(r.requests["p"].status, Status::Rejected);
}

#[test]
fn deadline_boundary_expires_pending_and_approved_and_never_rewinds_clock() {
    for approved in [false, true] {
        let mut r = registry();
        if approved {
            r.dispatch(
                Member::Lead,
                Member::Core,
                &response("p", Decision::Approve),
            )
            .unwrap();
        }
        r.advance(9).unwrap();
        assert_ne!(r.requests["p"].status, Status::Expired);
        r.advance(10).unwrap();
        assert_eq!(r.requests["p"].status, Status::Expired);
        assert_eq!(r.advance(9), Err("clock_regression"));
        assert_eq!(
            r.dispatch(
                Member::Lead,
                Member::Core,
                &response("p", Decision::Approve)
            ),
            Err("request_not_pending")
        );
    }
}

#[test]
fn cancellation_requires_requester_and_late_approval_does_not_revive() {
    let mut r = registry();
    assert_eq!(r.cancel(Member::Config, "p"), Err("wrong_identity"));
    r.cancel(Member::Core, "p").unwrap();
    assert_eq!(
        r.dispatch(
            Member::Lead,
            Member::Core,
            &response("p", Decision::Approve)
        ),
        Err("request_not_pending")
    );
}

#[test]
fn approval_is_exact_single_use_and_changes_real_file_content() {
    for content in ["first independent payload", "second changed payload"] {
        let dir = tempfile::tempdir().unwrap();
        let p = Plan {
            content: content.into(),
            ..plan()
        };
        let mut r = Registry::default();
        r.dispatch(
            Member::Core,
            Member::Lead,
            &Message::PlanRequest {
                request_id: "p".into(),
                plan: p.clone(),
                ttl: 10,
            },
        )
        .unwrap();
        assert_eq!(
            r.execute(Member::Core, "p", &p, dir.path()),
            Err("not_approved")
        );
        assert!(!dir.path().join("review.txt").exists());
        r.dispatch(
            Member::Lead,
            Member::Core,
            &response("p", Decision::Approve),
        )
        .unwrap();
        for changed in [
            Plan {
                revision: 2,
                ..p.clone()
            },
            Plan {
                content: "different".into(),
                ..p.clone()
            },
            Plan {
                path: "other.txt".into(),
                ..p.clone()
            },
        ] {
            assert_eq!(
                r.execute(Member::Core, "p", &changed, dir.path()),
                Err("plan_changed")
            );
        }
        assert_eq!(
            r.execute(Member::Config, "p", &p, dir.path()),
            Err("wrong_identity")
        );
        r.execute(Member::Core, "p", &p, dir.path()).unwrap();
        assert_eq!(
            std::fs::read_to_string(dir.path().join("review.txt")).unwrap(),
            content
        );
        assert_eq!(
            r.execute(Member::Core, "p", &p, dir.path()),
            Err("not_approved")
        );
        assert_eq!(r.writes, 1);
    }
}

#[test]
fn approved_path_still_requires_acl_and_existing_file_is_preserved() {
    let dir = tempfile::tempdir().unwrap();
    let mut r = registry();
    r.dispatch(
        Member::Lead,
        Member::Core,
        &response("p", Decision::Approve),
    )
    .unwrap();
    std::fs::write(dir.path().join("review.txt"), "existing output").unwrap();
    assert_eq!(
        r.execute(Member::Core, "p", &plan(), dir.path()),
        Err("write_failed")
    );
    assert_eq!(r.requests["p"].status, Status::Failed);
    assert_eq!(
        std::fs::read_to_string(dir.path().join("review.txt")).unwrap(),
        "existing output"
    );
    let mut p = plan();
    p.path = "../escape.txt".into();
    let mut r = Registry::default();
    r.dispatch(
        Member::Core,
        Member::Lead,
        &Message::PlanRequest {
            request_id: "p".into(),
            plan: p.clone(),
            ttl: 10,
        },
    )
    .unwrap();
    r.dispatch(
        Member::Lead,
        Member::Core,
        &response("p", Decision::Approve),
    )
    .unwrap();
    assert_eq!(
        r.execute(Member::Core, "p", &p, dir.path()),
        Err("permission_denied")
    );
}

#[test]
fn schema_rejects_claimed_identity_invalid_variant_and_boolean_decision() {
    for raw in [
        r#"{"type":"plan_response","request_id":"p","decision":"approve","feedback":"x","from":"lead"}"#,
        r#"{"type":"plan_response","request_id":"p","decision":true,"feedback":"x"}"#,
        r#"{"type":"custom","request_id":"p"}"#,
    ] {
        assert!(protocol::decode(raw).is_err());
    }
    assert_eq!(
        protocol::decode(&"x".repeat(4097)).unwrap_err(),
        "message_size"
    );
}

#[test]
fn invalid_request_bounds_are_rejected_before_registration() {
    for (id, ttl, now, expected) in [
        ("", 10, 0, "invalid_id"),
        ("p/1", 10, 0, "invalid_id"),
        ("p", 0, 0, "invalid_ttl"),
        ("p", 101, 0, "invalid_ttl"),
        ("p", 10, u64::MAX, "deadline_overflow"),
    ] {
        let mut r = Registry::default();
        r.advance(now).unwrap();
        assert_eq!(
            r.dispatch(
                Member::Core,
                Member::Lead,
                &Message::PlanRequest {
                    request_id: id.into(),
                    plan: plan(),
                    ttl
                }
            ),
            Err(expected)
        );
        assert!(r.requests.is_empty());
    }
    let mut r = Registry::default();
    assert_eq!(
        r.dispatch(
            Member::Lead,
            Member::Core,
            &Message::PlanRequest {
                request_id: "p".into(),
                plan: plan(),
                ttl: 10
            }
        ),
        Err("wrong_direction")
    );
    let p = Plan {
        content: "x".repeat(513),
        ..plan()
    };
    assert_eq!(
        r.dispatch(
            Member::Core,
            Member::Lead,
            &Message::PlanRequest {
                request_id: "p".into(),
                plan: p,
                ttl: 10
            }
        ),
        Err("invalid_plan")
    );
}

#[tokio::test]
async fn full_mailbox_does_not_commit_shutdown_and_same_id_can_retry() {
    let r = scenario("mailbox-full").await;
    assert!(r.observations["failed_send_rolled_back"]);
    assert_eq!(r.errors, ["mailbox_full"]);
    assert_eq!(
        r.after_cleanup.requests["stop-core"].status,
        Status::Approved
    );
    assert_eq!(r.after_cleanup.writes, 1);
}

#[tokio::test]
async fn shutdown_rejection_revokes_old_grant_and_requires_fresh_plan() {
    let r = scenario("shutdown-rejected").await;
    assert!(r.observations["rejection_keeps_actor_alive"]);
    assert_eq!(
        r.before_cleanup.requests["plan-1"].status,
        Status::Cancelled
    );
    assert_eq!(
        r.before_cleanup.requests["plan-2"].status,
        Status::Completed
    );
    assert_eq!(
        r.before_cleanup.requests["stop-core"].status,
        Status::Rejected
    );
}

#[tokio::test]
async fn approval_is_independent_from_join_and_abort_fallback_is_awaited() {
    for name in ["ack-without-exit", "abort-fallback"] {
        let r = scenario(name).await;
        assert!(r.observations["approved_but_actor_alive"]);
        assert_eq!(
            r.before_cleanup.requests["stop-core"].status,
            Status::Approved
        );
        assert_eq!(
            r.joined[0].outcome,
            if name == "abort-fallback" {
                "aborted"
            } else {
                "cancelled"
            }
        );
        assert_eq!(r.joined[0].aborted, name == "abort-fallback");
    }
}

#[tokio::test]
async fn timeout_and_panic_have_separate_request_and_resource_evidence() {
    let timeout = scenario("shutdown-timeout").await;
    assert!(timeout.observations["real_receive_timeout"]);
    assert_eq!(
        timeout.after_cleanup.requests["stop-core"].status,
        Status::Expired
    );
    let panic = scenario("shutdown-panic").await;
    assert_eq!(panic.joined[0].outcome, "panic");
    assert_eq!(
        panic.before_cleanup.requests["stop-core"].status,
        Status::Pending
    );
    assert_eq!(
        panic.after_cleanup.requests["stop-core"].status,
        Status::Failed
    );
}

#[tokio::test]
async fn closed_receiver_rolls_back_new_request() {
    let dir = tempfile::tempdir().unwrap();
    let mut rt = Runtime::new(dir.path().into(), Mode::Normal, false);
    rt.cancel(Member::Core);
    tokio::task::yield_now().await;
    assert_eq!(shutdown(&rt, Member::Core, "stop"), Err("mailbox_closed"));
    assert!(rt.snapshot().requests.is_empty());
    rt.finish().await;
}

#[tokio::test]
async fn every_scenario_has_bounded_requests_and_no_detached_actor_or_escaped_file() {
    for name in SCENARIOS {
        let r = scenario(name).await;
        assert_eq!(r.active, 0, "{name}");
        assert_eq!(r.joined.len(), 2, "{name}");
        assert!(r.workspace_removed && r.escape_absent, "{name}");
        assert!(r.observations.values().all(|value| *value), "{name}");
        assert!(r.after_cleanup.requests.len() <= 16);
        assert!(
            r.after_cleanup
                .requests
                .values()
                .all(|q| !matches!(q.status, Status::Pending | Status::Approved)
                    || q.kind == Kind::Shutdown)
        );
    }
}
