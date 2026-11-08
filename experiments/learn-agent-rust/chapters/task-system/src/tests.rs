use crate::tasks::{Board, Status, Update};

fn add(board: Board, id: &str, dependencies: &[&str], max_attempts: u32) -> Board {
    board
        .propose(
            board.revision,
            Update::Add {
                id: id.into(),
                title: format!("task {id}"),
                depends_on: dependencies.iter().map(|s| (*s).into()).collect(),
                max_attempts,
            },
        )
        .unwrap()
}
fn start(board: Board, id: &str) -> Board {
    board
        .propose(board.revision, Update::Start { id: id.into() })
        .unwrap()
}
fn complete(board: Board, id: &str) -> Board {
    let attempt = board.task(id).unwrap().attempts;
    board
        .propose(
            board.revision,
            Update::Complete {
                id: id.into(),
                attempt,
                result: "checked".into(),
            },
        )
        .unwrap()
}
fn fail(board: Board, id: &str) -> Board {
    let attempt = board.task(id).unwrap().attempts;
    board
        .propose(
            board.revision,
            Update::Fail {
                id: id.into(),
                attempt,
                error: "transient fixture".into(),
            },
        )
        .unwrap()
}

#[test]
fn dependencies_unlock_only_after_completion() {
    let board = add(add(Board::empty(), "a", &[], 2), "b", &["a"], 2);
    assert_eq!(board.ready(), vec!["a"]);
    assert_eq!(
        board
            .propose(2, Update::Start { id: "b".into() })
            .unwrap_err()
            .code,
        "dependency_incomplete"
    );
    let board = start(board, "a");
    assert!(board.ready().is_empty());
    let board = complete(board, "a");
    assert_eq!(board.ready(), vec!["b"]);
}

#[test]
fn indirect_cycle_is_rejected_without_mutating_source() {
    let board = add(
        add(add(Board::empty(), "a", &[], 2), "b", &["a"], 2),
        "c",
        &["b"],
        2,
    );
    let copy = board.clone();
    let error = board
        .propose(
            3,
            Update::SetDependencies {
                id: "a".into(),
                depends_on: vec!["c".into()],
            },
        )
        .unwrap_err();
    assert_eq!(error.code, "dependency_cycle");
    assert_eq!(board, copy);
}

#[test]
fn self_cycle_missing_and_duplicate_edges_are_rejected() {
    let board = add(Board::empty(), "a", &[], 2);
    for (edges, expected) in [
        (vec!["a".into()], "dependency_cycle"),
        (vec!["unknown".into()], "dependency_missing"),
        (vec!["a".into(), "a".into()], "duplicate_dependency"),
    ] {
        let id = if expected == "dependency_cycle" {
            "a"
        } else {
            "b"
        };
        let op = if id == "a" {
            Update::SetDependencies {
                id: id.into(),
                depends_on: edges,
            }
        } else {
            Update::Add {
                id: id.into(),
                title: "b".into(),
                depends_on: edges,
                max_attempts: 2,
            }
        };
        assert_eq!(board.propose(1, op).unwrap_err().code, expected);
    }
}

#[test]
fn pending_cannot_be_completed_and_completed_cannot_restart() {
    let board = add(Board::empty(), "a", &[], 2);
    assert_eq!(
        board
            .propose(
                1,
                Update::Complete {
                    id: "a".into(),
                    attempt: 0,
                    result: "claim".into()
                }
            )
            .unwrap_err()
            .code,
        "illegal_transition"
    );
    let board = complete(start(board, "a"), "a");
    assert_eq!(
        board
            .propose(3, Update::Start { id: "a".into() })
            .unwrap_err()
            .code,
        "illegal_transition"
    );
}

#[test]
fn single_executor_blocks_independent_second_start() {
    let board = start(add(add(Board::empty(), "a", &[], 2), "b", &[], 2), "a");
    assert_eq!(
        board
            .propose(3, Update::Start { id: "b".into() })
            .unwrap_err()
            .code,
        "executor_busy"
    );
    assert_eq!(board.reconcile(), vec!["a"]);
}

#[test]
fn attempts_survive_explicit_retry_and_stop_at_limit() {
    let board = fail(start(add(Board::empty(), "a", &[], 2), "a"), "a");
    let board = board
        .propose(board.revision, Update::Retry { id: "a".into() })
        .unwrap();
    assert_eq!(board.task("a").unwrap().attempts, 1);
    assert!(board.task("a").unwrap().last_error.is_some());
    let board = fail(start(board, "a"), "a");
    assert_eq!(board.task("a").unwrap().attempts, 2);
    assert_eq!(
        board
            .propose(board.revision, Update::Retry { id: "a".into() })
            .unwrap_err()
            .code,
        "attempt_limit"
    );
}

#[test]
fn stale_attempt_result_cannot_complete_a_later_run() {
    let board = fail(start(add(Board::empty(), "a", &[], 2), "a"), "a");
    let board = board
        .propose(board.revision, Update::Retry { id: "a".into() })
        .unwrap();
    let board = start(board, "a");
    assert_eq!(
        board
            .propose(
                board.revision,
                Update::Complete {
                    id: "a".into(),
                    attempt: 1,
                    result: "old worker".into()
                }
            )
            .unwrap_err()
            .code,
        "attempt_conflict"
    );
    assert_eq!(board.task("a").unwrap().status, Status::Running);
}

#[test]
fn dependencies_freeze_at_first_start() {
    let board = fail(start(add(Board::empty(), "a", &[], 2), "a"), "a");
    let board = board
        .propose(board.revision, Update::Retry { id: "a".into() })
        .unwrap();
    assert_eq!(
        board
            .propose(
                board.revision,
                Update::SetDependencies {
                    id: "a".into(),
                    depends_on: vec![]
                }
            )
            .unwrap_err()
            .code,
        "dependencies_frozen"
    );
}

#[test]
fn stale_revision_and_revision_overflow_are_rejected() {
    let mut board = add(Board::empty(), "a", &[], 2);
    assert_eq!(
        board
            .propose(0, Update::Start { id: "a".into() })
            .unwrap_err()
            .code,
        "revision_conflict"
    );
    board.revision = u64::MAX;
    assert_eq!(
        board
            .propose(u64::MAX, Update::Start { id: "a".into() })
            .unwrap_err()
            .code,
        "revision_limit"
    );
    assert_eq!(board.task("a").unwrap().attempts, 0);
}

#[test]
fn forged_completed_dependency_is_rejected_on_load_validation() {
    let mut board = add(add(Board::empty(), "a", &[], 2), "b", &["a"], 2);
    board.tasks[1].status = Status::Completed;
    board.tasks[1].attempts = 1;
    board.tasks[1].result = Some("forged".into());
    assert_eq!(board.validate().unwrap_err().code, "dependency_incomplete");
}

#[test]
fn diamond_needs_both_parents() {
    let board = add(
        add(
            add(add(Board::empty(), "a", &[], 2), "b", &["a"], 2),
            "c",
            &["a"],
            2,
        ),
        "d",
        &["b", "c"],
        2,
    );
    let board = complete(start(board, "a"), "a");
    assert_eq!(board.ready(), vec!["b", "c"]);
    let board = complete(start(board, "b"), "b");
    assert_eq!(board.ready(), vec!["c"]);
    let board = complete(start(board, "c"), "c");
    assert_eq!(board.ready(), vec!["d"]);
}

#[test]
fn json_contract_rejects_unknown_fields_and_duplicate_revision() {
    let op = r#"{"op":"start","id":"a","owner":"untrusted"}"#;
    assert!(serde_json::from_str::<Update>(op).is_err());
    let board = r#"{"schema":1,"revision":0,"revision":1,"tasks":[]}"#;
    assert!(serde_json::from_str::<Board>(board).is_err());
}

#[test]
fn field_and_board_limits_are_checked() {
    let mut board = Board::empty();
    assert_eq!(
        board
            .propose(
                0,
                Update::Add {
                    id: "../escape".into(),
                    title: "x".into(),
                    depends_on: vec![],
                    max_attempts: 2
                }
            )
            .unwrap_err()
            .code,
        "invalid_task"
    );
    for n in 0..32 {
        board = add(board, &format!("t{n}"), &[], 2);
    }
    assert_eq!(
        board
            .propose(
                32,
                Update::Add {
                    id: "extra".into(),
                    title: "x".into(),
                    depends_on: vec![],
                    max_attempts: 2
                }
            )
            .unwrap_err()
            .code,
        "task_limit"
    );
    board.tasks[0].max_attempts = 0;
    assert_eq!(board.validate().unwrap_err().code, "invalid_attempts");
}

#[test]
fn duplicate_task_id_and_empty_completion_are_rejected() {
    let board = add(Board::empty(), "a", &[], 2);
    assert_eq!(
        board
            .propose(
                1,
                Update::Add {
                    id: "a".into(),
                    title: "another".into(),
                    depends_on: vec![],
                    max_attempts: 2
                }
            )
            .unwrap_err()
            .code,
        "duplicate_id"
    );
    let board = start(board, "a");
    assert_eq!(
        board
            .propose(
                2,
                Update::Complete {
                    id: "a".into(),
                    attempt: 1,
                    result: " ".into()
                }
            )
            .unwrap_err()
            .code,
        "invalid_detail"
    );
}
