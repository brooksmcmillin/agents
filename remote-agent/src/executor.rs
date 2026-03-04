use std::time::{Duration, Instant};
use tokio::process::Command;

const MAX_OUTPUT_BYTES: usize = 60 * 1024; // 60 KB (under 64 KB relay limit)
const DEFAULT_TIMEOUT: Duration = Duration::from_secs(300); // 5 minutes

pub struct CommandResult {
    pub exit_code: Option<i32>,
    pub output: String,
    pub duration_ms: u128,
}

impl CommandResult {
    /// Format the result for posting to the relay.
    pub fn format(&self, command: &str) -> String {
        let code_str = match self.exit_code {
            Some(code) => code.to_string(),
            None => "signal".to_string(),
        };
        format!(
            "$ {}\n{}\n[exit {} in {}ms]",
            command, self.output, code_str, self.duration_ms
        )
    }
}

/// Execute a shell command and capture combined stdout+stderr.
pub async fn execute(shell: &str, command: &str) -> CommandResult {
    let start = Instant::now();

    let result = tokio::time::timeout(DEFAULT_TIMEOUT, async {
        Command::new(shell)
            .arg("-c")
            .arg(command)
            .output()
            .await
    })
    .await;

    let duration_ms = start.elapsed().as_millis();

    match result {
        Ok(Ok(output)) => {
            let mut combined = Vec::new();
            combined.extend_from_slice(&output.stdout);
            combined.extend_from_slice(&output.stderr);

            let mut text = String::from_utf8_lossy(&combined).into_owned();
            if text.len() > MAX_OUTPUT_BYTES {
                text.truncate(MAX_OUTPUT_BYTES);
                text.push_str("\n... [output truncated]");
            }

            CommandResult {
                exit_code: output.status.code(),
                output: text,
                duration_ms,
            }
        }
        Ok(Err(e)) => CommandResult {
            exit_code: None,
            output: format!("Failed to execute command: {e}"),
            duration_ms,
        },
        Err(_) => CommandResult {
            exit_code: None,
            output: format!("Command timed out after {}s", DEFAULT_TIMEOUT.as_secs()),
            duration_ms,
        },
    }
}
