# Agent RSI: bounded policy search lab

Rust 1.99.1, edition 2024, standard library only. No model key, network service or database.

```sh
cargo test --locked --offline
cargo clippy --locked --offline -- -D warnings
cargo run --locked --offline -- normal /tmp/rsi-new-run 1
cargo run --locked --offline -- overfit /tmp/rsi-new-run 1
cargo run --locked --offline -- rollback /tmp/rsi-new-run 1
```

Use a **fresh, nonexistent** workspace path; its parent must exist. The program removes only the directory it creates after each successful run. Existing directories are refused. Choose a writable temporary directory on your platform.

Scenarios: normal, overfit, evaluator-tamper, permission-escalation, budget, stale-parent, rollback. The final argument is an order seed: odd/even selects one of TWO predefined candidate orders; seeds 1,2,3 are not independent model trials.

Task: sum comma-separated signed i32 values, trim whitespace, reject empty/invalid fields and intermediate overflow. Four development cases, four validation cases and six final test cases are declared in src/main.rs. A candidate receives only its input string. The gate checks development/validation; final tests run once after selection. All datasets are public here, so this is a **simulated holdout by call path**, not hidden data or evidence of generalization. Repeated validation selection makes validation a tuning set.

Four prewritten policies isolate failure modes: Baseline, Trim, Memorize (deliberate development overfit), Robust. Search performs at most three candidate evaluations per run. `candidate_case_evaluations` counts only candidate development/validation calls (8 per attempt), excluding incumbent rescoring and final tests; it is not a total compute or token meter.

The trusted gate accepts a structured proposal from this finite allowlist. Flags model forbidden evaluator/permission changes; they do not detect malicious source code. No arbitrary generated code is executed, and no proposer/evaluator rewrites itself. This demonstrates release safeguards needed around research on recursive self-improvement, **not an implementation or proof of RSI**.

Release files are immutable via create_new, and CURRENT is replaced with a local rename. Rollback reads the baseline through the actual pointer. This is a single-process local filesystem exercise, without fsync durability, concurrent CAS, process sandbox, crash recovery, actual deployment, or rollback of external business effects.

Website source of truth: https://lewislau86.github.io/learn-agent-rust/agent-rsi
