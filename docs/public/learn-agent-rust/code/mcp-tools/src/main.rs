mod adapter;
mod connection;
mod lab;
mod schema;
mod server;
#[cfg(test)]
mod tests;

type AnyError = Box<dyn std::error::Error + Send + Sync>;

#[tokio::main]
async fn main() -> Result<(), AnyError> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.len() == 3 && args[0] == "server" {
        return server::run(args[1].clone().into(), args[2].clone()).await;
    }
    if args.len() != 2 {
        return Err("usage: learn-agent-r19 SCENARIO NEW_DIRECTORY".into());
    }
    let evidence = lab::run(&args[0], std::path::Path::new(&args[1])).await?;
    println!("{}", serde_json::to_string_pretty(&evidence)?);
    Ok(())
}
