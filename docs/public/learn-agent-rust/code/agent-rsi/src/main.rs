use std::fs;
use std::path::{Path, PathBuf};

type Case = (&'static str, &'static str);
// Labels belong to the trusted evaluator. A policy receives only the input.
const DEV: &[Case] = &[("1,2", "3"), (" 2,3 ", "5"), ("-2,1", "-1"), ("x,1", "ERR")];
const VALIDATION: &[Case] = &[
    (" 5, 6", "11"),
    ("7,q", "ERR"),
    ("2147483647,1", "ERR"),
    ("3,-3", "0"),
];
const TEST: &[Case] = &[
    (" 8,9 ", "17"),
    ("", "ERR"),
    ("2,,3", "ERR"),
    ("-2147483648,-1", "ERR"),
    ("-10,5", "-5"),
    ("2147483647,0", "2147483647"),
];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Policy {
    Baseline,
    Trim,
    Memorize,
    Robust,
}

// region task-policy
impl Policy {
    fn run(self, input: &str) -> String {
        if self == Self::Memorize {
            // Deliberate development-set overfit. No validation/test labels here.
            return match input {
                "1,2" => "3",
                " 2,3 " => "5",
                "-2,1" => "-1",
                "x,1" => "ERR",
                _ => "0",
            }
            .into();
        }
        if self == Self::Robust {
            let value = input.split(',').try_fold(0_i32, |sum, field| {
                let value = field.trim().parse::<i32>().ok()?;
                sum.checked_add(value)
            });
            return value.map_or_else(|| "ERR".into(), |n| n.to_string());
        }
        input
            .split(',')
            .fold(0_i32, |sum, field| {
                let field = if self == Self::Trim {
                    field.trim()
                } else {
                    field
                };
                sum.wrapping_add(field.parse::<i32>().unwrap_or(0))
            })
            .to_string()
    }
}
// endregion task-policy

fn score(policy: Policy, cases: &[Case]) -> usize {
    cases
        .iter()
        .filter(|(input, expected)| policy.run(input) == *expected)
        .count()
}

// region promotion-gate
#[derive(Clone, Copy)]
struct Proposal {
    policy: Policy,
    parent: u32,
    evaluator_changed: bool,
    extra_permission: bool,
    cost: usize,
}

struct Search {
    current: Policy,
    revision: u32,
    remaining: usize,
    attempts: usize,
    evaluations: usize,
}

impl Search {
    fn try_candidate(&mut self, proposal: Proposal) -> Result<(usize, usize), &'static str> {
        if proposal.parent != self.revision {
            return Err("stale_parent");
        }
        if proposal.evaluator_changed {
            return Err("evaluator_changed");
        }
        if proposal.extra_permission {
            return Err("permission_expanded");
        }
        if proposal.cost != 1 {
            return Err("invalid_cost");
        }
        if self.remaining == 0 {
            return Err("search_budget");
        }
        self.remaining -= 1;
        self.attempts += 1;
        // Four policies form a finite fixture. This is not arbitrary code execution.
        let dev = score(proposal.policy, DEV);
        let validation = score(proposal.policy, VALIDATION);
        self.evaluations += DEV.len() + VALIDATION.len();
        println!(
            "candidate={:?} dev={}/{} validation={}/{}",
            proposal.policy,
            dev,
            DEV.len(),
            validation,
            VALIDATION.len()
        );
        if dev < score(self.current, DEV) || validation <= score(self.current, VALIDATION) {
            return Err("no_validated_gain");
        }
        self.current = proposal.policy;
        self.revision += 1;
        Ok((dev, validation))
    }
}
// endregion promotion-gate

fn proposal(policy: Policy, parent: u32) -> Proposal {
    Proposal {
        policy,
        parent,
        evaluator_changed: false,
        extra_permission: false,
        cost: 1,
    }
}

struct Workspace(PathBuf);
impl Drop for Workspace {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

// region release
fn publish(root: &Path, revision: u32, policy: Policy) {
    let version = format!("revision-{revision}.txt");
    let mut options = fs::OpenOptions::new();
    use std::io::Write;
    options
        .write(true)
        .create_new(true)
        .open(root.join(&version))
        .unwrap()
        .write_all(format!("{policy:?}\n").as_bytes())
        .unwrap();
    fs::write(root.join("CURRENT.next"), format!("{version}\n")).unwrap();
    fs::rename(root.join("CURRENT.next"), root.join("CURRENT")).unwrap();
}

fn load_current(root: &Path) -> Policy {
    let version = fs::read_to_string(root.join("CURRENT")).unwrap();
    match fs::read_to_string(root.join(version.trim()))
        .unwrap()
        .trim()
    {
        "Baseline" => Policy::Baseline,
        "Trim" => Policy::Trim,
        "Memorize" => Policy::Memorize,
        "Robust" => Policy::Robust,
        other => panic!("unknown fixture policy: {other}"),
    }
}
// endregion release

const SCENARIOS: &[&str] = &[
    "normal",
    "overfit",
    "evaluator-tamper",
    "permission-escalation",
    "budget",
    "stale-parent",
    "rollback",
];

fn experiment(name: &str, root: &Path, seed: u32) {
    fs::create_dir(root).expect("experiment requires a fresh workspace path");
    let guard = Workspace(root.into());
    let mut search = Search {
        current: Policy::Baseline,
        revision: 0,
        remaining: 3,
        attempts: 0,
        evaluations: 0,
    };
    publish(root, 0, Policy::Baseline);
    println!("scenario={name} order_seed={seed}");
    println!(
        "baseline dev={}/{} validation={}/{}",
        score(Policy::Baseline, DEV),
        DEV.len(),
        score(Policy::Baseline, VALIDATION),
        VALIDATION.len()
    );
    let policies = match name {
        "normal" => {
            if seed.is_multiple_of(2) {
                vec![Policy::Memorize, Policy::Trim, Policy::Robust]
            } else {
                vec![Policy::Trim, Policy::Memorize, Policy::Robust]
            }
        }
        "overfit" => vec![Policy::Memorize],
        "budget" => {
            search.remaining = 0;
            vec![Policy::Robust]
        }
        "stale-parent" => vec![Policy::Trim, Policy::Robust],
        _ => vec![Policy::Robust],
    };
    for policy in policies {
        let mut candidate = proposal(policy, search.revision);
        candidate.evaluator_changed = name == "evaluator-tamper";
        candidate.extra_permission = name == "permission-escalation";
        if name == "stale-parent" && search.revision > 0 {
            candidate.parent = 0;
        }
        let previous = search.current;
        match search.try_candidate(candidate) {
            Ok(_) => {
                publish(root, search.revision, search.current);
                assert_eq!(load_current(root), search.current);
                println!(
                    "decision=promote revision={} previous={previous:?} current={:?}",
                    search.revision, search.current
                );
            }
            Err(reason) => println!(
                "decision=reject reason={reason} current={:?}",
                search.current
            ),
        }
    }
    if name == "rollback" {
        // Trusted operator's injected runtime alarm, separate from search scores.
        fs::write(root.join("CURRENT.next"), "revision-0.txt\n").unwrap();
        fs::rename(root.join("CURRENT.next"), root.join("CURRENT")).unwrap();
        println!("runtime_alarm=true rollback_to=revision-0");
    }
    let deployed = load_current(root);
    // Once per run, only after selection. These cases are not read by the gate.
    let baseline_test = score(Policy::Baseline, TEST);
    let selected_test = score(deployed, TEST);
    println!(
        "audit baseline_test={baseline_test}/{} selected_test={selected_test}/{} deployed={deployed:?}",
        TEST.len(),
        TEST.len()
    );
    println!(
        "search_attempts={} candidate_case_evaluations={} remaining={}",
        search.attempts, search.evaluations, search.remaining
    );
    assert_eq!(
        fs::read_to_string(root.join("revision-0.txt")).unwrap(),
        "Baseline\n"
    );
    println!("baseline_preserved=true pointer_matches_policy=true");
    drop(guard);
    println!("workspace_removed={}", !root.exists());
}

fn main() {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.len() != 3 || !SCENARIOS.contains(&args[0].as_str()) {
        eprintln!("usage: agent-rsi-lab <scenario> <fresh-workspace-path> <order-seed>");
        std::process::exit(2);
    }
    let Ok(seed) = args[2].parse::<u32>() else {
        std::process::exit(2);
    };
    experiment(&args[0], Path::new(&args[1]), seed);
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn robust_checks_whitespace_invalid_and_overflow() {
        for &(input, expected) in DEV.iter().chain(VALIDATION).chain(TEST) {
            assert_eq!(Policy::Robust.run(input), expected);
        }
        assert_eq!(Policy::Robust.run("1.5,2"), "ERR");
    }
    #[test]
    fn dev_overfit_fails_validation_and_does_not_replace_current() {
        let mut s = Search {
            current: Policy::Baseline,
            revision: 0,
            remaining: 3,
            attempts: 0,
            evaluations: 0,
        };
        assert_eq!(score(Policy::Memorize, DEV), DEV.len());
        assert_eq!(
            s.try_candidate(proposal(Policy::Memorize, 0)),
            Err("no_validated_gain")
        );
        assert_eq!(s.current, Policy::Baseline);
        assert_eq!(s.remaining, 2);
    }
    #[test]
    fn trusted_boundaries_refuse_before_evaluation() {
        for reason in [
            "evaluator_changed",
            "permission_expanded",
            "invalid_cost",
            "stale_parent",
            "search_budget",
        ] {
            let mut s = Search {
                current: Policy::Baseline,
                revision: 0,
                remaining: 3,
                attempts: 0,
                evaluations: 0,
            };
            let mut p = proposal(Policy::Robust, 0);
            match reason {
                "evaluator_changed" => p.evaluator_changed = true,
                "permission_expanded" => p.extra_permission = true,
                "invalid_cost" => p.cost = 0,
                "stale_parent" => p.parent = 1,
                _ => s.remaining = 0,
            }
            assert_eq!(s.try_candidate(p), Err(reason));
            assert_eq!(s.evaluations, 0);
            assert_eq!(s.revision, 0);
        }
    }
    #[test]
    fn accepted_versions_require_strict_validation_gain() {
        let mut s = Search {
            current: Policy::Baseline,
            revision: 0,
            remaining: 3,
            attempts: 0,
            evaluations: 0,
        };
        s.try_candidate(proposal(Policy::Trim, 0)).unwrap();
        s.try_candidate(proposal(Policy::Robust, 1)).unwrap();
        assert_eq!(
            s.try_candidate(proposal(Policy::Robust, 2)),
            Err("no_validated_gain")
        );
        assert_eq!(s.current, Policy::Robust);
        assert_eq!(s.revision, 2);
        assert_eq!(s.remaining, 0);
    }
}
