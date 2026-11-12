//! Authenticated calls from the Rust core to the local service (used by the global
//! push-to-talk hotkey and the tray, which must work while the window is hidden).

use crate::supervisor::Supervisor;
use std::time::Duration;

pub async fn call(
    supervisor: &Supervisor,
    method: reqwest::Method,
    path: &str,
    body: Option<serde_json::Value>,
) -> Result<serde_json::Value, String> {
    let conn = supervisor
        .connection()
        .await
        .ok_or_else(|| "JACK service is not running".to_string())?;
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .no_proxy()
        .build()
        .map_err(|e| e.to_string())?;
    let mut req = client
        .request(method, format!("{}{}", conn.base_url, path))
        .bearer_auth(&conn.token);
    if let Some(b) = body {
        req = req.json(&b);
    }
    let resp = req.send().await.map_err(|e| e.to_string())?;
    let status = resp.status();
    let value: serde_json::Value = resp.json().await.unwrap_or(serde_json::Value::Null);
    if status.is_success() {
        Ok(value)
    } else {
        Err(value["error"]["message"]
            .as_str()
            .map(str::to_owned)
            .unwrap_or_else(|| format!("HTTP {status}")))
    }
}
