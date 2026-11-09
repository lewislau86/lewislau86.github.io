mod agent;
mod provider;
#[cfg(test)]
mod tests;
use serde_json::{Value, json};
use std::{
    fs,
    path::{Path, PathBuf},
    time::Instant,
};
type Error = Box<dyn std::error::Error + Send + Sync>;

#[tokio::main]
async fn main() -> Result<(), Error> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    let (live,endpoint,model,token,case_path,case_id,dest)=match args.as_slice() {
        [mode,endpoint,cases,id,dest] if mode=="fixture"=>(false,endpoint.clone(),"fixture-v1".into(),"fixture-secret".into(),cases,id,dest),
        [mode,cases,id,dest] if mode=="live"=>(true,"https://api.deepseek.com/chat/completions".into(),
            std::env::var("P03_MODEL").map_err(|_|"set P03_MODEL explicitly")?,
            std::env::var("DEEPSEEK_API_KEY").map_err(|_|"set DEEPSEEK_API_KEY locally")?,cases,id,dest),
        _=>return Err("usage: learn-agent-p03 fixture ENDPOINT CASES_JSON CASE_ID NEW_DIR | live CASES_JSON CASE_ID NEW_DIR".into()),
    };
    let cases: Value = serde_json::from_slice(&fs::read(case_path)?)?;
    let case = cases["cases"]
        .as_array()
        .ok_or("cases")?
        .iter()
        .find(|c| c["id"] == *case_id)
        .ok_or("case_id")?;
    let model = provider::HttpModel::new(endpoint, token, model, live)
        .map_err(|_| "endpoint/model rejected")?;
    fs::create_dir(dest)?; // Never overwrite an earlier run.
    let root = fs::canonicalize(Path::new(dest))?;
    if let Some(readme) = case["readme"].as_str() {
        fs::write(root.join("README.md"), readme)?;
    }
    let telemetry = model.telemetry.clone();
    let started = Instant::now();
    let (state, nodes) = agent::run(model.clone(), PathBuf::from(&root)).await?;
    let elapsed = started.elapsed().as_secs_f64() * 1000.0;
    let book = telemetry.lock().unwrap();
    let exchanges = book.exchanges.clone();
    let adapter_ok = book.error.is_none() && exchanges.iter().all(|e| e["error"].is_null());
    let usage_known =
        exchanges.len() == state.attempts && exchanges.iter().all(|e| e["usage"].is_object());
    let usage = if usage_known {
        let input = exchanges.iter().try_fold(0_u64, |sum, e| {
            sum.checked_add(e["usage"]["prompt_tokens"].as_u64()?)
        });
        let output = exchanges.iter().try_fold(0_u64, |sum, e| {
            sum.checked_add(e["usage"]["completion_tokens"].as_u64()?)
        });
        match (input, output) {
            (Some(input), Some(output)) => {
                json!({"prompt_tokens":input,"completion_tokens":output})
            }
            _ => Value::Null,
        }
    } else {
        Value::Null
    };
    let report = json!({"mode":if live{"live"}else{"fixture"},"case_id":case_id,"requested_model":model.model,
        "adapter_ok":adapter_ok,"grade":agent::grade(&state,&case["expected"]),"state":state,"graph_nodes":nodes,
        "exchanges":exchanges,"usage":usage,"cost_usd":null,"cost_reason":if live {"No dated price schedule supplied; provider bill not reconciled"}else{"Fixture usage is synthetic, never billable"},
        "usage_origin":if live {"provider_reported"}else{"fixture_synthetic"},
        "elapsed_ms":elapsed,"live_status":if live{"executed"}else{"not_run"}});
    let output = serde_json::to_string_pretty(&report)?;
    fs::write(root.join("run.json"), &output)?;
    println!("{output}");
    Ok(())
}
