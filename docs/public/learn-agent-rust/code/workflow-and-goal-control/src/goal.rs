use serde::Serialize;
use std::{collections::BTreeMap, fs, path::Path};

pub type Counts = BTreeMap<String, u32>;
pub const MAX_FILE_BYTES: usize = 512;

pub fn parse(text: &str, keys: &[&str]) -> Result<Counts, &'static str> {
    if text.len() > MAX_FILE_BYTES {
        return Err("file_too_large");
    }
    let mut counts = Counts::new();
    for line in text.lines() {
        let (key, value) = line.split_once('=').ok_or("malformed_line")?;
        if !keys.contains(&key) || counts.contains_key(key) {
            return Err("unknown_or_duplicate_key");
        }
        if value.is_empty() || !value.bytes().all(|b| b.is_ascii_digit()) {
            return Err("invalid_count");
        }
        let number: u32 = value.parse().map_err(|_| "invalid_count")?;
        let maximum = if key == "total" { 2_000_000 } else { 1_000_000 };
        if number > maximum {
            return Err("count_too_large");
        }
        counts.insert(key.to_string(), number);
    }
    Ok(counts)
}

pub fn read_bounded(path: &Path) -> Result<String, &'static str> {
    use std::io::Read;
    let file = fs::File::open(path).map_err(|_| "file_unreadable")?;
    if !file.metadata().map_err(|_| "file_unreadable")?.is_file() {
        return Err("not_regular_file");
    }
    let mut bytes = Vec::new();
    file.take((MAX_FILE_BYTES + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|_| "file_unreadable")?;
    if bytes.len() > MAX_FILE_BYTES {
        return Err("file_too_large");
    }
    String::from_utf8(bytes).map_err(|_| "invalid_utf8")
}

// region contract
#[derive(Serialize)]
pub struct Goal {
    source: String,
    expected: Counts,
}

impl Goal {
    pub fn prepare(root: &Path) -> Result<Self, &'static str> {
        let source = read_bounded(&root.join("source.txt"))?;
        let mut expected = parse(&source, &["apples", "pears"])?;
        if expected.len() != 2 {
            return Err("source_incomplete");
        }
        expected.insert("total".into(), expected.values().sum());
        Ok(Self { source, expected })
    }
}

#[derive(Clone, Serialize)]
pub struct Verdict {
    pub kind: &'static str,
    pub score: usize,
    pub feedback: Vec<String>,
}
// endregion contract

// region verify
impl Goal {
    pub fn verify(&self, root: &Path) -> Verdict {
        if read_bounded(&root.join("source.txt")).as_ref() != Ok(&self.source) {
            return Verdict {
                kind: "blocked",
                score: 0,
                feedback: vec!["source_changed".into()],
            };
        }
        let text = match read_bounded(&root.join("report.txt")) {
            Ok(text) => text,
            Err(code) => {
                return Verdict {
                    kind: "repairable",
                    score: 0,
                    feedback: vec![format!("report:{code}")],
                };
            }
        };
        self.grade(&text)
    }

    pub fn grade(&self, text: &str) -> Verdict {
        let actual = match parse(text, &["apples", "pears", "total"]) {
            Ok(value) => value,
            Err(code) => {
                return Verdict {
                    kind: "repairable",
                    score: 0,
                    feedback: vec![format!("report:{code}")],
                };
            }
        };
        let mut feedback = Vec::new();
        for (key, expected) in &self.expected {
            match actual.get(key) {
                None => feedback.push(format!("missing:{key}")),
                Some(value) if value != expected => feedback.push(format!("wrong:{key}")),
                _ => {}
            }
        }
        Verdict {
            kind: if feedback.is_empty() {
                "satisfied"
            } else {
                "repairable"
            },
            score: self.expected.len() - feedback.len(),
            feedback,
        }
    }
}
// endregion verify

#[cfg(test)]
pub fn test_goal() -> Goal {
    Goal {
        source: "apples=7\npears=11\n".into(),
        expected: Counts::from([
            ("apples".into(), 7),
            ("pears".into(), 11),
            ("total".into(), 18),
        ]),
    }
}
