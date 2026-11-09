use crate::{
    controller::reserve,
    goal::{self, parse, test_goal},
};

#[test]
fn valid_report_passes() {
    let v = test_goal().grade("total=18\npears=11\napples=7\n");
    assert_eq!(v.kind, "satisfied");
    assert_eq!(v.score, 3);
}

#[test]
fn total_accepts_sum_of_maximum_items() {
    let values = parse(
        "apples=1000000\npears=1000000\ntotal=2000000\n",
        &["apples", "pears", "total"],
    )
    .unwrap();
    assert_eq!(values["total"], values["apples"] + values["pears"]);
    assert!(parse("total=2000001", &["total"]).is_err());
}
#[test]
fn correct_sum_cannot_hide_wrong_items() {
    let v = test_goal().grade("total=18\npears=10\napples=8\n");
    assert_eq!(v.score, 1);
    assert_eq!(v.feedback, vec!["wrong:apples", "wrong:pears"]);
}
#[test]
fn duplicate_keys_rejected() {
    assert!(parse("apples=7\napples=7", &["apples"]).is_err());
}
#[test]
fn unknown_keys_rejected() {
    assert!(parse("admin=1", &["apples"]).is_err());
}
#[test]
fn non_counts_rejected() {
    for value in ["-1", "+1", " 1", "NaN", "4294967296", "1000001", ""] {
        assert!(parse(&format!("apples={value}"), &["apples"]).is_err());
    }
}
#[test]
fn missing_fields_produce_feedback() {
    let v = test_goal().grade("apples=7\npears=11\n");
    assert_eq!(v.score, 2);
    assert_eq!(v.feedback, vec!["missing:total"]);
}
#[test]
fn oversized_report_rejected() {
    assert!(parse(&"a".repeat(goal::MAX_FILE_BYTES + 1), &["apples"]).is_err());
}
#[test]
fn budget_inclusive_boundary_and_failed_reservation() {
    let mut used = 2;
    assert!(reserve(&mut used, 3, 1));
    assert!(!reserve(&mut used, 3, 1));
    assert_eq!(used, 3);
}
#[test]
fn budget_overflow_rejected() {
    let mut used = usize::MAX;
    assert!(!reserve(&mut used, usize::MAX, 1));
    assert_eq!(used, usize::MAX);
}
#[test]
fn progress_is_semantic_not_file_length() {
    let g = test_goal();
    assert_eq!(g.grade("apples=7\npears=11\n").score, 2);
    assert_eq!(g.grade("apples=8\npears=12\ntotal=20\n").score, 0);
}
