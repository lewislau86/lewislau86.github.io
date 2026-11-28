//! K01（ADK-Rust 3.0 / adk-rag）：检索、证据与回答。
//!
//!   rag-lab suite NEW_DIRECTORY        在新目录里建资料，按顺序跑完全部场景（目录保留供检查）
//!   rag-lab query CORPUS A|B 'query'    读取已有资料目录，回答一次
//!
//! 切块、词袋 embedding、按范围的向量检索由 adk-rag 的 RagPipeline 执行（内存向量库，不联网）；
//! 来源时效、上下文预算和引用校验由宿主执行。生成器是“摘录第一条证据”的确定性夹具；
//! agent 场景用 ScriptedLlm 调用 RagTool，并用 CitationRequired 检查最终回答的引用。
mod trace;

use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
    sync::Arc,
};

use adk_agent::{
    LlmAgentBuilder,
    guardrails::{CitationRequired, GuardrailSet},
};
use adk_core::{Content, DeclarativePolicy, Part};
use adk_model::{ScriptedLlm, ScriptedResponse};
use adk_rag::{
    Chunk, Chunker, Document, EmbeddingProvider, InMemoryVectorStore, QueryOptions, RagConfig,
    RagPipeline, RagTool, Scope, SearchResult,
};
use adk_runner::Runner;
use adk_session::{CreateRequest, InMemorySessionService, SessionService};
use async_trait::async_trait;
use futures::StreamExt;
use serde_json::{Value, json};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

const COLLECTION: &str = "docs";
const FILES: [(&str, &str); 4] = [
    ("A", "release.md"),
    ("A", "operations.md"),
    ("A", "untrusted.md"),
    ("B", "private.md"),
];
/// 词袋向量的维数。太小会让不同的词落进同一维（见 collision 场景）；取质数，
/// 让哈希值的高位也参与取余。本章语料在这个维数下没有碰撞，由测试守住。
const DIMS: usize = 2003;
/// 相似度下限。adk-rag 默认是 0.0，会把零分结果也返回（见 zero-score 场景）。
const THRESHOLD: f32 = 0.05;

// region chunking
/// 按段落切块：每块记下所在标题和原文件里的起止行。
/// 块 ID 与来源 URI 都带行号，引用能直接指回原文。
struct ParagraphChunker;

impl Chunker for ParagraphChunker {
    fn chunk(&self, document: &Document) -> Vec<Chunk> {
        let lines: Vec<&str> = document.text.lines().collect();
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
                let span = format!("L{}-L{}", start + 1, i);
                let text = lines[start..i].join("\n");
                chunks.push(
                    Chunk::from_document(document, format!("{}:{span}", document.id), text)
                        .with_source_uri(format!("kb://{}#{span}", document.id))
                        .with_title(heading.clone())
                        .with_metadata("heading", heading.clone()),
                );
            }
        }
        chunks
    }
}
// endregion chunking

// region embedding
/// 只认英文单词和数字，统一小写：一个刻意很小的词法基线。
fn words(text: &str) -> impl Iterator<Item = String> + '_ {
    text.split(|c: char| !c.is_ascii_alphanumeric())
        .filter(|w| !w.is_empty())
        .map(str::to_ascii_lowercase)
}

fn fnv(text: &str) -> u64 {
    text.bytes().fold(0xcbf29ce484222325, |hash, byte| {
        (hash ^ u64::from(byte)).wrapping_mul(0x100000001b3)
    })
}

/// 词袋向量：每个词哈希到 `dims` 维中的一维，出现次数作为分量。
/// 两段文字共享的词越多、方向越接近，余弦相似度越高；它不懂同义词。
struct HashedWords {
    dims: usize,
}

impl HashedWords {
    fn vector<'a>(&self, words: impl Iterator<Item = &'a str>) -> Vec<f32> {
        let mut v = vec![0.0; self.dims];
        for word in words {
            v[(fnv(word) % self.dims as u64) as usize] += 1.0;
        }
        v
    }
}

#[async_trait]
impl EmbeddingProvider for HashedWords {
    async fn embed(&self, text: &str) -> adk_rag::Result<Vec<f32>> {
        let words: Vec<String> = words(text).collect();
        Ok(self.vector(words.iter().map(String::as_str)))
    }

    fn dimensions(&self) -> usize {
        self.dims
    }
}

/// 手写同义词表的替身：把 revert 当成 rollback。只用来演示“只换 embedder、其余不变”，
/// 它不是语义模型，换一个说法就又找不到了。
struct SynonymWords {
    inner: HashedWords,
}

#[async_trait]
impl EmbeddingProvider for SynonymWords {
    async fn embed(&self, text: &str) -> adk_rag::Result<Vec<f32>> {
        let words: Vec<String> = words(text)
            .map(|w| if w == "revert" { "rollback".into() } else { w })
            .collect();
        Ok(self.inner.vector(words.iter().map(String::as_str)))
    }

    fn dimensions(&self) -> usize {
        self.inner.dims
    }
}
// endregion embedding

// region index
/// 索引 = adk-rag 的管线（向量库里存块和向量）+ 宿主自己的来源清单（建索引时读到的完整原文）。
struct Index {
    pipeline: Arc<RagPipeline>,
    sources: BTreeMap<String, (PathBuf, String)>,
}

async fn build(root: &Path, embedder: Arc<dyn EmbeddingProvider>, threshold: f32) -> Result<Index> {
    let pipeline = RagPipeline::builder()
        .config(
            RagConfig::builder()
                .top_k(2)
                .similarity_threshold(threshold)
                .build()?,
        )
        .embedding_provider(embedder)
        .vector_store(Arc::new(InMemoryVectorStore::new()))
        .chunker(Arc::new(ParagraphChunker))
        .build()?;
    pipeline.create_collection(COLLECTION).await?;
    let mut index = Index {
        pipeline: Arc::new(pipeline),
        sources: BTreeMap::new(),
    };
    for (scope, name) in FILES {
        if root.join(name).exists() {
            refresh(&mut index, root, scope, name).await?;
        }
    }
    Ok(index)
}

/// 把一个文件的当前版本写进索引：存在就重新切块入库（框架替换这份文档的旧块），
/// 文件已被删除就删除这份文档的全部块。返回删除的块数（重新入库时为 0）。
async fn refresh(index: &mut Index, root: &Path, scope: &str, name: &str) -> Result<u64> {
    let id = format!("{scope}/{name}");
    let path = root.join(name);
    let rag = index.pipeline.scoped(Scope::new(scope)?);
    match fs::read_to_string(&path) {
        Ok(snapshot) => {
            let document = Document::new(&id, &snapshot)
                .with_metadata("fingerprint", format!("{:016x}", fnv(&snapshot)));
            rag.ingest(COLLECTION, &document).await?;
            index.sources.insert(id, (path, snapshot));
            Ok(0)
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            index.sources.remove(&id);
            Ok(rag.delete_document(COLLECTION, &id).await?)
        }
        Err(error) => Err(error.into()),
    }
}
// endregion index

// region retrieval
/// 范围由宿主给出，模型和用户输入都不能改；检索只在这个范围的块里打分。
async fn retrieve(index: &Index, scope: &str, query: &str, k: usize) -> Result<Vec<SearchResult>> {
    let options = QueryOptions::new().with_top_k(k);
    Ok(index
        .pipeline
        .scoped(Scope::new(scope)?)
        .query_with(COLLECTION, query, &options)
        .await?)
}
// endregion retrieval

// region context
#[derive(Debug, PartialEq)]
struct Claim {
    quote: String,
    citation: String,
}

fn block(hit: &SearchResult) -> String {
    format!(
        "<evidence id={:?} heading={:?}>\n{}\n</evidence>\n",
        hit.chunk.id,
        hit.chunk.metadata.get("heading").map_or("", String::as_str),
        hit.chunk.text
    )
}

/// 命中的块先核对来源仍是建索引时的版本，再按排名装进字符预算；装不下的跳过。
fn pack<'a>(
    index: &Index,
    hits: &'a [SearchResult],
    max_chars: usize,
) -> Result<Vec<&'a SearchResult>> {
    let mut used = 0;
    let mut selected = Vec::new();
    for hit in hits {
        let (path, snapshot) = index
            .sources
            .get(&hit.chunk.document_id)
            .ok_or("source_missing")?;
        let current = fs::read_to_string(path).map_err(|_| "source_missing")?;
        if &current != snapshot {
            return Err("stale_index".into());
        }
        let size = block(hit).chars().count();
        if used + size <= max_chars {
            selected.push(hit);
            used += size;
        }
    }
    Ok(selected)
}

/// 确定性生成夹具：摘录第一条证据并带上引用。换成模型时，检索到的文字仍是不可信数据。
fn generate_fixture(context: &[&SearchResult]) -> Option<Claim> {
    context.first().map(|hit| Claim {
        quote: hit.chunk.text.clone(),
        citation: hit.chunk.id.clone(),
    })
}

fn validate_claim(claim: &Claim, context: &[&SearchResult]) -> bool {
    !claim.quote.is_empty()
        && context
            .iter()
            .any(|hit| hit.chunk.id == claim.citation && hit.chunk.text.contains(&claim.quote))
}

async fn answer(index: &Index, scope: &str, query: &str, budget: usize) -> Result<String> {
    let hits = retrieve(index, scope, query, 2).await?;
    let context = pack(index, &hits, budget)?;
    let Some(claim) = generate_fixture(&context) else {
        return Ok("abstain=no_evidence".into());
    };
    if !validate_claim(&claim, &context) {
        return Err("invalid_citation".into());
    }
    let fingerprint = context[0].chunk.metadata.get("fingerprint").cloned();
    Ok(format!(
        "quote={}\ncitation={}@{}\nscore={:.3}\nclaim_valid=true",
        claim.quote,
        claim.citation,
        fingerprint.unwrap_or_default(),
        context[0].score
    ))
}
// endregion context

// region agent
/// 把检索交给 Agent：RagTool 只搜宿主固定的范围，检索结果记为本轮的来源；
/// CitationRequired 要求最终回答链接到至少一个本轮检索到的来源。
async fn agent_run(index: &Index, answer_text: &str) -> Result<Vec<String>> {
    let tool = RagTool::new(index.pipeline.clone(), COLLECTION).with_scope(Scope::new("A")?);
    let model = Arc::new(ScriptedLlm::new(
        "scripted",
        vec![
            ScriptedResponse::function_call("rag_search", json!({ "query": "upgrade Rust" })),
            ScriptedResponse::text(answer_text),
        ],
    ));
    let agent = LlmAgentBuilder::new("assistant")
        .instruction("先用 rag_search 检索，回答时用 [标题](来源) 链接引用检索到的来源。")
        .model(model)
        .tool(Arc::new(tool))
        .output_guardrails(GuardrailSet::new().with(CitationRequired::new()))
        .build()?;
    let sessions = Arc::new(InMemorySessionService::new());
    sessions
        .create(CreateRequest {
            app_name: "k01".into(),
            user_id: "reader".into(),
            session_id: Some("s1".into()),
            state: Default::default(),
        })
        .await?;
    let runner = Runner::builder()
        .app_name("k01")
        .agent(Arc::new(agent))
        .session_service(sessions)
        .tool_policy(Arc::new(
            DeclarativePolicy::builder().allow("rag_search").build(),
        ))
        .without_intra_compaction()
        .build()?;
    let question = Content::new("user").with_text("升级到 v2 要求哪个 Rust 版本？");
    let mut stream = runner.run_str("reader", "s1", question).await?;
    let mut lines = Vec::new();
    while let Some(event) = stream.next().await {
        let event = match event {
            Ok(event) => event,
            Err(error) => {
                lines.push(format!("[run] error   {}", error.code));
                break;
            }
        };
        let mut traced: Vec<String> = trace::event_lines(&event)
            .into_iter()
            .filter(|line| !line.contains("] result "))
            .collect();
        // “final” 标记留在这条事件的最后一行
        let final_mark = traced.pop_if(|line| line.ends_with("] final"));
        lines.extend(traced);
        for part in event
            .content()
            .map(|c| c.parts.as_slice())
            .unwrap_or_default()
        {
            if let Part::FunctionResponse {
                function_response, ..
            } = part
            {
                lines.push(format!(
                    "[{}] result  {}",
                    event.author,
                    hits_summary(&function_response.response)
                ));
            }
        }
        for source in &event.actions.grounding_sources {
            lines.push(format!("[{}] source  {}", event.author, source.uri));
        }
        if let Some(citations) = &event.llm_response.citation_metadata {
            for citation in &citations.citation_sources {
                lines.push(format!(
                    "[{}] cites   {}",
                    event.author,
                    citation.uri.as_deref().unwrap_or("-")
                ));
            }
        }
        lines.extend(final_mark);
    }
    Ok(lines)
}

/// 工具结果只列块 ID 和分数，正文太长不写进轨迹。
fn hits_summary(response: &Value) -> String {
    let hits: Vec<String> = response
        .as_array()
        .into_iter()
        .flatten()
        .map(|hit| {
            format!(
                "{} score={:.3}",
                hit["id"].as_str().unwrap_or("-"),
                hit["score"].as_f64().unwrap_or_default()
            )
        })
        .collect();
    format!("rag_search [{}]", hits.join(", "))
}
// endregion agent

// region evaluation
/// 公开的四道教学查询，每题一个标注相关块。不是隐藏测试集，不代表真实模型质量。
async fn evaluate(index: &Index) -> Result<(usize, f64)> {
    let cases = [
        ("upgrade Rust", "A/release.md:L3-L3"),
        ("database backup", "A/operations.md:L3-L3"),
        ("rollback", "A/release.md:L5-L5"),
        ("revert disaster", "A/release.md:L5-L5"),
    ];
    let mut found = 0;
    let mut reciprocal_ranks = 0.0;
    for (query, expected) in cases {
        let hits = retrieve(index, "A", query, 2).await?;
        let rank = hits.iter().position(|hit| hit.chunk.id == expected);
        if let Some(rank) = rank {
            found += 1;
            reciprocal_ranks += 1.0 / (rank + 1) as f64;
        }
    }
    Ok((found, reciprocal_ranks / cases.len() as f64))
}
// endregion evaluation

fn prepare(root: &Path) -> Result<()> {
    fs::create_dir(root)?;
    for (name, body) in [
        ("release.md", include_str!("../corpus/release.md")),
        ("operations.md", include_str!("../corpus/operations.md")),
        ("untrusted.md", include_str!("../corpus/untrusted.md")),
        ("private.md", include_str!("../corpus/private.md")),
    ] {
        fs::write(root.join(name), body)?;
    }
    Ok(())
}

fn lexical() -> Arc<dyn EmbeddingProvider> {
    Arc::new(HashedWords { dims: DIMS })
}

async fn suite(root: &Path) -> Result<()> {
    prepare(root)?;
    let mut index = build(root, lexical(), THRESHOLD).await?;
    println!(
        "scenario=normal\n{}",
        answer(&index, "A", "upgrade Rust", 1000).await?
    );
    println!(
        "scenario=no-hit\n{}",
        answer(&index, "A", "unicorn", 1000).await?
    );

    // 同样的资料、同样的 embedder，只把相似度下限改回框架默认的 0.0
    let loose = build(root, lexical(), 0.0).await?;
    let zero = retrieve(&loose, "A", "unicorn", 2).await?;
    println!(
        "scenario=zero-score threshold=0.0 hits={} scores=[{}] first={}\n{}",
        zero.len(),
        zero.iter()
            .map(|hit| format!("{:.3}", hit.score))
            .collect::<Vec<_>>()
            .join(","),
        zero.first().map_or("-", |hit| hit.chunk.id.as_str()),
        answer(&loose, "A", "unicorn", 1000).await?
    );

    let visible = retrieve(&index, "A", "private token upgrade", 10).await?;
    assert!(visible.iter().all(
        |h| h.chunk.document_id.starts_with("A/") && !h.chunk.text.contains("private-token-B")
    ));
    let other = retrieve(&index, "B", "private token upgrade", 10).await?;
    println!(
        "scenario=scope visible_hits_a={} private_leak=false visible_hits_b={} b_documents=[{}]",
        visible.len(),
        other.len(),
        other
            .iter()
            .map(|hit| hit.chunk.document_id.as_str())
            .collect::<Vec<_>>()
            .join(",")
    );
    println!(
        "scenario=budget\n{}",
        answer(&index, "A", "upgrade Rust", 1).await?
    );

    let injection_hits = retrieve(&index, "A", "instruction secrets", 1).await?;
    let context = pack(&index, &injection_hits, 1000)?;
    let quoted = generate_fixture(&context).ok_or("missing injection fixture")?;
    assert!(validate_claim(&quoted, &context));
    println!(
        "scenario=injection cited={} quoted_as_data=true generator=fixture actions=0",
        quoted.citation
    );
    let forged = Claim {
        quote: "Rust 0.1 is enough".into(),
        citation: context[0].chunk.id.clone(),
    };
    assert!(!validate_claim(&forged, &context));
    let unknown = Claim {
        quote: context[0].chunk.text.clone(),
        citation: "forged-id".into(),
    };
    assert!(!validate_claim(&unknown, &context));
    println!("scenario=bad-citation unsupported_quote_rejected=true unknown_id_rejected=true");

    let (found, mrr) = evaluate(&index).await?;
    println!(
        "scenario=evaluation embedder=hashed-words labeled_queries=4 recall_at_2={found}/4 mrr_at_2={mrr:.3}"
    );
    println!(
        "scenario=lexical-gap\n{}",
        answer(&index, "A", "revert disaster", 1000).await?
    );

    // 只换 embedder：语料、切块、范围、阈值、查询和标签都不变
    let synonyms = build(
        root,
        Arc::new(SynonymWords {
            inner: HashedWords { dims: DIMS },
        }),
        THRESHOLD,
    )
    .await?;
    let (found, mrr) = evaluate(&synonyms).await?;
    println!(
        "scenario=swap-embedder embedder=synonym-table recall_at_2={found}/4 mrr_at_2={mrr:.3}\n{}",
        answer(&synonyms, "A", "revert disaster", 1000).await?
    );

    let tiny = build(root, Arc::new(HashedWords { dims: 4 }), THRESHOLD).await?;
    let collided = retrieve(&tiny, "A", "unicorn", 1).await?;
    println!(
        "scenario=collision dims=4 query=unicorn hits={} first={} score={:.3}",
        collided.len(),
        collided.first().map_or("-", |hit| hit.chunk.id.as_str()),
        collided.first().map_or(0.0, |hit| hit.score)
    );

    let replacement = include_str!("../corpus/release.md").replace("1.99.1", "2.00.0");
    fs::write(root.join("release.md"), replacement)?;
    let stale = answer(&index, "A", "upgrade Rust", 1000)
        .await
        .unwrap_err()
        .to_string();
    assert_eq!(stale, "stale_index");
    println!("scenario=stale rejected={stale}");
    refresh(&mut index, root, "A", "release.md").await?;
    let chunks_in_a = index
        .pipeline
        .scoped(Scope::new("A")?)
        .count(COLLECTION)
        .await?;
    println!(
        "scenario=updated chunks_in_a={chunks_in_a}\n{}",
        answer(&index, "A", "upgrade Rust", 1000).await?
    );

    fs::remove_file(root.join("release.md"))?;
    let deleted = answer(&index, "A", "upgrade Rust", 1000)
        .await
        .unwrap_err()
        .to_string();
    assert_eq!(deleted, "source_missing");
    let removed = refresh(&mut index, root, "A", "release.md").await?;
    let rebuilt = retrieve(&index, "A", "upgrade Rust", 2).await?;
    println!(
        "scenario=deleted rejected={deleted} removed_chunks={removed} rebuilt_hits={}",
        rebuilt
            .iter()
            .filter(|hit| hit.chunk.document_id == "A/release.md")
            .count()
    );

    // Agent 场景用一份新的资料，避免受前面改动和删除的影响
    let fresh_root = root.join("agent");
    prepare(&fresh_root)?;
    let fresh = build(&fresh_root, lexical(), THRESHOLD).await?;
    println!("scenario=agent-cited");
    for line in agent_run(
        &fresh,
        "升级到 v2 需要 Rust 1.99.1（[Release v2](kb://A/release.md#L3-L3)）。",
    )
    .await?
    {
        println!("{line}");
    }
    println!("scenario=agent-uncited");
    for line in agent_run(&fresh, "升级到 v2 需要 Rust 1.99.1。").await? {
        println!("{line}");
    }
    // 资料留给验证脚本检查；不删除调用者给的路径
    Ok(())
}

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let args: Vec<_> = std::env::args().collect();
    let result = match args.get(1).map(String::as_str) {
        Some("suite") if args.len() == 3 => suite(Path::new(&args[2])).await,
        Some("query") if args.len() == 5 && !Path::new(&args[2]).is_dir() => {
            Err(format!("corpus directory not found: {}", args[2]).into())
        }
        Some("query") if args.len() == 5 => {
            match build(Path::new(&args[2]), lexical(), THRESHOLD).await {
                Ok(index) => answer(&index, &args[3], &args[4], 1000)
                    .await
                    .map(|text| println!("{text}")),
                Err(error) => Err(error),
            }
        }
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

    fn corpus() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("corpus")
    }

    #[test]
    fn source_lines_and_headings_survive_chunking() {
        let document = Document::new(
            "A/test.md",
            "# Release v2\n\nfirst line\nsecond line\n\n## Backup\n\nbackup now\n",
        );
        let chunks = ParagraphChunker.chunk(&document);
        assert_eq!(chunks.len(), 2);
        assert_eq!(chunks[0].id, "A/test.md:L3-L4");
        assert_eq!(chunks[0].text, "first line\nsecond line");
        assert_eq!(chunks[1].metadata["heading"], "Backup");
        assert_eq!(
            chunks[1].source_uri.as_deref(),
            Some("kb://A/test.md#L8-L8")
        );
    }

    #[test]
    fn corpus_words_do_not_collide_at_the_chosen_dimension() {
        let mut slots = BTreeMap::new();
        for (_, name) in FILES {
            let text = fs::read_to_string(corpus().join(name)).unwrap();
            for word in words(&text).chain(words(
                "unicorn revert disaster instruction secrets database backup rollback",
            )) {
                let slot = fnv(&word) % DIMS as u64;
                let previous = slots.insert(slot, word.clone());
                assert!(previous.is_none_or(|p| p == word), "{word} collides");
            }
        }
    }

    #[tokio::test]
    async fn ranks_the_release_note_first_and_keeps_scopes_apart() {
        let index = build(&corpus(), lexical(), THRESHOLD).await.unwrap();
        let hits = retrieve(&index, "A", "upgrade Rust", 2).await.unwrap();
        assert_eq!(hits[0].chunk.id, "A/release.md:L3-L3");
        assert!(hits.iter().all(|h| h.chunk.document_id.starts_with("A/")));
        let b = retrieve(&index, "B", "upgrade", 10).await.unwrap();
        assert!(!b.is_empty());
        assert!(b.iter().all(|h| h.chunk.document_id == "B/private.md"));
        assert!(
            retrieve(&index, "unknown", "upgrade", 2)
                .await
                .unwrap()
                .is_empty()
        );
    }

    #[tokio::test]
    async fn a_chunks_score_does_not_depend_on_other_documents() {
        let root = std::env::temp_dir().join(format!("k01-alone-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        prepare(&root).unwrap();
        let full = build(&root, lexical(), THRESHOLD).await.unwrap();
        for name in ["operations.md", "untrusted.md", "private.md"] {
            fs::remove_file(root.join(name)).unwrap();
        }
        let alone = build(&root, lexical(), THRESHOLD).await.unwrap();
        let score = |hits: Vec<SearchResult>| hits[0].score;
        assert_eq!(
            score(retrieve(&full, "A", "upgrade Rust", 1).await.unwrap()),
            score(retrieve(&alone, "A", "upgrade Rust", 1).await.unwrap())
        );
        fs::remove_dir_all(&root).unwrap();
    }

    #[tokio::test]
    async fn the_threshold_drops_zero_scores_and_empty_queries() {
        let strict = build(&corpus(), lexical(), THRESHOLD).await.unwrap();
        assert!(
            retrieve(&strict, "A", "unicorn", 2)
                .await
                .unwrap()
                .is_empty()
        );
        assert!(retrieve(&strict, "A", "", 2).await.unwrap().is_empty());
        let loose = build(&corpus(), lexical(), 0.0).await.unwrap();
        let hits = retrieve(&loose, "A", "unicorn", 2).await.unwrap();
        assert_eq!(hits.len(), 2);
        assert!(hits.iter().all(|h| h.score == 0.0));
    }

    #[tokio::test]
    async fn citation_must_match_id_and_quote() {
        let index = build(&corpus(), lexical(), THRESHOLD).await.unwrap();
        let hits = retrieve(&index, "A", "upgrade Rust", 1).await.unwrap();
        let context: Vec<&SearchResult> = hits.iter().collect();
        let id = hits[0].chunk.id.clone();
        let claim = |quote: &str, citation: &str| Claim {
            quote: quote.into(),
            citation: citation.into(),
        };
        assert!(validate_claim(&claim("Rust 1.99.1", &id), &context));
        assert!(!validate_claim(&claim("Python", &id), &context));
        assert!(!validate_claim(&claim("Rust", "z"), &context));
        assert!(!validate_claim(&claim("", &id), &context));
        assert_eq!(generate_fixture(&[]), None);
    }

    #[tokio::test]
    async fn budget_boundary_and_source_freshness() {
        let root = std::env::temp_dir().join(format!("k01-test-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        prepare(&root).unwrap();
        let index = build(&root, lexical(), THRESHOLD).await.unwrap();
        let hits = retrieve(&index, "A", "upgrade Rust", 1).await.unwrap();
        let size = block(&hits[0]).chars().count();
        assert_eq!(pack(&index, &hits, size).unwrap().len(), 1);
        assert!(pack(&index, &hits, size - 1).unwrap().is_empty());
        fs::write(root.join("release.md"), "# Release v2\n\nChanged\n").unwrap();
        assert_eq!(
            pack(&index, &hits, size).unwrap_err().to_string(),
            "stale_index"
        );
        fs::remove_file(root.join("release.md")).unwrap();
        assert_eq!(
            pack(&index, &hits, size).unwrap_err().to_string(),
            "source_missing"
        );
        fs::remove_dir_all(&root).unwrap();
    }

    #[tokio::test]
    async fn reingesting_replaces_a_documents_chunks() {
        let root = std::env::temp_dir().join(format!("k01-reingest-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        prepare(&root).unwrap();
        let mut index = build(&root, lexical(), THRESHOLD).await.unwrap();
        let rag = |index: &Index| index.pipeline.clone();
        let before = rag(&index)
            .scoped(Scope::new("A").unwrap())
            .count(COLLECTION)
            .await
            .unwrap();
        fs::write(
            root.join("release.md"),
            "# Release v2\n\nOnly one paragraph now.\n",
        )
        .unwrap();
        refresh(&mut index, &root, "A", "release.md").await.unwrap();
        let after = rag(&index)
            .scoped(Scope::new("A").unwrap())
            .count(COLLECTION)
            .await
            .unwrap();
        assert_eq!(
            before - after,
            1,
            "the dropped paragraph's chunk is removed"
        );
        let hits = retrieve(&index, "A", "paragraph", 2).await.unwrap();
        assert_eq!(hits[0].chunk.text, "Only one paragraph now.");
        let old = retrieve(&index, "A", "rollback", 2).await.unwrap();
        assert!(old.iter().all(|h| h.chunk.document_id != "A/release.md"));
        fs::remove_dir_all(&root).unwrap();
    }

    #[tokio::test]
    async fn an_answer_without_a_retrieved_link_is_blocked() {
        let index = build(&corpus(), lexical(), THRESHOLD).await.unwrap();
        let cited = agent_run(&index, "Rust 1.99.1 ([v2](kb://A/release.md#L3-L3)).")
            .await
            .unwrap();
        assert!(
            cited
                .iter()
                .any(|l| l.contains("cites   kb://A/release.md#L3-L3"))
        );
        let uncited = agent_run(&index, "Rust 1.99.1.").await.unwrap();
        assert!(
            uncited
                .iter()
                .any(|l| l.ends_with("error   guardrail.output_blocked"))
        );
        let elsewhere = agent_run(&index, "Rust 1.99.1 ([v2](kb://A/release.md)).")
            .await
            .unwrap();
        assert!(
            elsewhere
                .iter()
                .any(|l| l.ends_with("error   guardrail.output_blocked"))
        );
    }
}
