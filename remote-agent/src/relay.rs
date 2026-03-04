use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::time::Duration;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Message {
    pub id: String,
    pub channel: String,
    pub sender: String,
    pub content: String,
    pub timestamp: String,
}

#[derive(Debug, Deserialize)]
#[allow(dead_code)]
pub struct MessagesResponse {
    pub channel: String,
    pub messages: Vec<Message>,
    pub count: usize,
}

pub struct RelayClient {
    client: Client,
    base_url: String,
    access_token: String,
}

/// Error types for relay operations.
#[derive(Debug)]
pub enum RelayError {
    Unauthorized,
    Request(String),
    Api(u16, String),
}

impl std::fmt::Display for RelayError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            RelayError::Unauthorized => write!(f, "Unauthorized (401)"),
            RelayError::Request(e) => write!(f, "Request error: {e}"),
            RelayError::Api(status, body) => write!(f, "API error ({status}): {body}"),
        }
    }
}

impl RelayClient {
    pub fn new(base_url: &str, access_token: &str) -> Self {
        let client = Client::builder()
            .timeout(Duration::from_secs(60))
            .build()
            .expect("Failed to build HTTP client");

        Self {
            client,
            base_url: base_url.trim_end_matches('/').to_string(),
            access_token: access_token.to_string(),
        }
    }

    pub fn set_token(&mut self, token: &str) {
        self.access_token = token.to_string();
    }

    /// Send a message to a channel.
    pub async fn send_message(&self, channel: &str, content: &str) -> Result<Message, RelayError> {
        let url = format!("{}/channels/{}/messages", self.base_url, channel);

        let body = serde_json::json!({ "content": content });

        let resp = self
            .client
            .post(&url)
            .bearer_auth(&self.access_token)
            .json(&body)
            .send()
            .await
            .map_err(|e| RelayError::Request(e.to_string()))?;

        let status = resp.status();
        if status.as_u16() == 401 {
            return Err(RelayError::Unauthorized);
        }
        if !status.is_success() {
            let text = resp.text().await.unwrap_or_default();
            return Err(RelayError::Api(status.as_u16(), text));
        }

        resp.json::<Message>()
            .await
            .map_err(|e| RelayError::Request(e.to_string()))
    }

    /// Read messages from a channel, optionally filtering by timestamp.
    pub async fn read_messages(
        &self,
        channel: &str,
        since: Option<&str>,
        limit: Option<u32>,
    ) -> Result<MessagesResponse, RelayError> {
        let url = format!("{}/channels/{}/messages", self.base_url, channel);

        let mut req = self.client.get(&url).bearer_auth(&self.access_token);

        if let Some(since) = since {
            req = req.query(&[("since", since)]);
        }
        if let Some(limit) = limit {
            req = req.query(&[("limit", limit.to_string())]);
        }
        // Always sort ascending so we process messages in order
        req = req.query(&[("sort_order", "asc")]);

        let resp = req
            .send()
            .await
            .map_err(|e| RelayError::Request(e.to_string()))?;

        let status = resp.status();
        if status.as_u16() == 401 {
            return Err(RelayError::Unauthorized);
        }
        if !status.is_success() {
            let text = resp.text().await.unwrap_or_default();
            return Err(RelayError::Api(status.as_u16(), text));
        }

        resp.json::<MessagesResponse>()
            .await
            .map_err(|e| RelayError::Request(e.to_string()))
    }
}
