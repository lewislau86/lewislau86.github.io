//! Application-owned discovery and bounded activation; never executes skill scripts.
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    fs,
    io::Read,
    path::{Path, PathBuf},
};

pub type SkillResult<T> = Result<T, &'static str>;
pub const MAX_FILE_BYTES: usize = 8192;
const MAX_SKILLS: usize = 32;

// region manifest
#[derive(Clone, Debug, Deserialize)]
struct Manifest {
    name: String,
    description: String,
    metadata: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Serialize)]
pub struct Entry {
    pub name: String,
    pub description: String,
    pub version: String,
    pub sha256: String,
    #[serde(skip)]
    path: PathBuf,
}

pub struct SkillStore {
    root: PathBuf,
    pub entries: BTreeMap<String, Entry>,
}

#[derive(Clone, Debug, Serialize)]
pub struct Loaded {
    pub name: String,
    pub version: String,
    pub sha256: String,
    pub instructions: String,
}
// endregion manifest

fn valid_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 64
        && !name.starts_with('-')
        && !name.ends_with('-')
        && !name.contains("--")
        && name
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
}

pub fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn read_bounded(path: &Path) -> SkillResult<Vec<u8>> {
    let meta = fs::symlink_metadata(path).map_err(|_| "missing_manifest")?;
    if !meta.is_file() {
        return Err("unsafe_manifest");
    }
    let mut bytes = Vec::new();
    fs::File::open(path)
        .map_err(|_| "manifest_io")?
        .take((MAX_FILE_BYTES + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|_| "manifest_io")?;
    if bytes.len() > MAX_FILE_BYTES {
        return Err("file_too_large");
    }
    Ok(bytes)
}

// region parse
fn parse(raw: &[u8]) -> SkillResult<(Manifest, String)> {
    let text = std::str::from_utf8(raw)
        .map_err(|_| "invalid_utf8")?
        .replace("\r\n", "\n");
    let rest = text.strip_prefix("---\n").ok_or("missing_frontmatter")?;
    let (yaml, body) = rest
        .split_once("\n---\n")
        .ok_or("missing_frontmatter_end")?;
    // Value's mapping deserializer rejects duplicate keys, including metadata keys.
    let yaml: serde_yaml_ng::Value =
        serde_yaml_ng::from_str(yaml).map_err(|_| "invalid_metadata")?;
    let meta: Manifest = serde_yaml_ng::from_value(yaml).map_err(|_| "invalid_metadata")?;
    if !valid_name(&meta.name)
        || meta.description.trim().is_empty()
        || meta.description.chars().count() > 1024
        || meta
            .metadata
            .get("version")
            .is_none_or(|v| v.trim().is_empty() || v.len() > 64)
        || body.trim().is_empty()
    {
        return Err("invalid_metadata");
    }
    Ok((meta, body.trim().into()))
}
// endregion parse

impl SkillStore {
    // region discover
    pub fn discover(root: &Path) -> SkillResult<Self> {
        let root = root.canonicalize().map_err(|_| "missing_skills_root")?;
        let mut paths: Vec<_> = fs::read_dir(&root)
            .map_err(|_| "catalog_io")?
            .take(MAX_SKILLS + 1)
            .map(|entry| entry.map(|e| e.path()).map_err(|_| "catalog_io"))
            .collect::<SkillResult<_>>()?;
        if paths.len() > MAX_SKILLS {
            return Err("catalog_too_large");
        }
        paths.sort();
        let mut entries = BTreeMap::new();
        for folder in paths {
            let kind = fs::symlink_metadata(&folder)
                .map_err(|_| "catalog_io")?
                .file_type();
            if kind.is_symlink() {
                return Err("unsafe_skill_directory");
            }
            if !kind.is_dir() {
                continue;
            }
            let path = folder.join("SKILL.md");
            let raw = read_bounded(&path)?;
            let (meta, _) = parse(&raw)?;
            if folder.file_name().and_then(|s| s.to_str()) != Some(meta.name.as_str()) {
                return Err("name_mismatch");
            }
            let entry = Entry {
                version: meta.metadata["version"].clone(),
                name: meta.name.clone(),
                description: meta.description,
                sha256: digest(&raw),
                path,
            };
            if entries.insert(meta.name, entry).is_some() {
                return Err("duplicate_name");
            }
        }
        Ok(Self { root, entries })
    }
    // endregion discover

    pub fn catalog(&self) -> String {
        self.entries
            .values()
            .map(|e| format!("- {}@{}: {}\n", e.name, e.version, e.description))
            .collect()
    }

    // region load
    pub fn load(&self, name: &str) -> SkillResult<Loaded> {
        if !valid_name(name) {
            return Err("invalid_skill_name");
        }
        let entry = self.entries.get(name).ok_or("unknown_skill")?;
        // Reject a folder changed into a symlink after discovery as well.
        if !fs::symlink_metadata(entry.path.parent().unwrap())
            .map_err(|_| "missing_manifest")?
            .is_dir()
        {
            return Err("unsafe_skill_directory");
        }
        let resolved = entry.path.canonicalize().map_err(|_| "missing_manifest")?;
        if !resolved.starts_with(&self.root) {
            return Err("outside_skills_root");
        }
        let raw = read_bounded(&entry.path)?;
        if digest(&raw) != entry.sha256 {
            return Err("stale_skill");
        }
        let (_, instructions) = parse(&raw)?;
        Ok(Loaded {
            name: name.into(),
            version: entry.version.clone(),
            sha256: entry.sha256.clone(),
            instructions,
        })
    }
    // endregion load
}

#[cfg(test)]
mod tests {
    use super::*;
    const REVIEW: &str = include_str!("../skills/rust-review/SKILL.md");

    fn fixture() -> tempfile::TempDir {
        let dir = tempfile::tempdir().unwrap();
        fs::create_dir(dir.path().join("rust-review")).unwrap();
        fs::write(dir.path().join("rust-review/SKILL.md"), REVIEW).unwrap();
        dir
    }

    #[test]
    fn catalog_contains_metadata_but_not_body() {
        let dir = fixture();
        let store = SkillStore::discover(dir.path()).unwrap();
        assert!(store.catalog().contains("rust-review@1.0.0"));
        assert!(!store.catalog().contains("先给结论"));
        assert!(
            store
                .load("rust-review")
                .unwrap()
                .instructions
                .contains("先给结论")
        );
    }

    #[test]
    fn names_do_not_become_paths() {
        let dir = fixture();
        let store = SkillStore::discover(dir.path()).unwrap();
        for name in ["../rust-review", "/etc/passwd", "rust--review", "Rust", ""] {
            assert_eq!(store.load(name).unwrap_err(), "invalid_skill_name");
        }
        assert_eq!(store.load("absent").unwrap_err(), "unknown_skill");
    }

    #[test]
    fn same_version_changed_body_is_rejected() {
        let dir = fixture();
        let store = SkillStore::discover(dir.path()).unwrap();
        fs::write(
            dir.path().join("rust-review/SKILL.md"),
            format!("{REVIEW}\n改写内容"),
        )
        .unwrap();
        assert_eq!(store.load("rust-review").unwrap_err(), "stale_skill");
    }

    #[test]
    fn size_limit_applies_before_parsing() {
        let dir = fixture();
        fs::write(
            dir.path().join("rust-review/SKILL.md"),
            vec![b'a'; MAX_FILE_BYTES + 1],
        )
        .unwrap();
        assert!(matches!(
            SkillStore::discover(dir.path()),
            Err("file_too_large")
        ));
    }

    #[test]
    fn malformed_and_duplicate_yaml_are_rejected() {
        for raw in [
            "plain markdown",
            "---\nname: [\n---\nbody",
            "---\nname: rust-review\nname: rust-review\n---\nbody",
        ] {
            assert!(parse(raw.as_bytes()).is_err());
        }
        for raw in [
            REVIEW.replace("name: rust-review", "name: rust-review\nname: rust-review"),
            REVIEW.replace(
                "  version: \"1.0.0\"",
                "  version: \"1.0.0\"\n  version: \"2.0.0\"",
            ),
        ] {
            assert!(parse(raw.as_bytes()).is_err());
        }
    }

    #[test]
    fn metadata_version_is_a_course_requirement() {
        assert!(
            parse(
                REVIEW
                    .replace("  version: \"1.0.0\"", "  author: course")
                    .as_bytes()
            )
            .is_err()
        );
        assert!(
            parse(
                REVIEW
                    .replace("name: rust-review", "name: other")
                    .as_bytes()
            )
            .is_ok()
        );
        let dir = fixture();
        fs::write(
            dir.path().join("rust-review/SKILL.md"),
            REVIEW.replace("name: rust-review", "name: other"),
        )
        .unwrap();
        assert!(matches!(
            SkillStore::discover(dir.path()),
            Err("name_mismatch")
        ));
    }

    #[test]
    fn yaml_multiline_description_is_supported() {
        let raw = REVIEW.replace(
            "description: 审查 Rust 函数的边界条件，适用于代码审查任务。",
            "description: >\n  Review Rust.\n  Use for code review.",
        );
        let (meta, _) = parse(raw.as_bytes()).unwrap();
        assert!(
            meta.description
                .contains("Review Rust. Use for code review.")
        );
    }

    #[test]
    fn deleted_manifest_is_reported() {
        let dir = fixture();
        let store = SkillStore::discover(dir.path()).unwrap();
        fs::remove_file(dir.path().join("rust-review/SKILL.md")).unwrap();
        assert_eq!(store.load("rust-review").unwrap_err(), "missing_manifest");
    }

    #[test]
    fn discovery_stops_at_catalog_limit() {
        let dir = tempfile::tempdir().unwrap();
        for index in 0..=MAX_SKILLS {
            fs::create_dir(dir.path().join(format!("skill-{index}"))).unwrap();
        }
        assert!(matches!(
            SkillStore::discover(dir.path()),
            Err("catalog_too_large")
        ));
    }

    #[cfg(unix)]
    #[test]
    fn symlink_replacement_is_rejected() {
        let dir = fixture();
        let store = SkillStore::discover(dir.path()).unwrap();
        let outside = tempfile::tempdir().unwrap();
        fs::write(outside.path().join("SKILL.md"), REVIEW).unwrap();
        fs::remove_dir_all(dir.path().join("rust-review")).unwrap();
        std::os::unix::fs::symlink(outside.path(), dir.path().join("rust-review")).unwrap();
        assert_eq!(
            store.load("rust-review").unwrap_err(),
            "unsafe_skill_directory"
        );
    }
}
