use crate::queue::{Command, Fault, Queue};
use serde_json::{Value, json};

fn apply(q: &mut Queue, value: Value) -> Value {
    q.apply(
        serde_json::from_value::<Command>(value).unwrap(),
        Fault::None,
    )
    .unwrap()
}
fn seed() -> Queue {
    let mut q = Queue::memory();
    apply(
        &mut q,
        json!({"op":"add","id":"report","title":"日报","max_claims":3}),
    );
    q
}
fn claim(q: &mut Queue, owner: &str, now: i64) -> Value {
    apply(q, json!({"op":"claim","owner":owner,"now":now,"ttl":10}))
}
fn rejected(q: &mut Queue, value: Value, code: &str) {
    let before = apply(q, json!({"op":"show"}));
    let error = q
        .apply(serde_json::from_value(value).unwrap(), Fault::None)
        .unwrap_err();
    assert_eq!(error.0, code);
    assert_eq!(apply(q, json!({"op":"show"})), before);
}

#[test]
fn normal_and_terminal_state() {
    let mut q = seed();
    assert_eq!(claim(&mut q, "a", 100)["task"]["token"], 1);
    let done = apply(
        &mut q,
        json!({"op":"complete","id":"report","owner":"a","token":1,"now":109,"result":"ok"}),
    );
    assert_eq!(done["task"]["state"], "done");
    assert_eq!(claim(&mut q, "b", 110)["status"], "empty");
    rejected(
        &mut q,
        json!({"op":"complete","id":"report","owner":"a","token":1,"now":110,"result":"again"}),
        "lease_rejected",
    );
}
#[test]
fn ownership_and_generation() {
    let mut q = seed();
    claim(&mut q, "a", 100);
    rejected(
        &mut q,
        json!({"op":"complete","id":"report","owner":"b","token":1,"now":101,"result":"bad"}),
        "lease_rejected",
    );
    rejected(
        &mut q,
        json!({"op":"complete","id":"report","owner":"a","token":2,"now":101,"result":"bad"}),
        "lease_rejected",
    );
}
#[test]
fn expiry_boundary_and_same_name_reuse() {
    let mut q = seed();
    claim(&mut q, "a", 100);
    assert_eq!(claim(&mut q, "b", 109)["status"], "empty");
    assert_eq!(claim(&mut q, "a", 110)["task"]["token"], 2);
    rejected(
        &mut q,
        json!({"op":"complete","id":"report","owner":"a","token":1,"now":110,"result":"old"}),
        "lease_rejected",
    );
}
#[test]
fn expired_owner_cannot_write_even_without_takeover() {
    let mut q = seed();
    claim(&mut q, "a", 100);
    rejected(
        &mut q,
        json!({"op":"complete","id":"report","owner":"a","token":1,"now":110,"result":"late"}),
        "lease_rejected",
    );
    rejected(
        &mut q,
        json!({"op":"renew","id":"report","owner":"a","token":1,"now":110,"ttl":10}),
        "lease_rejected",
    );
}
#[test]
fn renewal_extends_without_new_generation() {
    let mut q = seed();
    claim(&mut q, "a", 100);
    let renewed = apply(
        &mut q,
        json!({"op":"renew","id":"report","owner":"a","token":1,"now":105,"ttl":10}),
    );
    assert_eq!(renewed["task"]["lease_until"], 115);
    assert_eq!(renewed["task"]["token"], 1);
    assert_eq!(claim(&mut q, "b", 110)["status"], "empty");
    assert_eq!(claim(&mut q, "b", 115)["task"]["token"], 2);
}
#[test]
fn renewal_cannot_shorten_or_repeat_deadline() {
    let mut q = seed();
    claim(&mut q, "a", 100);
    for ttl in [1, 5] {
        rejected(
            &mut q,
            json!({"op":"renew","id":"report","owner":"a","token":1,"now":105,"ttl":ttl}),
            "lease_rejected",
        );
    }
}
#[test]
fn clock_regression_and_range() {
    let mut q = seed();
    claim(&mut q, "a", 100);
    rejected(
        &mut q,
        json!({"op":"claim","owner":"b","now":99,"ttl":10}),
        "clock_regression",
    );
    rejected(
        &mut q,
        json!({"op":"claim","owner":"b","now":-1,"ttl":10}),
        "invalid_time",
    );
    rejected(
        &mut q,
        json!({"op":"claim","owner":"b","now":4000000000_i64,"ttl":1}),
        "time_limit",
    );
}
#[test]
fn finite_claim_budget() {
    let mut q = seed();
    for n in 1..=3 {
        assert_eq!(claim(&mut q, "a", 90 + n * 10)["task"]["token"], n);
    }
    assert_eq!(claim(&mut q, "b", 130)["status"], "empty");
    assert_eq!(
        apply(&mut q, json!({"op":"show"}))["tasks"][0]["state"],
        "running"
    );
}
#[test]
fn selection_and_task_identity() {
    let mut q = seed();
    apply(
        &mut q,
        json!({"op":"add","id":"aaa","title":"先处理","max_claims":1}),
    );
    assert_eq!(claim(&mut q, "a", 100)["task"]["id"], "aaa");
    assert_eq!(claim(&mut q, "b", 100)["task"]["id"], "report");
    rejected(
        &mut q,
        json!({"op":"add","id":"report","title":"复用","max_claims":3}),
        "duplicate_id",
    );
}
#[test]
fn invalid_inputs_and_rollback() {
    let mut q = seed();
    for ttl in [0, 3601] {
        rejected(
            &mut q,
            json!({"op":"claim","owner":"a","now":100,"ttl":ttl}),
            "invalid_ttl",
        );
    }
    rejected(
        &mut q,
        json!({"op":"claim","owner":"a/b","now":100,"ttl":10}),
        "invalid_owner",
    );
    claim(&mut q, "a", 100);
    rejected(
        &mut q,
        json!({"op":"complete","id":"report","owner":"a","token":1,"now":101,"result":" "}),
        "invalid_result",
    );
    assert!(serde_json::from_value::<Command>(json!({"op":"show","unknown":true})).is_err());
}
#[test]
fn transaction_failure_preserves_all_fields() {
    let mut q = seed();
    let before = apply(&mut q, json!({"op":"show"}));
    let error = q
        .apply(
            serde_json::from_value(json!({"op":"claim","owner":"a","now":100,"ttl":10})).unwrap(),
            Fault::Fail,
        )
        .unwrap_err();
    assert_eq!(error.0, "injected_failure");
    assert_eq!(before, apply(&mut q, json!({"op":"show"})));
}
#[test]
fn bounded_board_and_result_bytes() {
    let mut q = seed();
    for i in 0..31 {
        apply(
            &mut q,
            json!({"op":"add","id":format!("t{i}"),"title":"task","max_claims":1}),
        );
    }
    rejected(
        &mut q,
        json!({"op":"add","id":"overflow","title":"task","max_claims":1}),
        "task_limit",
    );
    claim(&mut q, "a", 100);
    rejected(
        &mut q,
        json!({"op":"complete","id":"report","owner":"a","token":1,"now":101,"result":"中".repeat(171)}),
        "invalid_result",
    );
}
