#!/usr/bin/env bash
# Run with: RUSTUP_TOOLCHAIN=stable bash check-environment.sh
# Checks installed tools and a temporary Cargo project; installs nothing.
set -euo pipefail

for env_check_tool in rustup rustc cargo git; do
  if ! command -v "$env_check_tool" >/dev/null 2>&1; then
    printf 'Missing command: %s\n' "$env_check_tool" >&2
    exit 1
  fi
done

# region versions
rustup show active-toolchain
rustc --version
cargo --version
cargo fmt --version
cargo clippy --version
git --version
# endregion versions

# region smoke
# Keep the check outside any existing Cargo workspace and remove it on exit.
env_check_dir=$(mktemp -d "${TMPDIR:-/tmp}/learn-agent-rust-env.XXXXXX")
trap 'rm -rf -- "$env_check_dir"' EXIT
export CARGO_TARGET_DIR="$env_check_dir/target"

cargo new --quiet --vcs none --edition 2024 "$env_check_dir/agent-env-check"
env_check_manifest="$env_check_dir/agent-env-check/Cargo.toml"
cargo fmt --manifest-path "$env_check_manifest" --check
env_check_output=$(cargo run --quiet --offline --manifest-path "$env_check_manifest")
if [ "$env_check_output" != 'Hello, world!' ]; then
  printf 'Unexpected program output: %s\n' "$env_check_output" >&2
  exit 1
fi
printf '%s\n' "$env_check_output"
cargo clippy --quiet --offline --locked --manifest-path "$env_check_manifest" -- -D warnings
printf '%s\n' 'Environment check passed: Rust + Cargo + rustfmt + Clippy.'
# endregion smoke
