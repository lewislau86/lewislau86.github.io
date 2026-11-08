use crate::AnyError;
use rmcp::{RoleClient, ServiceExt, model::*, service::RunningService};
use serde_json::{Value, json};
use std::{
    path::Path,
    process::Stdio,
    sync::{Arc, Mutex},
    time::Duration,
};
use tokio::{
    io::{AsyncBufReadExt, AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt, BufReader},
    process::{Child, Command},
    task::JoinHandle,
};

pub const REQUEST_MS: u64 = 250;
pub const START_MS: u64 = 2000;
pub type Wire = Arc<Mutex<Vec<Value>>>;

// The relay bounds a frame before handing it to the SDK decoder.
async fn relay<R, W>(reader: R, mut writer: W, label: String, direction: &'static str, wire: Wire)
where
    R: AsyncRead + Unpin,
    W: AsyncWrite + Unpin,
{
    let mut reader = BufReader::new(reader);
    loop {
        let mut bytes = Vec::new();
        let read = (&mut reader)
            .take(65537)
            .read_until(b'\n', &mut bytes)
            .await;
        if !matches!(read, Ok(n) if n > 0) {
            break;
        }
        if bytes.len() > 65536 {
            break;
        }
        let message = match serde_json::from_slice::<Value>(&bytes) {
            Ok(value) => value,
            Err(_) => {
                wire.lock()
                    .unwrap()
                    .push(json!({"server":label,"direction":direction,"invalid_frame":true}));
                break;
            }
        };
        {
            let mut events = wire.lock().unwrap();
            if events.len() >= 128 {
                break;
            }
            events.push(json!({"server":label,"direction":direction,"message":message}));
        }
        if writer.write_all(&bytes).await.is_err() || writer.flush().await.is_err() {
            break;
        }
    }
    let _ = writer.shutdown().await;
}

pub struct Connection {
    pub service: Option<RunningService<RoleClient, ClientConfig>>,
    pub usable: bool,
    pub startup: &'static str,
    pub pid: u32,
    child: Child,
    relays: Vec<JoinHandle<()>>,
}
impl Connection {
    // region connect
    pub async fn spawn(root: &Path, mode: &str, label: &str, wire: Wire) -> Result<Self, AnyError> {
        let executable = std::env::current_exe()?.canonicalize()?;
        let diagnostic = std::fs::File::create(root.join("stderr.txt"))?;
        let mut child = Command::new(executable)
            .arg("server")
            .arg(root)
            .arg(mode)
            .env_clear()
            .current_dir(root)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::from(diagnostic))
            .kill_on_drop(true)
            .spawn()?;
        let stdin = child.stdin.take().ok_or("missing child stdin")?;
        let stdout = child.stdout.take().ok_or("missing child stdout")?;
        let (sdk_output, to_child) = tokio::io::duplex(8192);
        let (from_child, sdk_input) = tokio::io::duplex(8192);
        let relays = vec![
            tokio::spawn(relay(
                to_child,
                stdin,
                label.into(),
                "client_to_server",
                wire.clone(),
            )),
            tokio::spawn(relay(
                stdout,
                from_child,
                label.into(),
                "server_to_client",
                wire,
            )),
        ];
        let pid = child.id().ok_or("missing child pid")?;
        let mut connection = Self {
            service: None,
            usable: false,
            startup: "handshake_failed",
            pid,
            child,
            relays,
        };
        let config = ClientConfig::new(
            ClientCapabilities::default(),
            Implementation::new("r19-client", "0.1.0"),
        )
        .with_protocol_version(ProtocolVersion::V_2025_11_25);
        match tokio::time::timeout(
            Duration::from_millis(START_MS),
            config.serve((sdk_input, sdk_output)),
        )
        .await
        {
            Ok(Ok(service)) => {
                connection.usable = service.peer_info().is_some_and(|info| {
                    info.protocol_version == ProtocolVersion::V_2025_11_25
                        && info.capabilities.tools.is_some()
                });
                connection.startup = if connection.usable {
                    "ready"
                } else {
                    "capability_or_version"
                };
                connection.service = Some(service);
            }
            Ok(Err(_)) => {}
            Err(_) => connection.startup = "startup_timeout",
        }
        Ok(connection)
    }
    // endregion connect

    // region shutdown
    pub async fn close(&mut self) -> Result<Value, AnyError> {
        self.usable = false;
        if let Some(service) = self.service.as_mut() {
            // Keep the same close future alive across the grace boundary.
            let closing = service.close();
            tokio::pin!(closing);
            if tokio::time::timeout(Duration::from_secs(1), &mut closing)
                .await
                .is_err()
            {
                let _ = self.child.start_kill();
                tokio::time::timeout(Duration::from_secs(2), closing).await??;
            }
        }
        let mut forced = false;
        let status = match tokio::time::timeout(Duration::from_secs(1), self.child.wait()).await {
            Ok(result) => result?,
            Err(_) => {
                forced = true;
                self.child.kill().await?;
                self.child.wait().await?
            }
        };
        for relay in self.relays.drain(..) {
            relay.abort();
            let _ = relay.await;
        }
        Ok(json!({"pid":self.pid,"reaped":true,"forced":forced,"exit_code":status.code()}))
    }
    // endregion shutdown
}
