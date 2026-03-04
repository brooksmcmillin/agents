mod executor;
mod oauth;
mod relay;
mod token_store;

use clap::Parser;
use relay::RelayError;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use tokio::signal;
use tokio::sync::Notify;

#[derive(Parser)]
#[command(name = "remote-agent", about = "Remote shell agent via MCP relay")]
struct Cli {
    /// Agent name (default: hostname)
    #[arg(long)]
    name: Option<String>,

    /// Relay REST API base URL
    #[arg(
        long,
        default_value = "https://mcp-relay.brooksmcmillin.com/api"
    )]
    relay_url: String,

    /// OAuth discovery URL
    #[arg(long, default_value = "https://mcp-relay.brooksmcmillin.com")]
    auth_url: String,

    /// Token storage path
    #[arg(long)]
    token_file: Option<PathBuf>,

    /// Shell to use for command execution
    #[arg(long, default_value = "/bin/sh")]
    shell: String,

    /// Poll interval in seconds
    #[arg(long, default_value_t = 3)]
    poll_interval: u64,
}

fn default_token_path() -> PathBuf {
    dirs::home_dir()
        .expect("Cannot determine home directory")
        .join(".remote-agent")
        .join("token.json")
}

fn get_hostname() -> String {
    hostname::get()
        .ok()
        .and_then(|h| h.into_string().ok())
        .unwrap_or_else(|| "unknown".to_string())
}

/// Acquire a valid token: load from disk, refresh if expired, or run device flow.
async fn acquire_token(
    http: &reqwest::Client,
    auth_url: &str,
    token_path: &Path,
) -> Result<token_store::TokenSet, String> {
    // Try loading existing token
    if let Some(token_set) = token_store::load(token_path) {
        if !token_set.is_expired() {
            eprintln!("Loaded valid token from {}", token_path.display());
            return Ok(token_set);
        }

        // Try refresh
        if token_set.refresh_token.is_some() {
            eprintln!("Token expired, attempting refresh...");
            match oauth::refresh_token(http, &token_set).await {
                Ok(new_token) => {
                    token_store::save(token_path, &new_token)?;
                    eprintln!("Token refreshed successfully");
                    return Ok(new_token);
                }
                Err(e) => {
                    eprintln!("Token refresh failed: {e}");
                    // Fall through to device flow
                }
            }
        }
    }

    // Full device flow
    eprintln!("Starting device authorization flow...");
    let config = oauth::discover(http, auth_url).await?;
    let token_set = oauth::device_flow(http, &config).await?;
    token_store::save(token_path, &token_set)?;
    eprintln!("Authorization successful, token saved to {}", token_path.display());
    Ok(token_set)
}

/// Handle a 401 error: refresh or re-auth, update the relay client.
async fn handle_auth_error(
    http: &reqwest::Client,
    auth_url: &str,
    token_path: &Path,
    relay_client: &mut relay::RelayClient,
) -> Result<(), String> {
    eprintln!("Received 401, re-authenticating...");
    let token_set = acquire_token(http, auth_url, token_path).await?;
    relay_client.set_token(&token_set.access_token);
    Ok(())
}

#[tokio::main]
async fn main() {
    let cli = Cli::parse();

    let agent_name = cli.name.unwrap_or_else(get_hostname);
    let token_path = cli.token_file.unwrap_or_else(default_token_path);
    let cmd_channel = format!("{}-commands", agent_name);
    let out_channel = format!("{}-output", agent_name);

    eprintln!("remote-agent '{agent_name}'");
    eprintln!("  commands: {cmd_channel}");
    eprintln!("  output:   {out_channel}");
    eprintln!("  relay:    {}", cli.relay_url);
    eprintln!("  shell:    {}", cli.shell);
    eprintln!();

    let http = reqwest::Client::new();

    // Acquire token
    let token_set = match acquire_token(&http, &cli.auth_url, &token_path).await {
        Ok(t) => t,
        Err(e) => {
            eprintln!("Failed to acquire token: {e}");
            std::process::exit(1);
        }
    };

    let mut relay_client = relay::RelayClient::new(&cli.relay_url, &token_set.access_token);

    // Post startup message
    let startup_msg = format!("remote-agent online: {agent_name} ({})", get_hostname());
    match relay_client.send_message(&out_channel, &startup_msg).await {
        Ok(_) => eprintln!("Posted startup message"),
        Err(RelayError::Unauthorized) => {
            if let Err(e) =
                handle_auth_error(&http, &cli.auth_url, &token_path, &mut relay_client).await
            {
                eprintln!("Auth recovery failed: {e}");
                std::process::exit(1);
            }
            if let Err(e) = relay_client.send_message(&out_channel, &startup_msg).await {
                eprintln!("Failed to post startup message after re-auth: {e}");
            }
        }
        Err(e) => {
            eprintln!("Warning: Failed to post startup message: {e}");
        }
    }

    // Track the timestamp of the last message we've seen.
    // Initialize to "now" so we only process messages sent after startup.
    let mut last_seen: Option<String> = Some(chrono::Utc::now().to_rfc3339());
    let mut backoff_secs: u64 = cli.poll_interval;
    let max_backoff: u64 = 60;

    // Set up graceful shutdown
    let shutdown = Arc::new(Notify::new());
    let shutdown_clone = shutdown.clone();

    tokio::spawn(async move {
        let mut sigint = signal::unix::signal(signal::unix::SignalKind::interrupt())
            .expect("Failed to install SIGINT handler");
        let mut sigterm = signal::unix::signal(signal::unix::SignalKind::terminate())
            .expect("Failed to install SIGTERM handler");

        tokio::select! {
            _ = sigint.recv() => {},
            _ = sigterm.recv() => {},
        }

        shutdown_clone.notify_one();
    });

    eprintln!("Entering main loop (poll every {}s)...", cli.poll_interval);

    loop {
        // Check for shutdown
        let poll_result = tokio::select! {
            _ = shutdown.notified() => {
                break;
            }
            result = relay_client.read_messages(
                &cmd_channel,
                last_seen.as_deref(),
                Some(50),
            ) => {
                result
            }
        };

        match poll_result {
            Ok(response) => {
                backoff_secs = cli.poll_interval; // Reset backoff on success

                if response.messages.is_empty() {
                    tokio::time::sleep(std::time::Duration::from_secs(cli.poll_interval)).await;
                    continue;
                }

                for msg in &response.messages {
                    last_seen = Some(msg.timestamp.clone());

                    let command = msg.content.trim();
                    if command.is_empty() {
                        continue;
                    }

                    eprintln!("[{}] executing: {}", msg.sender, command);

                    let result = executor::execute(&cli.shell, command).await;
                    let output = result.format(command);

                    // Post result, handling auth errors
                    match relay_client.send_message(&out_channel, &output).await {
                        Ok(_) => {}
                        Err(RelayError::Unauthorized) => {
                            if let Err(e) = handle_auth_error(
                                &http,
                                &cli.auth_url,
                                &token_path,
                                &mut relay_client,
                            )
                            .await
                            {
                                eprintln!("Auth recovery failed: {e}");
                                break;
                            }
                            // Retry sending
                            if let Err(e) =
                                relay_client.send_message(&out_channel, &output).await
                            {
                                eprintln!("Failed to send output after re-auth: {e}");
                            }
                        }
                        Err(e) => {
                            eprintln!("Failed to send output: {e}");
                        }
                    }
                }
            }
            Err(RelayError::Unauthorized) => {
                if let Err(e) =
                    handle_auth_error(&http, &cli.auth_url, &token_path, &mut relay_client).await
                {
                    eprintln!("Auth recovery failed: {e}");
                    break;
                }
            }
            Err(e) => {
                eprintln!("Poll error: {e} (retrying in {backoff_secs}s)");
                tokio::time::sleep(std::time::Duration::from_secs(backoff_secs)).await;
                backoff_secs = (backoff_secs * 2).min(max_backoff);
            }
        }
    }

    // Graceful shutdown: post offline message
    eprintln!("\nShutting down...");
    let offline_msg = format!("remote-agent offline: {agent_name}");
    let _ = relay_client.send_message(&out_channel, &offline_msg).await;
    eprintln!("Goodbye.");
}
