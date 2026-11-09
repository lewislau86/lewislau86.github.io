use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};

// region records
#[derive(Clone, Debug)]
struct Chunk {
    id: String,
    scope: String,
    path: PathBuf,
    heading: String,
    start: usize,
    end: usize,
    text: String,
    snapshot: String,
    terms: Vec<String>,
}

#[derive(Debug)]
struct Hit<'a> {
    chunk: &'a Chunk,
    score: f64,
}

#[derive(Debug, PartialEq)]
struct Claim {
    quote: String,
    citation: String,
}
// endregion records

// English words and numbers only: a deliberately small lexical baseline.
fn tokenize(text: &str) -> Vec<String> {
    text.split(|c: char| !c.is_ascii_alphanumeric())
        .filter(|s| !s.is_empty())
        .map(str::to_ascii_lowercase)
        .collect()
}

// Display fingerprint only; freshness compares the complete source bytes.
fn fingerprint(text: &str) -> u64 {
    text.bytes().fold(0xcbf29ce484222325, |hash, byte| {
        (hash ^ u64::from(byte)).wrapping_mul(0x100000001b3)
    })
}

// region chunking
fn chunk_document(scope: &str, path: &Path) -> Result<Vec<Chunk>, String> {
    let snapshot = fs::read_to_string(path).map_err(|e| e.to_string())?;
    let lines: Vec<_> = snapshot.lines().collect();
    let mut chunks = Vec::new();
    let mut heading = String::new();
    let mut i = 0;
    while i < lines.len() {
        if lines[i].starts_with('#') {
            heading = lines[i].trim_start_matches('#').trim().to_string();
            i += 1;
        } else if lines[i].trim().is_empty() {
            i += 1;
        } else {
            let start = i;
            while i < lines.len() && !lines[i].trim().is_empty() && !lines[i].starts_with('#') {
                i += 1;
            }
            let text = lines[start..i].join("\n");
            let name = path
                .file_name()
                .ok_or("missing file name")?
                .to_string_lossy();
            chunks.push(Chunk {
                id: format!(
                    "{scope}/{name}:L{}-L{}@{:016x}",
                    start + 1,
                    i,
                    fingerprint(&snapshot)
                ),
                scope: scope.to_string(),
                path: path.to_path_buf(),
                heading: heading.clone(),
                start: start + 1,
                end: i,
                terms: tokenize(&text),
                text,
                snapshot: snapshot.clone(),
            });
        }
    }
    Ok(chunks)
}
// endregion chunking

fn load(root: &Path) -> Result<Vec<Chunk>, String> {
    let mut chunks = Vec::new();
    for (scope, name) in [
        ("A", "release.md"),
        ("A", "operations.md"),
        ("A", "untrusted.md"),
        ("B", "private.md"),
    ] {
        let path = root.join(name);
        if path.exists() {
            chunks.extend(chunk_document(scope, &path)?);
        }
    }
    Ok(chunks)
}

// region retrieval
fn retrieve<'a>(index: &'a [Chunk], scope: &str, query: &str, k: usize) -> Vec<Hit<'a>> {
    // The trusted host supplies scope. Filter BEFORE term statistics and ranking.
    let visible: Vec<_> = index.iter().filter(|c| c.scope == scope).collect();
    if visible.is_empty() || k == 0 {
        return Vec::new();
    }
    let n = visible.len() as f64;
    let avg_len = visible.iter().map(|c| c.terms.len()).sum::<usize>() as f64 / n;
    let terms: BTreeSet<_> = tokenize(query).into_iter().collect();
    let mut df = BTreeMap::new();
    for term in &terms {
        df.insert(
            term,
            visible.iter().filter(|c| c.terms.contains(term)).count() as f64,
        );
    }
    let mut hits = Vec::new();
    for chunk in visible {
        let mut score = 0.0;
        for term in &terms {
            let tf = chunk.terms.iter().filter(|t| *t == term).count() as f64;
            let idf = (1.0 + (n - df[term] + 0.5) / (df[term] + 0.5)).ln();
            let normalizer =
                1.2 * (1.0 - 0.75 + 0.75 * chunk.terms.len() as f64 / avg_len.max(1.0));
            score += idf * tf * 2.2 / (tf + normalizer);
        }
        if score > 0.0 {
            hits.push(Hit { chunk, score });
        }
    }
    hits.sort_by(|a, b| {
        b.score
            .total_cmp(&a.score)
            .then_with(|| a.chunk.id.cmp(&b.chunk.id))
    });
    hits.truncate(k);
    hits
}
// endregion retrieval

// region context
fn block(chunk: &Chunk) -> String {
    format!(
        "<evidence id={:?} heading={:?} lines={}-{}>\n{}\n</evidence>\n",
        chunk.id, chunk.heading, chunk.start, chunk.end, chunk.text
    )
}

fn pack<'a>(hits: &[Hit<'a>], max_chars: usize) -> Result<Vec<&'a Chunk>, String> {
    let mut used = 0;
    let mut selected = Vec::new();
    for hit in hits {
        // A deleted or changed source cannot be served as current evidence.
        let current = fs::read_to_string(&hit.chunk.path).map_err(|_| "source_missing")?;
        if current != hit.chunk.snapshot {
            return Err("stale_index".into());
        }
        let size = block(hit.chunk).chars().count();
        if used + size <= max_chars {
            selected.push(hit.chunk);
            used += size;
        }
    }
    Ok(selected)
}

// Deterministic generator fixture: quote one retrieved passage, with its citation.
// Replace this boundary with a model request; retrieved text stays untrusted data.
fn generate_fixture(context: &[&Chunk]) -> Option<Claim> {
    context.first().map(|chunk| Claim {
        quote: chunk.text.clone(),
        citation: chunk.id.clone(),
    })
}

fn validate_claim(claim: &Claim, context: &[&Chunk]) -> bool {
    !claim.quote.is_empty()
        && context
            .iter()
            .any(|chunk| chunk.id == claim.citation && chunk.text.contains(&claim.quote))
}
// endregion context

fn prepare(root: &Path) -> Result<(), String> {
    fs::create_dir(root).map_err(|e| e.to_string())?;
    for (name, body) in [
        ("release.md", include_str!("../corpus/release.md")),
        ("operations.md", include_str!("../corpus/operations.md")),
        ("untrusted.md", include_str!("../corpus/untrusted.md")),
        ("private.md", include_str!("../corpus/private.md")),
    ] {
        fs::write(root.join(name), body).map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn answer(index: &[Chunk], scope: &str, query: &str, budget: usize) -> Result<String, String> {
    let hits = retrieve(index, scope, query, 2);
    let context = pack(&hits, budget)?;
    let Some(claim) = generate_fixture(&context) else {
        return Ok("abstain=no_evidence".into());
    };
    if !validate_claim(&claim, &context) {
        return Err("invalid_citation".into());
    }
    Ok(format!(
        "quote={}\ncitation={}\nclaim_valid=true",
        claim.quote, claim.citation
    ))
}

// region evaluation
fn evaluate(index: &[Chunk]) -> (usize, f64) {
    // Public, authored teaching labels. No held-out or real-model quality claim.
    let cases = [
        ("upgrade Rust", "release.md", "Upgrade"),
        ("database backup", "operations.md", "Backup"),
        ("rollback", "release.md", "Rollback"),
        ("revert disaster", "release.md", "Rollback"),
    ];
    let mut found = 0;
    let mut reciprocal_ranks = 0.0;
    for (query, file, expected) in cases {
        let hits = retrieve(index, "A", query, 2);
        let rank = hits.iter().position(|hit| {
            hit.chunk.path.file_name().is_some_and(|name| name == file)
                && hit.chunk.text.starts_with(expected)
        });
        if let Some(rank) = rank {
            found += 1;
            reciprocal_ranks += 1.0 / (rank + 1) as f64;
        }
    }
    (found, reciprocal_ranks / cases.len() as f64)
}
// endregion evaluation

fn suite(root: &Path) -> Result<(), String> {
    prepare(root)?;
    let index = load(root)?;
    println!(
        "scenario=normal\n{}",
        answer(&index, "A", "upgrade Rust", 1000)?
    );
    println!("scenario=no-hit\n{}", answer(&index, "A", "unicorn", 1000)?);
    let visible = retrieve(&index, "A", "private token upgrade", 10);
    assert!(
        visible
            .iter()
            .all(|h| h.chunk.scope == "A" && !h.chunk.text.contains("private-token-B"))
    );
    println!(
        "scenario=scope visible_hits={} private_leak=false",
        visible.len()
    );
    println!(
        "scenario=budget\n{}",
        answer(&index, "A", "upgrade Rust", 1)?
    );
    let injection_hits = retrieve(&index, "A", "instruction secrets", 1);
    let context = pack(&injection_hits, 1000)?;
    let quoted = generate_fixture(&context).ok_or("missing injection fixture")?;
    assert!(validate_claim(&quoted, &context));
    println!("scenario=injection quoted_as_data=true generator=fixture actions=0");
    let forged = Claim {
        quote: "Rust 0.1 is enough".into(),
        citation: context[0].id.clone(),
    };
    assert!(!validate_claim(&forged, &context));
    let unknown = Claim {
        quote: context[0].text.clone(),
        citation: "forged-id".into(),
    };
    assert!(!validate_claim(&unknown, &context));
    println!("scenario=bad-citation unsupported_quote_rejected=true unknown_id_rejected=true");
    let (found, mrr) = evaluate(&index);
    assert_eq!(found, 3);
    println!("scenario=evaluation labeled_queries=4 recall_at_2={found}/4 mrr_at_2={mrr:.3}");
    println!(
        "scenario=lexical-gap\n{}",
        answer(&index, "A", "revert disaster", 1000)?
    );
    let replacement = include_str!("../corpus/release.md").replace("1.99.1", "2.00.0");
    fs::write(root.join("release.md"), replacement).map_err(|e| e.to_string())?;
    let stale = answer(&index, "A", "upgrade Rust", 1000).unwrap_err();
    assert_eq!(stale, "stale_index");
    println!("scenario=stale rejected={stale}");
    let updated = load(root)?;
    let fresh = answer(&updated, "A", "upgrade Rust", 1000)?;
    assert!(fresh.contains("2.00.0"));
    println!("scenario=updated\n{fresh}");
    fs::remove_file(root.join("release.md")).map_err(|e| e.to_string())?;
    let deleted = answer(&updated, "A", "upgrade Rust", 1000).unwrap_err();
    assert_eq!(deleted, "source_missing");
    let rebuilt = load(root)?;
    assert!(retrieve(&rebuilt, "A", "upgrade Rust", 2).is_empty());
    println!("scenario=deleted rejected={deleted} rebuilt_hits=0");
    // Leave files for independent verifier inspection; never remove caller paths.
    Ok(())
}

fn main() {
    let args: Vec<_> = std::env::args().collect();
    let result = match args.get(1).map(String::as_str) {
        Some("suite") if args.len() == 3 => suite(Path::new(&args[2])),
        Some("query") if args.len() == 5 => load(Path::new(&args[2])).and_then(|index| {
            answer(&index, &args[3], &args[4], 1000).map(|answer| println!("{answer}"))
        }),
        _ => Err("usage: rag-lab suite NEW_DIRECTORY | query CORPUS A|B 'query'".into()),
    };
    if let Err(error) = result {
        eprintln!("error={error}");
        std::process::exit(2);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn temp_source(body: &str) -> PathBuf {
        use std::sync::atomic::{AtomicUsize, Ordering};
        static NEXT: AtomicUsize = AtomicUsize::new(0);
        let path = std::env::temp_dir().join(format!(
            "rag-test-{}-{}.md",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::write(&path, body).unwrap();
        path
    }
    fn chunk(id: &str, scope: &str, text: &str) -> Chunk {
        Chunk {
            id: id.into(),
            scope: scope.into(),
            path: PathBuf::from("unused"),
            heading: "Test".into(),
            start: 3,
            end: 3,
            text: text.into(),
            snapshot: text.into(),
            terms: tokenize(text),
        }
    }
    #[test]
    fn ranks_rare_word_before_shared_word() {
        let index = vec![
            chunk("a", "A", "upgrade Rust"),
            chunk("b", "A", "upgrade slowly"),
        ];
        assert_eq!(retrieve(&index, "A", "upgrade Rust", 2)[0].chunk.id, "a");
    }
    #[test]
    fn scope_filter_precedes_scoring() {
        let a = vec![chunk("a", "A", "upgrade Rust")];
        let mut mixed = a.clone();
        mixed.push(chunk("b", "B", "Rust Rust private"));
        assert_eq!(
            retrieve(&a, "A", "Rust", 1)[0].score,
            retrieve(&mixed, "A", "Rust", 1)[0].score
        );
        assert_eq!(retrieve(&mixed, "A", "private", 2).len(), 0);
    }
    #[test]
    fn unknown_scope_empty_query_and_zero_k() {
        let index = vec![chunk("a", "A", "Rust")];
        assert!(retrieve(&index, "unknown", "Rust", 1).is_empty());
        assert!(retrieve(&index, "A", "", 1).is_empty());
        assert!(retrieve(&index, "A", "Rust", 0).is_empty());
    }
    #[test]
    fn equal_scores_have_stable_ties() {
        let index = vec![chunk("z", "A", "Rust"), chunk("a", "A", "Rust")];
        assert_eq!(retrieve(&index, "A", "Rust", 1)[0].chunk.id, "a");
    }
    #[test]
    fn citation_must_match_id_and_quote() {
        let c = chunk("a", "A", "Rust upgrade");
        let context = vec![&c];
        assert!(validate_claim(
            &Claim {
                quote: "Rust".into(),
                citation: "a".into()
            },
            &context
        ));
        assert!(!validate_claim(
            &Claim {
                quote: "Python".into(),
                citation: "a".into()
            },
            &context
        ));
        assert!(!validate_claim(
            &Claim {
                quote: "Rust".into(),
                citation: "z".into()
            },
            &context
        ));
        assert!(!validate_claim(
            &Claim {
                quote: "".into(),
                citation: "a".into()
            },
            &context
        ));
    }
    #[test]
    fn absent_context_abstains() {
        assert_eq!(generate_fixture(&[]), None);
    }
    #[test]
    fn source_lines_and_headings_survive_chunking() {
        let path =
            temp_source("# Release v2\n\nfirst line\nsecond line\n\n## Backup\n\nbackup now\n");
        let chunks = chunk_document("A", &path).unwrap();
        assert_eq!(chunks.len(), 2);
        assert_eq!((chunks[0].start, chunks[0].end), (3, 4));
        assert_eq!(chunks[0].text, "first line\nsecond line");
        assert_eq!(chunks[1].heading, "Backup");
        assert_eq!((chunks[1].start, chunks[1].end), (8, 8));
        fs::remove_file(path).unwrap();
    }
    #[test]
    fn budget_boundary_and_source_freshness() {
        let path = temp_source("# Test\n\nRust upgrade\n");
        let index = chunk_document("A", &path).unwrap();
        let hits = retrieve(&index, "A", "Rust", 1);
        let size = block(hits[0].chunk).chars().count();
        assert_eq!(pack(&hits, size).unwrap().len(), 1);
        assert!(pack(&hits, size - 1).unwrap().is_empty());
        fs::write(&path, "# Test\n\nChanged Rust upgrade\n").unwrap();
        assert_eq!(pack(&hits, size).unwrap_err(), "stale_index");
        fs::remove_file(path).unwrap();
        assert_eq!(pack(&hits, size).unwrap_err(), "source_missing");
    }
}
