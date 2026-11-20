//! Small helpers shared by the chapter experiments.

use std::time::Instant;

/// Milliseconds elapsed since `start`, for printing.
#[must_use]
pub fn ms(start: Instant) -> f64 {
    start.elapsed().as_secs_f64() * 1000.0
}

/// Names of all threads in this process (Linux only, read from /proc).
#[must_use]
pub fn thread_names() -> Vec<String> {
    let Ok(dir) = std::fs::read_dir("/proc/self/task") else {
        return vec!["(thread listing needs Linux /proc)".to_string()];
    };
    let mut names: Vec<String> = dir
        .filter_map(|e| e.ok())
        .filter_map(|e| std::fs::read_to_string(e.path().join("comm")).ok())
        .map(|s| s.trim().to_string())
        .collect();
    names.sort();
    names
}

/// Thread names grouped as "name ×count".
#[must_use]
pub fn thread_summary() -> String {
    let names = thread_names();
    let mut out: Vec<(String, usize)> = Vec::new();
    for n in names {
        match out.iter_mut().find(|(k, _)| *k == n) {
            Some((_, c)) => *c += 1,
            None => out.push((n, 1)),
        }
    }
    out.iter()
        .map(|(n, c)| format!("{n} ×{c}"))
        .collect::<Vec<_>>()
        .join(", ")
}

/// Runs `f`, catching a panic and returning its message instead.
pub fn catch_panic<R>(f: impl FnOnce() -> R + std::panic::UnwindSafe) -> Result<R, String> {
    let hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(|_| {}));
    let result = std::panic::catch_unwind(f);
    std::panic::set_hook(hook);
    result.map_err(|payload| {
        payload
            .downcast_ref::<String>()
            .cloned()
            .or_else(|| payload.downcast_ref::<&str>().map(|s| (*s).to_string()))
            .unwrap_or_else(|| "<non-string panic>".to_string())
    })
}

/// A minimal `log` backend that prints WARN and above to stdout.
pub struct PrintLogger;

impl log::Log for PrintLogger {
    fn enabled(&self, metadata: &log::Metadata) -> bool {
        metadata.level() <= log::Level::Warn
    }
    fn log(&self, record: &log::Record) {
        if self.enabled(record.metadata()) {
            println!("    [log {}] {}", record.level(), record.args());
        }
    }
    fn flush(&self) {}
}

pub fn init_print_logger() {
    static LOGGER: PrintLogger = PrintLogger;
    let _ = log::set_logger(&LOGGER);
    log::set_max_level(log::LevelFilter::Warn);
}
