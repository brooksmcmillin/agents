use reqwest::Client;
use serde::Deserialize;
use std::collections::HashMap;
use std::time::Duration;

use crate::token_store::TokenSet;

#[derive(Debug)]
pub struct OAuthConfig {
    pub token_endpoint: String,
    pub registration_endpoint: String,
    pub device_authorization_endpoint: String,
}

#[derive(Debug, Deserialize)]
struct ProtectedResourceMeta {
    authorization_servers: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct AuthServerMeta {
    token_endpoint: String,
    registration_endpoint: Option<String>,
    device_authorization_endpoint: Option<String>,
}

#[derive(Debug, Deserialize)]
struct RegistrationResponse {
    client_id: String,
}

#[derive(Debug, Deserialize)]
struct DeviceCodeResponse {
    device_code: String,
    user_code: String,
    verification_uri: String,
    verification_uri_complete: Option<String>,
    expires_in: Option<u64>,
    interval: Option<u64>,
}

#[derive(Debug, Deserialize)]
struct TokenResponse {
    access_token: String,
    refresh_token: Option<String>,
    expires_in: Option<u64>,
}

#[derive(Debug, Deserialize)]
struct TokenErrorResponse {
    error: String,
}

/// Discover OAuth endpoints from the auth URL.
pub async fn discover(client: &Client, auth_url: &str) -> Result<OAuthConfig, String> {
    let resource_url = format!("{}/.well-known/oauth-protected-resource", auth_url);
    let resp = client
        .get(&resource_url)
        .send()
        .await
        .map_err(|e| format!("Failed to fetch protected resource metadata: {e}"))?;

    if !resp.status().is_success() {
        return Err(format!(
            "Protected resource metadata returned {}",
            resp.status()
        ));
    }

    let meta: ProtectedResourceMeta = resp
        .json()
        .await
        .map_err(|e| format!("Failed to parse protected resource metadata: {e}"))?;

    let auth_server = meta
        .authorization_servers
        .first()
        .ok_or("No authorization servers found")?;

    let as_url = format!(
        "{}/.well-known/oauth-authorization-server",
        auth_server.trim_end_matches('/')
    );
    let resp = client
        .get(&as_url)
        .send()
        .await
        .map_err(|e| format!("Failed to fetch auth server metadata: {e}"))?;

    if !resp.status().is_success() {
        return Err(format!("Auth server metadata returned {}", resp.status()));
    }

    let as_meta: AuthServerMeta = resp
        .json()
        .await
        .map_err(|e| format!("Failed to parse auth server metadata: {e}"))?;

    let registration_endpoint = as_meta
        .registration_endpoint
        .ok_or("Auth server has no registration_endpoint")?;
    let device_authorization_endpoint = as_meta
        .device_authorization_endpoint
        .ok_or("Auth server has no device_authorization_endpoint")?;

    Ok(OAuthConfig {
        token_endpoint: as_meta.token_endpoint,
        registration_endpoint,
        device_authorization_endpoint,
    })
}

/// Register a dynamic OAuth client for device flow.
pub async fn register_client(client: &Client, config: &OAuthConfig) -> Result<String, String> {
    let mut body = HashMap::new();
    body.insert(
        "grant_types",
        serde_json::json!([
            "urn:ietf:params:oauth:grant-type:device_code",
            "refresh_token"
        ]),
    );
    body.insert(
        "token_endpoint_auth_method",
        serde_json::json!("none"),
    );
    body.insert(
        "client_name",
        serde_json::json!("remote-agent"),
    );

    let resp = client
        .post(&config.registration_endpoint)
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("Client registration request failed: {e}"))?;

    if !resp.status().is_success() {
        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
        return Err(format!(
            "Client registration failed ({status}): {text}"
        ));
    }

    let reg: RegistrationResponse = resp
        .json()
        .await
        .map_err(|e| format!("Failed to parse registration response: {e}"))?;

    Ok(reg.client_id)
}

/// Run the full device authorization flow. Returns a TokenSet.
pub async fn device_flow(client: &Client, config: &OAuthConfig) -> Result<TokenSet, String> {
    let client_id = register_client(client, config).await?;

    // Request device code
    let mut form = HashMap::new();
    form.insert("client_id", client_id.as_str());

    let resp = client
        .post(&config.device_authorization_endpoint)
        .form(&form)
        .send()
        .await
        .map_err(|e| format!("Device authorization request failed: {e}"))?;

    if !resp.status().is_success() {
        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
        return Err(format!(
            "Device authorization failed ({status}): {text}"
        ));
    }

    let device: DeviceCodeResponse = resp
        .json()
        .await
        .map_err(|e| format!("Failed to parse device code response: {e}"))?;

    // Display instructions to user
    eprintln!();
    eprintln!("============================================================");
    eprintln!("  DEVICE AUTHORIZATION REQUIRED");
    eprintln!("============================================================");
    eprintln!();
    if let Some(ref uri_complete) = device.verification_uri_complete {
        eprintln!("  Visit: {uri_complete}");
    } else {
        eprintln!("  Visit: {}", device.verification_uri);
        eprintln!("  Enter code: {}", device.user_code);
    }
    let expires_min = device.expires_in.unwrap_or(1800) / 60;
    eprintln!();
    eprintln!("  This code expires in {expires_min} minutes.");
    eprintln!("============================================================");
    eprintln!();

    // Poll for token
    let mut interval = device.interval.unwrap_or(5);
    let expires_in = device.expires_in.unwrap_or(1800);
    let deadline = std::time::Instant::now() + Duration::from_secs(expires_in);

    loop {
        tokio::time::sleep(Duration::from_secs(interval)).await;

        if std::time::Instant::now() > deadline {
            return Err("Device code expired".to_string());
        }

        let mut form = HashMap::new();
        form.insert(
            "grant_type",
            "urn:ietf:params:oauth:grant-type:device_code",
        );
        form.insert("device_code", &device.device_code);
        form.insert("client_id", &client_id);

        let resp = client
            .post(&config.token_endpoint)
            .form(&form)
            .send()
            .await
            .map_err(|e| format!("Token poll request failed: {e}"))?;

        let status = resp.status();
        let body = resp
            .text()
            .await
            .map_err(|e| format!("Failed to read token response: {e}"))?;

        if status.is_success() {
            let token: TokenResponse = serde_json::from_str(&body)
                .map_err(|e| format!("Failed to parse token response: {e}"))?;

            let now = chrono::Utc::now().timestamp() as u64;
            return Ok(TokenSet {
                access_token: token.access_token,
                refresh_token: token.refresh_token,
                expires_in: token.expires_in,
                client_id: Some(client_id),
                client_secret: None,
                issued_at: now,
                token_endpoint: config.token_endpoint.clone(),
            });
        }

        // Check for expected polling errors
        if let Ok(err) = serde_json::from_str::<TokenErrorResponse>(&body) {
            match err.error.as_str() {
                "authorization_pending" => continue,
                "slow_down" => {
                    interval += 5;
                    continue;
                }
                "expired_token" => return Err("Device code expired".to_string()),
                "access_denied" => return Err("Authorization denied by user".to_string()),
                other => return Err(format!("Token endpoint error: {other}")),
            }
        }

        return Err(format!("Unexpected token response ({status}): {body}"));
    }
}

/// Refresh an access token using the refresh token.
pub async fn refresh_token(client: &Client, token_set: &TokenSet) -> Result<TokenSet, String> {
    let refresh = token_set
        .refresh_token
        .as_deref()
        .ok_or("No refresh token available")?;
    let client_id = token_set
        .client_id
        .as_deref()
        .ok_or("No client_id stored for refresh")?;

    let mut form = HashMap::new();
    form.insert("grant_type", "refresh_token");
    form.insert("refresh_token", refresh);
    form.insert("client_id", client_id);

    let resp = client
        .post(&token_set.token_endpoint)
        .form(&form)
        .send()
        .await
        .map_err(|e| format!("Token refresh request failed: {e}"))?;

    if !resp.status().is_success() {
        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
        return Err(format!("Token refresh failed ({status}): {text}"));
    }

    let token: TokenResponse = resp
        .json()
        .await
        .map_err(|e| format!("Failed to parse refresh response: {e}"))?;

    let now = chrono::Utc::now().timestamp() as u64;
    Ok(TokenSet {
        access_token: token.access_token,
        refresh_token: token.refresh_token.or(token_set.refresh_token.clone()),
        expires_in: token.expires_in,
        client_id: token_set.client_id.clone(),
        client_secret: None,
        issued_at: now,
        token_endpoint: token_set.token_endpoint.clone(),
    })
}
