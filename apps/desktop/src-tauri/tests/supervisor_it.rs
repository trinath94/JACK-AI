//! Integration test against the real jack-service (M1 acceptance item 8).
//!
//! Requires JACK_SERVICE_BIN to point at a frozen sidecar (scripts/build_sidecar.py).
//! Skipped (with a message) when it is not set.

use jack_ai_lib::supervisor::{LaunchSpec, State, Status, Supervisor};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

async fn wait_for(sup: &Supervisor, want: State, timeout: Duration) -> Status {
    let deadline = Instant::now() + timeout;
    loop {
        let s = sup.status().await;
        if s.state == want {
            return s;
        }
        assert!(
            Instant::now() < deadline,
            "timed out waiting for {want:?}; last status {s:?}"
        );
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
}

fn kill_pid(pid: u32) {
    #[cfg(unix)]
    let ok = std::process::Command::new("kill")
        .args(["-9", &pid.to_string()])
        .status();
    #[cfg(windows)]
    let ok = std::process::Command::new("taskkill")
        .args(["/F", "/PID", &pid.to_string()])
        .status();
    assert!(ok.expect("kill command").success());
}

#[tokio::test(flavor = "multi_thread")]
async fn supervises_restarts_and_authenticates() {
    let Ok(bin) = std::env::var("JACK_SERVICE_BIN") else {
        eprintln!("SKIPPED: set JACK_SERVICE_BIN to a built jack-service binary");
        return;
    };
    let data = std::env::temp_dir().join(format!("jack-it-{}", std::process::id()));
    let seen: Arc<Mutex<Vec<State>>> = Arc::default();
    let seen2 = seen.clone();
    let sup = Supervisor::new(
        LaunchSpec {
            program: bin.into(),
            args: vec![],
            cwd: None,
            data_dir: data.clone(),
            dev_mode: false,
        },
        Arc::new(move |s: &Status| seen2.lock().unwrap().push(s.state)),
    );
    let runner = tokio::spawn(sup.clone().run());

    let first = wait_for(&sup, State::Running, Duration::from_secs(60)).await;
    let conn = sup.connection().await.expect("connection when running");
    assert!(conn.base_url.starts_with("http://127.0.0.1:"));
    assert_eq!(conn.token.len(), 64);

    let http = reqwest::Client::builder().no_proxy().build().unwrap();
    let unauth = http
        .get(format!("{}/v1/health", conn.base_url))
        .send()
        .await
        .unwrap();
    assert_eq!(unauth.status(), 401);
    let auth = http
        .get(format!("{}/v1/health", conn.base_url))
        .bearer_auth(&conn.token)
        .send()
        .await
        .unwrap();
    assert_eq!(auth.status(), 200);

    // Crash the service from outside; the supervisor must bring it back with a NEW token.
    kill_pid(first.pid.expect("pid"));
    let deadline = Instant::now() + Duration::from_secs(60);
    let second = loop {
        let s = sup.status().await;
        if s.state == State::Running && s.restarts >= 1 && s.pid != first.pid {
            break s;
        }
        assert!(
            Instant::now() < deadline,
            "service was not restarted: {s:?}"
        );
        tokio::time::sleep(Duration::from_millis(100)).await;
    };
    assert_eq!(second.restarts, 1);
    let conn2 = sup.connection().await.expect("connection after restart");
    assert_ne!(conn2.token, conn.token, "token must rotate on restart");
    let old_token = http
        .get(format!("{}/v1/health", conn2.base_url))
        .bearer_auth(&conn.token)
        .send()
        .await
        .unwrap();
    assert_eq!(old_token.status(), 401, "old token must be rejected");

    sup.stop().await;
    tokio::time::timeout(Duration::from_secs(10), runner)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(sup.status().await.state, State::Stopped);
    let states = seen.lock().unwrap().clone();
    assert!(states.contains(&State::Restarting), "states: {states:?}");
    let _ = std::fs::remove_dir_all(data);
}
