use crate::*;

fn request() -> Request {
    Request {
        tenant: "course".into(),
        operation_id: "review-42".into(),
        title: "Check timeout".into(),
    }
}

#[test]
fn exact_same_intent_returns_original_receipt() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("service.db");
    let a = provider::apply(&path, request(), "key", 1, "none").unwrap();
    let b = provider::apply(&path, request(), "key", 2, "none").unwrap();
    assert_eq!(a["receipt"], b["receipt"]);
    assert_eq!(b["replayed"], true);
    let state = provider::inspect(&path).unwrap();
    assert_eq!(state["ticket_count"], 1);
    assert_eq!(state["committed_apply_calls"], 2);
}

#[test]
fn same_id_changed_payload_is_rejected_without_new_ticket() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("service.db");
    provider::apply(&path, request(), "key", 1, "none").unwrap();
    let mut changed = request();
    changed.title = "Different task".into();
    assert_eq!(
        provider::apply(&path, changed, "key", 2, "none")
            .unwrap_err()
            .to_string(),
        "idempotency_conflict"
    );
    assert_eq!(provider::inspect(&path).unwrap()["ticket_count"], 1);
}

#[test]
fn same_parameters_with_distinct_business_ids_are_distinct_intents() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("service.db");
    provider::apply(&path, request(), "key", 1, "none").unwrap();
    let mut changed = request();
    changed.operation_id = "review-43".into();
    provider::apply(&path, changed, "key", 2, "none").unwrap();
    assert_eq!(provider::inspect(&path).unwrap()["ticket_count"], 2);
}

#[test]
fn tenant_is_part_of_the_key_scope() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("service.db");
    provider::apply(&path, request(), "key", 1, "none").unwrap();
    let mut other = request();
    other.tenant = "another".into();
    provider::apply(&path, other, "key", 1, "none").unwrap();
    let state = provider::query(&path, "course", "review-42", "none").unwrap();
    assert_eq!(state["matches"].as_array().unwrap().len(), 1);
    assert_eq!(provider::inspect(&path).unwrap()["ticket_count"], 2);
}

#[test]
fn expiry_loses_deduplication_without_deleting_business_result() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("service.db");
    provider::apply(&path, request(), "key", 1, "none").unwrap();
    assert_eq!(provider::expire(&path, 100).unwrap()["keys_removed"], 0);
    assert_eq!(provider::expire(&path, 101).unwrap()["keys_removed"], 1);
    provider::apply(&path, request(), "key", 101, "none").unwrap();
    assert_eq!(provider::inspect(&path).unwrap()["ticket_count"], 2);
}

#[test]
fn non_idempotent_service_really_creates_two_rows() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("service.db");
    for _ in 0..2 {
        provider::apply(&path, request(), "none", 1, "none").unwrap();
    }
    assert_eq!(provider::inspect(&path).unwrap()["ticket_count"], 2);
}

#[test]
fn changed_content_is_visible_in_actual_business_row() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("service.db");
    let mut changed = request();
    changed.title = "Inspect values.first()".into();
    provider::apply(&path, changed.clone(), "key", 1, "none").unwrap();
    let rows = provider::query(&path, "course", "review-42", "none").unwrap();
    assert_eq!(rows["matches"][0]["request"]["title"], changed.title);
    assert_eq!(rows["matches"][0]["digest"], changed.digest());
}

#[test]
fn receipts_bind_identity_parameters_and_result() {
    let r = request();
    let good = Receipt {
        ticket_id: 1,
        request: r.clone(),
        digest: r.digest(),
    };
    good.verify(&r).unwrap();
    let mut bad = good.clone();
    bad.request.tenant = "other".into();
    assert!(bad.verify(&r).is_err());
    let mut bad = good.clone();
    bad.request.title = "changed".into();
    assert!(bad.verify(&r).is_err());
    let mut bad = good.clone();
    bad.digest = "wrong".into();
    assert!(bad.verify(&r).is_err());
    let mut bad = good;
    bad.ticket_id = 0;
    assert!(bad.verify(&r).is_err());
}

#[test]
fn duplicate_prepare_preserves_frozen_mode_deadline_and_payload() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("client.db");
    client::prepare(&path, request(), "key", 0, "none").unwrap();
    let duplicate = client::prepare(&path, request(), "key", 99, "none").unwrap();
    assert_eq!(duplicate["prepared"], false);
    assert!(client::prepare(&path, request(), "none", 99, "none").is_err());
    let db = database(&path).unwrap();
    let deadline: i64 = db
        .query_row("SELECT safe_until FROM outbox", [], |r| r.get(0))
        .unwrap();
    assert_eq!(deadline, 100);
    assert_eq!(client::inspect(&path).unwrap()["actions"], 1);
}

#[test]
fn malformed_request_cannot_create_an_intent() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("client.db");
    for changed in [
        Request {
            title: " ".into(),
            ..request()
        },
        Request {
            operation_id: "../escape".into(),
            ..request()
        },
        Request {
            title: "x".repeat(257),
            ..request()
        },
    ] {
        assert!(client::prepare(&path, changed, "key", 0, "none").is_err());
    }
    assert!(!path.exists());
    assert!(
        serde_json::from_str::<Request>(
            r#"{"tenant":"a","operation_id":"x","title":"ok","approved":true}"#
        )
        .is_err()
    );
}

#[test]
fn corrupted_local_payload_is_rejected_before_any_provider_call() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("client.db");
    let remote = dir.path().join("provider.db");
    client::prepare(&path, request(), "key", 0, "none").unwrap();
    database(&path)
        .unwrap()
        .execute("UPDATE outbox SET digest='corrupt'", [])
        .unwrap();
    let error =
        client::deliver(&path, &remote, "course", "review-42", 1, "none", false).unwrap_err();
    assert_eq!(error.to_string(), "corrupt_intent");
    assert!(!remote.exists());
}
