//! Supervises the local `jack-service` process (docs/architecture/ARCHITECTURE.md §3.2–3.3).
//!
//! * Generates a fresh 256-bit session token per launch (OS CSPRNG).
//! * Picks a free loopback port.
//! * Passes token + port to the child through its environment only (never argv).
//! * Probes `/health/live`; restarts the child on exit or after 3 failed probes, with
//!   exponential back-off (1 s → 30 s), giving up after 5 consecutive failed starts.
//! * On Windows the child is placed in a Job Object with KILL_ON_JOB_CLOSE so it cannot
//!   outlive the desktop process, even after a crash.

use serde::Serialize;
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::process::{Child, Command};
use tokio::sync::{Mutex, Notify};

pub const MAX_CONSECUTIVE_FAILURES: u32 = 5;
const PROBE_INTERVAL: Duration = Duration::from_secs(2);
const STARTUP_TIMEOUT: Duration = Duration::from_secs(45);
const STABLE_AFTER: Duration = Duration::from_secs(60);
const FAILED_PROBES_BEFORE_RESTART: u32 = 3;

#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum State {
    Starting,
    Running,
    Restarting,
    Failed,
    Stopped,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Status {
    pub state: State,
    pub restarts: u32,
    pub last_error: Option<String>,
    pub pid: Option<u32>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Connection {
    pub base_url: String,
    pub ws_url: String,
    pub token: String,
}

/// How to launch the service. Resolved once at start-up.
#[derive(Debug, Clone)]
pub struct LaunchSpec {
    pub program: PathBuf,
    pub args: Vec<String>,
    pub cwd: Option<PathBuf>,
    pub data_dir: PathBuf,
    pub dev_mode: bool,
}

pub type OnChange = Arc<dyn Fn(&Status) + Send + Sync>;

struct Inner {
    status: Status,
    conn: Option<Connection>,
    child: Option<Child>,
    #[cfg(windows)]
    job: Option<win::Job>,
}

pub struct Supervisor {
    spec: LaunchSpec,
    inner: Mutex<Inner>,
    restart_now: Notify,
    shutdown: Notify,
    on_change: OnChange,
}

pub fn generate_token() -> String {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).expect("OS random number generator unavailable");
    hex::encode(bytes)
}

pub fn free_loopback_port() -> std::io::Result<u16> {
    let l = TcpListener::bind(("127.0.0.1", 0))?;
    Ok(l.local_addr()?.port())
}

pub fn backoff(consecutive_failures: u32) -> Duration {
    let secs = 1u64 << consecutive_failures.min(5);
    Duration::from_secs(secs.min(30))
}

impl Supervisor {
    pub fn new(spec: LaunchSpec, on_change: OnChange) -> Arc<Self> {
        Arc::new(Self {
            spec,
            inner: Mutex::new(Inner {
                status: Status {
                    state: State::Stopped,
                    restarts: 0,
                    last_error: None,
                    pid: None,
                },
                conn: None,
                child: None,
                #[cfg(windows)]
                job: None,
            }),
            restart_now: Notify::new(),
            shutdown: Notify::new(),
            on_change,
        })
    }

    pub async fn status(&self) -> Status {
        self.inner.lock().await.status.clone()
    }

    pub async fn connection(&self) -> Option<Connection> {
        let g = self.inner.lock().await;
        (g.status.state == State::Running)
            .then(|| g.conn.clone())
            .flatten()
    }

    pub fn request_restart(&self) {
        self.restart_now.notify_one();
    }

    async fn set(&self, f: impl FnOnce(&mut Status)) {
        let snapshot = {
            let mut g = self.inner.lock().await;
            f(&mut g.status);
            g.status.clone()
        };
        (self.on_change)(&snapshot);
    }

    async fn spawn(&self) -> Result<Connection, String> {
        let token = generate_token();
        let port = free_loopback_port().map_err(|e| format!("no free port: {e}"))?;
        let mut cmd = Command::new(&self.spec.program);
        cmd.args(&self.spec.args)
            .env("JACK_SESSION_TOKEN", &token)
            .env("JACK_PORT", port.to_string())
            .env("JACK_HOST", "127.0.0.1")
            .env("JACK_DATA_DIR", &self.spec.data_dir)
            .env("JACK_DEV_MODE", if self.spec.dev_mode { "1" } else { "0" })
            .env("JACK_EXIT_WITH_PARENT", "1")
            .env("JACK_SUPERVISOR_PID", std::process::id().to_string())
            .stdin(Stdio::null())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .kill_on_drop(true);
        if let Some(cwd) = &self.spec.cwd {
            cmd.current_dir(cwd);
        }
        #[cfg(windows)]
        {
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }
        let child = cmd
            .spawn()
            .map_err(|e| format!("failed to start {}: {e}", self.spec.program.display()))?;
        let pid = child.id();
        {
            let mut g = self.inner.lock().await;
            #[cfg(windows)]
            {
                g.job = win::Job::assign(&child).ok();
            }
            g.child = Some(child);
            g.status.pid = pid;
        }
        let base_url = format!("http://127.0.0.1:{port}");
        Ok(Connection {
            ws_url: format!("ws://127.0.0.1:{port}/v1/ws"),
            base_url,
            token,
        })
    }

    async fn wait_until_live(&self, http: &reqwest::Client, base: &str) -> Result<(), String> {
        let deadline = Instant::now() + STARTUP_TIMEOUT;
        while Instant::now() < deadline {
            if self.child_exited().await {
                return Err("service exited during start-up".into());
            }
            if probe(http, base).await {
                return Ok(());
            }
            tokio::time::sleep(Duration::from_millis(250)).await;
        }
        Err(format!(
            "service not live after {}s",
            STARTUP_TIMEOUT.as_secs()
        ))
    }

    async fn child_exited(&self) -> bool {
        let mut g = self.inner.lock().await;
        match g.child.as_mut() {
            Some(c) => !matches!(c.try_wait(), Ok(None)),
            None => true,
        }
    }

    async fn kill_child(&self) {
        let mut g = self.inner.lock().await;
        if let Some(mut c) = g.child.take() {
            // Graceful first: on Unix, SIGTERM lets uvicorn shut down cleanly and the
            // PyInstaller bootloader forwards it to its Python child. SIGKILL would orphan
            // that child. On Windows the Job Object terminates the whole tree.
            #[cfg(unix)]
            if let Some(pid) = c.id() {
                // SAFETY: plain libc call on a pid we spawned and still own.
                unsafe {
                    libc::kill(pid as libc::pid_t, libc::SIGTERM);
                }
                if tokio::time::timeout(Duration::from_secs(5), c.wait())
                    .await
                    .is_ok()
                {
                    g.conn = None;
                    g.status.pid = None;
                    return;
                }
            }
            let _ = c.start_kill();
            let _ = tokio::time::timeout(Duration::from_secs(5), c.wait()).await;
        }
        g.conn = None;
        g.status.pid = None;
        #[cfg(windows)]
        {
            g.job = None;
        }
    }

    /// Main supervision loop. Runs until `stop` is called.
    pub async fn run(self: Arc<Self>) {
        let http = reqwest::Client::builder()
            .timeout(Duration::from_secs(2))
            .no_proxy()
            .build()
            .expect("http client");
        let mut consecutive_failures = 0u32;
        loop {
            self.set(|s| {
                s.state = if s.restarts == 0 && consecutive_failures == 0 {
                    State::Starting
                } else {
                    State::Restarting
                }
            })
            .await;

            let started = match self.spawn().await {
                Ok(conn) => match self.wait_until_live(&http, &conn.base_url).await {
                    Ok(()) => Ok(conn),
                    Err(e) => Err(e),
                },
                Err(e) => Err(e),
            };

            let conn = match started {
                Ok(conn) => conn,
                Err(e) => {
                    log::error!("jack-service start failed: {e}");
                    self.kill_child().await;
                    consecutive_failures += 1;
                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES {
                        self.set(|s| {
                            s.state = State::Failed;
                            s.last_error = Some(e);
                        })
                        .await;
                        // Wait for a manual restart request or shutdown.
                        tokio::select! {
                            _ = self.restart_now.notified() => { consecutive_failures = 0; continue; }
                            _ = self.shutdown.notified() => break,
                        }
                    }
                    self.set(|s| s.last_error = Some(e)).await;
                    tokio::select! {
                        _ = tokio::time::sleep(backoff(consecutive_failures)) => continue,
                        _ = self.shutdown.notified() => break,
                    }
                }
            };

            self.inner.lock().await.conn = Some(conn.clone());
            self.set(|s| {
                s.state = State::Running;
                s.last_error = None;
            })
            .await;
            log::info!("jack-service running at {}", conn.base_url);

            let running_since = Instant::now();
            let mut failed_probes = 0u32;
            let reason: Option<String> = loop {
                tokio::select! {
                    _ = tokio::time::sleep(PROBE_INTERVAL) => {}
                    _ = self.restart_now.notified() => break Some("restart requested".into()),
                    _ = self.shutdown.notified() => break None,
                }
                if self.child_exited().await {
                    break Some("service process exited".into());
                }
                if probe(&http, &conn.base_url).await {
                    failed_probes = 0;
                } else {
                    failed_probes += 1;
                    if failed_probes >= FAILED_PROBES_BEFORE_RESTART {
                        break Some("service stopped responding".into());
                    }
                }
            };

            // Leave `Running` before tearing down so nobody observes a running state
            // without a connection.
            if reason.is_some() {
                self.set(|s| s.state = State::Restarting).await;
            }
            self.kill_child().await;
            let Some(reason) = reason else { break };
            log::warn!("restarting jack-service: {reason}");
            if running_since.elapsed() >= STABLE_AFTER || reason == "restart requested" {
                consecutive_failures = 0;
            } else {
                consecutive_failures += 1;
            }
            self.set(|s| {
                s.restarts += 1;
                s.last_error = Some(reason);
            })
            .await;
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES {
                self.set(|s| s.state = State::Failed).await;
                tokio::select! {
                    _ = self.restart_now.notified() => { consecutive_failures = 0; }
                    _ = self.shutdown.notified() => break,
                }
            } else if consecutive_failures > 0 {
                tokio::time::sleep(backoff(consecutive_failures)).await;
            }
        }
        self.kill_child().await;
        self.set(|s| s.state = State::Stopped).await;
    }

    pub async fn stop(&self) {
        self.shutdown.notify_waiters();
        self.shutdown.notify_one();
        self.kill_child().await;
    }
}

async fn probe(http: &reqwest::Client, base: &str) -> bool {
    matches!(
        http.get(format!("{base}/health/live")).send().await,
        Ok(r) if r.status().is_success()
    )
}

#[cfg(windows)]
mod win {
    use std::ffi::c_void;
    use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };

    /// Owned Job Object handle; closing it kills every process in the job.
    pub struct Job(HANDLE);
    // SAFETY: a job handle is a kernel object handle usable from any thread.
    unsafe impl Send for Job {}
    unsafe impl Sync for Job {}

    impl Job {
        pub fn assign(child: &tokio::process::Child) -> std::io::Result<Self> {
            let process = child
                .raw_handle()
                .ok_or_else(|| std::io::Error::other("child already exited"))?;
            // SAFETY: plain Win32 calls with valid arguments; handle ownership is tracked by Job.
            unsafe {
                let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
                if job.is_null() {
                    return Err(std::io::Error::last_os_error());
                }
                let job = Job(job);
                let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
                info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
                if SetInformationJobObject(
                    job.0,
                    JobObjectExtendedLimitInformation,
                    &info as *const _ as *const c_void,
                    std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                ) == 0
                {
                    return Err(std::io::Error::last_os_error());
                }
                if AssignProcessToJobObject(job.0, process as HANDLE) == 0 {
                    return Err(std::io::Error::last_os_error());
                }
                Ok(job)
            }
        }
    }

    impl Drop for Job {
        fn drop(&mut self) {
            // SAFETY: handle was created by CreateJobObjectW and is closed exactly once.
            unsafe {
                CloseHandle(self.0);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn token_is_256_bit_hex_and_unique() {
        let a = generate_token();
        let b = generate_token();
        assert_eq!(a.len(), 64);
        assert!(a.chars().all(|c| c.is_ascii_hexdigit()));
        assert_ne!(a, b);
    }

    #[test]
    fn backoff_is_bounded() {
        assert_eq!(backoff(0), Duration::from_secs(1));
        assert_eq!(backoff(1), Duration::from_secs(2));
        assert_eq!(backoff(4), Duration::from_secs(16));
        assert_eq!(backoff(5), Duration::from_secs(30));
        assert_eq!(backoff(50), Duration::from_secs(30));
    }

    #[test]
    fn port_is_loopback_bindable() {
        let p = free_loopback_port().unwrap();
        assert!(p > 0);
        TcpListener::bind(("127.0.0.1", p)).unwrap();
    }
}
