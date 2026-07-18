//! Sidecar lifecycle: venv bootstrap, spawn, handshake, process-tree kill.
//!
//! Flow (all off the main thread, entered via [`run`]):
//!   1. `ensure_venv` — idempotent bootstrap of `<app_data>/venv` from the
//!      bundled CPython + wheelhouse resources (skipped entirely when the
//!      `DPI_EVAL_DESKTOP_VENV` override is set).
//!   2. `spawn_sidecar` — launches `dpi-eval-web --no-browser` in its own
//!      process group (unix) / Job Object with kill-on-close (windows).
//!   3. Handshake — within a 60 s budget: read stdout for the sentinel line,
//!      then poll `GET <url>/` every 500 ms until HTTP 200, then navigate the
//!      main window. Any failure shows a native dialog naming the log file.
//!   4. [`shutdown`] — kills the whole process tree (killpg / Job close).

use std::io::{BufRead, BufReader, Write as _};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{mpsc, Mutex};
use std::time::{Duration, Instant};

use tauri::{AppHandle, Emitter, Manager, Url};
use tauri_plugin_dialog::{DialogExt, MessageDialogKind};

/// Total budget for sentinel + HTTP handshake.
const HANDSHAKE_BUDGET: Duration = Duration::from_secs(60);
/// Interval between `GET <url>/` polls.
const POLL_INTERVAL: Duration = Duration::from_millis(500);
/// Grace period between SIGTERM and SIGKILL on unix shutdown.
#[cfg(unix)]
const TERM_GRACE: Duration = Duration::from_secs(3);

/// Env var naming an existing venv to use instead of bootstrapping.
/// Committed on purpose: it is how dev-machine verification and Task 9's
/// re-tests point the app at a hand-built venv.
pub const VENV_OVERRIDE_ENV: &str = "DPI_EVAL_DESKTOP_VENV";

// ---------------------------------------------------------------------------
// Pure helpers (unit-tested)
// ---------------------------------------------------------------------------

pub fn parse_sentinel(line: &str) -> Option<String> {
    line.strip_prefix("dpi-eval-web running at ")
        .map(|url| url.trim().to_string())
}

pub fn marker_matches(venv: &std::path::Path, hash: &str) -> bool {
    std::fs::read_to_string(venv.join(".bootstrap-ok"))
        .map(|s| s.trim() == hash)
        .unwrap_or(false)
}

pub fn write_marker(venv: &std::path::Path, hash: &str) -> std::io::Result<()> {
    std::fs::write(venv.join(".bootstrap-ok"), hash)
}

// ---------------------------------------------------------------------------
// Sidecar handle
// ---------------------------------------------------------------------------

/// Running sidecar plus whatever the platform needs to kill its whole tree.
pub struct Sidecar {
    child: Child,
    #[cfg(windows)]
    job: job::JobHandle,
}

/// Process-wide slot for the running sidecar. A module global rather than
/// Tauri managed state so the unix signal watcher (which has no AppHandle)
/// can reach it too.
static SIDECAR: Mutex<Option<Sidecar>> = Mutex::new(None);

// ---------------------------------------------------------------------------
// Entry point (called from `setup` on a worker thread)
// ---------------------------------------------------------------------------

pub fn run(app: AppHandle) {
    let log_path = sidecar_log_path(&app);
    if let Err(detail) = run_inner(&app, &log_path) {
        eprintln!("[dpi-eval-desktop] startup failed: {detail}");
        emit_status(&app, &format!("failed: {detail}"));
        app.dialog()
            .message(format!(
                "dpi-eval could not start.\n\n{detail}\n\nDetails were written to:\n{}",
                log_path.display()
            ))
            .kind(MessageDialogKind::Error)
            .title("dpi-eval")
            .blocking_show();
    }
}

fn run_inner(app: &AppHandle, log_path: &Path) -> Result<(), String> {
    if let Some(dir) = log_path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| format!("cannot create log dir: {e}"))?;
    }

    // 1. Resolve the venv: env override, or bootstrap from bundled resources.
    let venv = match std::env::var(VENV_OVERRIDE_ENV) {
        Ok(v) if !v.is_empty() => {
            eprintln!("[dpi-eval-desktop] using venv override {VENV_OVERRIDE_ENV}={v}");
            PathBuf::from(v)
        }
        _ => {
            let resource_dir = app
                .path()
                .resource_dir()
                .map_err(|e| format!("cannot resolve resource dir: {e}"))?;
            let app_data = app
                .path()
                .app_data_dir()
                .map_err(|e| format!("cannot resolve app data dir: {e}"))?;
            let status_app = app.clone();
            ensure_venv(&app_data, &resource_dir, &|s| emit_status(&status_app, s))?
        }
    };

    // 2. Spawn the sidecar, keeping stdout for the handshake.
    let deadline = Instant::now() + HANDSHAKE_BUDGET;
    let mut sidecar = spawn_sidecar(&venv, log_path)
        .map_err(|e| format!("failed to launch dpi-eval-web: {e}"))?;
    eprintln!(
        "[dpi-eval-desktop] sidecar spawned, pid {}",
        sidecar.child.id()
    );
    let stdout = sidecar
        .child
        .stdout
        .take()
        .ok_or_else(|| "sidecar stdout was not piped".to_string())?;
    *SIDECAR.lock().unwrap() = Some(sidecar);

    // Forward stdout lines to the handshake (and echo them into the log).
    // The reader thread keeps draining after the handshake drops the receiver
    // so the pipe never fills up.
    let (tx, rx) = mpsc::channel::<String>();
    let stdout_log = log_path.to_path_buf();
    std::thread::spawn(move || {
        let mut log = std::fs::File::options()
            .create(true)
            .append(true)
            .open(&stdout_log)
            .ok();
        for line in BufReader::new(stdout).lines() {
            let Ok(line) = line else { break };
            if let Some(log) = log.as_mut() {
                let _ = writeln!(log, "{line}");
            }
            let _ = tx.send(line);
        }
    });

    // 3a. Wait for the sentinel line.
    let url = loop {
        check_deadline(deadline, "no startup line from dpi-eval-web")?;
        match rx.recv_timeout(Duration::from_millis(250)) {
            Ok(line) => {
                eprintln!("[dpi-eval-desktop] sidecar stdout: {line}");
                if let Some(url) = parse_sentinel(&line) {
                    eprintln!("[dpi-eval-desktop] sentinel parsed: {url}");
                    break url;
                }
            }
            Err(mpsc::RecvTimeoutError::Timeout) => check_alive()?,
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                check_alive()?;
                return Err("dpi-eval-web closed stdout before announcing its URL".into());
            }
        }
    };

    // 3b. Poll until the server actually answers.
    let parsed =
        Url::parse(&url).map_err(|e| format!("sidecar announced a bad URL ({url}): {e}"))?;
    let host = parsed.host_str().unwrap_or("127.0.0.1").to_string();
    let port = parsed
        .port_or_known_default()
        .ok_or_else(|| format!("sidecar URL has no port: {url}"))?;
    loop {
        check_deadline(deadline, "dpi-eval-web never answered HTTP")?;
        check_alive()?;
        if http_get_ok(&host, port) {
            eprintln!("[dpi-eval-desktop] HTTP 200 from {url}");
            break;
        }
        std::thread::sleep(POLL_INTERVAL);
    }

    // 3c. Show the real UI.
    emit_status(app, "ready");
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| "main window is gone".to_string())?;
    window
        .navigate(parsed)
        .map_err(|e| format!("failed to navigate to {url}: {e}"))?;
    eprintln!("[dpi-eval-desktop] navigated main window to {url}");
    Ok(())
}

fn emit_status(app: &AppHandle, status: &str) {
    let _ = app.emit_to("main", "bootstrap-status", status.to_string());
}

fn sidecar_log_path(app: &AppHandle) -> PathBuf {
    app.path()
        .app_data_dir()
        .map(|d| d.join("logs").join("sidecar.log"))
        .unwrap_or_else(|_| std::env::temp_dir().join("dpi-eval-sidecar.log"))
}

/// Err if the deadline has passed.
fn check_deadline(deadline: Instant, what: &str) -> Result<(), String> {
    if Instant::now() >= deadline {
        Err(format!("timed out after 60s: {what}"))
    } else {
        Ok(())
    }
}

/// Err if the sidecar has already exited.
fn check_alive() -> Result<(), String> {
    let mut guard = SIDECAR.lock().unwrap();
    if let Some(sidecar) = guard.as_mut() {
        if let Ok(Some(status)) = sidecar.child.try_wait() {
            return Err(format!("dpi-eval-web exited during startup ({status})"));
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------

struct Manifest {
    package: String,
    hash: String,
    probe: bool,
}

fn read_manifest(wheelhouse: &Path) -> Result<Manifest, String> {
    let path = wheelhouse.join("MANIFEST");
    let text = std::fs::read_to_string(&path)
        .map_err(|e| format!("missing wheelhouse manifest {}: {e}", path.display()))?;
    let mut lines = text.lines();
    let package = lines
        .next()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .ok_or("MANIFEST is empty (expected package name on line 1)")?
        .to_string();
    let hash = lines
        .next()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .ok_or("MANIFEST has no hash on line 2")?
        .to_string();
    let probe = lines.next().map(str::trim) == Some("probe");
    Ok(Manifest {
        package,
        hash,
        probe,
    })
}

fn bundled_python(resource_dir: &Path) -> PathBuf {
    #[cfg(unix)]
    {
        resource_dir
            .join("runtime")
            .join("cpython")
            .join("bin")
            .join("python3")
    }
    #[cfg(windows)]
    {
        resource_dir
            .join("runtime")
            .join("cpython")
            .join("python.exe")
    }
}

fn venv_python(venv: &Path) -> PathBuf {
    #[cfg(unix)]
    {
        venv.join("bin").join("python3")
    }
    #[cfg(windows)]
    {
        venv.join("Scripts").join("python.exe")
    }
}

fn venv_sidecar_exe(venv: &Path) -> PathBuf {
    #[cfg(unix)]
    {
        venv.join("bin").join("dpi-eval-web")
    }
    #[cfg(windows)]
    {
        venv.join("Scripts").join("dpi-eval-web.exe")
    }
}

/// Idempotently create `<app_data>/venv` from the bundled CPython and
/// wheelhouse. `status` receives `"installing"` / `"ready"`; on Err the caller
/// emits `"failed: <detail>"`.
pub fn ensure_venv(
    app_data: &Path,
    resource_dir: &Path,
    status: &dyn Fn(&str),
) -> Result<PathBuf, String> {
    let venv = app_data.join("venv");
    let wheelhouse = resource_dir.join("runtime").join("wheelhouse");
    let manifest = read_manifest(&wheelhouse)?;

    if marker_matches(&venv, &manifest.hash) && venv_sidecar_exe(&venv).exists() {
        eprintln!("[dpi-eval-desktop] venv up to date ({})", venv.display());
        status("ready");
        return Ok(venv);
    }

    status("installing");
    eprintln!("[dpi-eval-desktop] (re)building venv at {}", venv.display());
    if venv.exists() {
        std::fs::remove_dir_all(&venv).map_err(|e| format!("cannot remove stale venv: {e}"))?;
    }
    std::fs::create_dir_all(app_data).map_err(|e| format!("cannot create app data dir: {e}"))?;

    let bundled = bundled_python(resource_dir);
    if !bundled.exists() {
        return Err(format!("bundled Python not found at {}", bundled.display()));
    }
    run_step(
        "create venv",
        Command::new(&bundled).arg("-m").arg("venv").arg(&venv),
    )?;

    let py = venv_python(&venv);
    let pip_base = |cmd: &mut Command| {
        cmd.arg("-m")
            .arg("pip")
            .arg("install")
            .arg("--no-index")
            .arg("--find-links")
            .arg(&wheelhouse);
    };
    if manifest.probe {
        // Probe payload: project wheel without its heavy deps, plus just
        // enough of the web stack to serve the UI. lxml is included because
        // dpi_eval.adapter imports it at module scope (web → runner → adapter),
        // so the sidecar dies at startup without it; Task 4's wheelhouse
        // script ships the wheel (plan commit 0b4d06e).
        let mut cmd = Command::new(&py);
        pip_base(&mut cmd);
        cmd.arg("--no-deps").arg(&manifest.package);
        run_step("install project wheel (probe, --no-deps)", &mut cmd)?;

        let mut cmd = Command::new(&py);
        pip_base(&mut cmd);
        cmd.args(["fastapi", "uvicorn", "python-multipart", "lxml"]);
        run_step("install web deps (probe)", &mut cmd)?;
    } else {
        let mut cmd = Command::new(&py);
        pip_base(&mut cmd);
        cmd.arg(&manifest.package);
        run_step("install project wheel", &mut cmd)?;
    }

    write_marker(&venv, &manifest.hash)
        .map_err(|e| format!("cannot write bootstrap marker: {e}"))?;
    status("ready");
    Ok(venv)
}

/// Run a bootstrap step to completion; Err carries the step name + stderr tail.
fn run_step(what: &str, cmd: &mut Command) -> Result<(), String> {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    let out = cmd
        .stdin(Stdio::null())
        .output()
        .map_err(|e| format!("{what}: {e}"))?;
    if out.status.success() {
        Ok(())
    } else {
        let stderr = String::from_utf8_lossy(&out.stderr);
        let mut tail: Vec<&str> = stderr.lines().rev().take(6).collect();
        tail.reverse();
        Err(format!(
            "{what} failed ({}): {}",
            out.status,
            tail.join(" | ")
        ))
    }
}

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

// ---------------------------------------------------------------------------
// Spawn
// ---------------------------------------------------------------------------

/// Directory containing the venv's executables (`bin` on Unix, `Scripts` on
/// Windows) — the engine invokes `dinglehopper` by bare name via PATH lookup,
/// so the sidecar needs this directory on its PATH.
fn venv_bin_dir(venv: &Path) -> PathBuf {
    #[cfg(unix)]
    {
        venv.join("bin")
    }
    #[cfg(windows)]
    {
        venv.join("Scripts")
    }
}

/// Build the PATH env value for the sidecar child: `venv_bin` first, followed
/// by whatever PATH the app process inherited (if any).
fn sidecar_path_env(venv_bin: &Path, existing: Option<std::ffi::OsString>) -> std::ffi::OsString {
    match existing {
        Some(existing) => {
            let mut parts = vec![venv_bin.to_path_buf()];
            parts.extend(std::env::split_paths(&existing));
            std::env::join_paths(parts).expect("venv bin dir and inherited PATH form a valid PATH")
        }
        None => venv_bin.as_os_str().to_os_string(),
    }
}

/// Spawn `dpi-eval-web --no-browser` from the venv: stdout piped (sentinel),
/// stderr appended to the sidecar log, child isolated so [`shutdown`] can kill
/// its whole tree.
pub fn spawn_sidecar(venv: &Path, log_path: &Path) -> std::io::Result<Sidecar> {
    let exe = venv_sidecar_exe(venv);
    if !exe.exists() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::NotFound,
            format!("{} does not exist", exe.display()),
        ));
    }
    let log = std::fs::File::options()
        .create(true)
        .append(true)
        .open(log_path)?;

    // The engine shells out to `dinglehopper` by bare name (PATH lookup), so
    // the venv's bin dir must be on the child's PATH.
    let path_env = sidecar_path_env(&venv_bin_dir(venv), std::env::var_os("PATH"));

    let mut cmd = Command::new(&exe);
    cmd.arg("--no-browser")
        .env("PYTHONUNBUFFERED", "1")
        .env("PATH", path_env)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::from(log));

    #[cfg(unix)]
    unsafe {
        use std::os::unix::process::CommandExt;
        // New session ⇒ the child leads its own process group; killpg on its
        // pid later reaches every descendant (uvicorn workers, dinglehopper).
        cmd.pre_exec(|| {
            if libc::setsid() == -1 {
                return Err(std::io::Error::last_os_error());
            }
            Ok(())
        });
    }

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    let child = cmd.spawn()?;

    #[cfg(windows)]
    let job = {
        // Assign immediately after spawn; kill-on-close then covers the child
        // and everything it forks from here on. (The tiny window before
        // assignment closes before Python has run any code.)
        let job = job::JobHandle::new().map_err(std::io::Error::other)?;
        job.assign(&child).map_err(std::io::Error::other)?;
        job
    };

    Ok(Sidecar {
        child,
        #[cfg(windows)]
        job,
    })
}

// ---------------------------------------------------------------------------
// Handshake HTTP poll
// ---------------------------------------------------------------------------

/// Minimal `GET /` returning true on an HTTP 200 status line. Plain std TCP —
/// no HTTP client dependency for a one-line loopback check.
fn http_get_ok(host: &str, port: u16) -> bool {
    use std::net::{TcpStream, ToSocketAddrs};
    let Ok(mut addrs) = (host, port).to_socket_addrs() else {
        return false;
    };
    let Some(addr) = addrs.next() else {
        return false;
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_millis(400)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
    let request = format!("GET / HTTP/1.1\r\nHost: {host}:{port}\r\nConnection: close\r\n\r\n");
    if std::io::Write::write_all(&mut stream, request.as_bytes()).is_err() {
        return false;
    }
    let mut buf = [0u8; 64];
    let Ok(n) = std::io::Read::read(&mut stream, &mut buf) else {
        return false;
    };
    let head = String::from_utf8_lossy(&buf[..n]);
    head.starts_with("HTTP/1.1 200") || head.starts_with("HTTP/1.0 200")
}

// ---------------------------------------------------------------------------
// Shutdown
// ---------------------------------------------------------------------------

/// Kill the sidecar's whole process tree. Idempotent (the slot is taken), so
/// wiring it to ExitRequested, Exit, and the signal watcher is safe.
pub fn shutdown() {
    let Some(mut sidecar) = SIDECAR.lock().unwrap().take() else {
        return;
    };

    #[cfg(unix)]
    {
        let pgid = sidecar.child.id() as i32;
        eprintln!("[dpi-eval-desktop] shutting down sidecar process group {pgid}");
        unsafe {
            let _ = libc::killpg(pgid, libc::SIGTERM);
        }
        let deadline = Instant::now() + TERM_GRACE;
        loop {
            if matches!(sidecar.child.try_wait(), Ok(Some(_))) {
                break;
            }
            if Instant::now() >= deadline {
                eprintln!("[dpi-eval-desktop] sidecar still alive after {TERM_GRACE:?}; SIGKILL");
                unsafe {
                    let _ = libc::killpg(pgid, libc::SIGKILL);
                }
                let _ = sidecar.child.wait();
                break;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
    }

    #[cfg(windows)]
    {
        // Dropping the Job handle closes it; JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        // terminates every process in the job.
        drop(sidecar.job);
        let _ = sidecar.child.wait();
    }
}

/// Unix: SIGTERM/SIGINT do not reach Tauri's run loop (the default signal
/// disposition would kill the process before `RunEvent::Exit` fires), so a
/// plain `kill` of the app would orphan the sidecar tree. Block both signals
/// process-wide and consume them on a watcher thread that tree-kills the
/// sidecar first. Must be called at the very top of `main`, before any other
/// thread exists, so every later thread inherits the mask.
///
/// Windows needs no equivalent: the OS closes the Job handle when the app
/// process dies, and kill-on-close takes the tree down even after a hard kill.
#[cfg(unix)]
pub fn install_signal_watcher() {
    unsafe {
        let mut set: libc::sigset_t = std::mem::zeroed();
        libc::sigemptyset(&mut set);
        libc::sigaddset(&mut set, libc::SIGTERM);
        libc::sigaddset(&mut set, libc::SIGINT);
        libc::pthread_sigmask(libc::SIG_BLOCK, &set, std::ptr::null_mut());
        std::thread::spawn(move || {
            let mut sig: libc::c_int = 0;
            if libc::sigwait(&set, &mut sig) == 0 {
                eprintln!("[dpi-eval-desktop] signal {sig} received; killing sidecar tree");
                shutdown();
                std::process::exit(128 + sig);
            }
        });
    }
}

#[cfg(not(unix))]
pub fn install_signal_watcher() {}

// ---------------------------------------------------------------------------
// Windows Job Object plumbing
// ---------------------------------------------------------------------------

#[cfg(windows)]
mod job {
    use std::os::windows::io::AsRawHandle;
    use windows::Win32::Foundation::{CloseHandle, HANDLE};
    use windows::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };

    pub struct JobHandle(HANDLE);

    // SAFETY: HANDLE is a raw pointer newtype; the job handle may be moved
    // across threads and is only closed once, in Drop.
    unsafe impl Send for JobHandle {}

    impl JobHandle {
        pub fn new() -> windows::core::Result<Self> {
            unsafe {
                let job = CreateJobObjectW(None, None)?;
                let mut info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
                info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
                SetInformationJobObject(
                    job,
                    JobObjectExtendedLimitInformation,
                    &info as *const _ as *const core::ffi::c_void,
                    std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                )?;
                Ok(Self(job))
            }
        }

        pub fn assign(&self, child: &std::process::Child) -> windows::core::Result<()> {
            unsafe { AssignProcessToJobObject(self.0, HANDLE(child.as_raw_handle() as _)) }
        }
    }

    impl Drop for JobHandle {
        fn drop(&mut self) {
            unsafe {
                let _ = CloseHandle(self.0);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sentinel_parses_the_exact_line() {
        assert_eq!(
            parse_sentinel("dpi-eval-web running at http://127.0.0.1:8765"),
            Some("http://127.0.0.1:8765".to_string())
        );
    }

    #[test]
    fn sentinel_ignores_other_lines() {
        assert_eq!(parse_sentinel("Done? Close the browser tab"), None);
        assert_eq!(parse_sentinel(""), None);
    }

    #[test]
    fn sidecar_path_env_prepends_venv_bin_before_existing_path() {
        let venv_bin = PathBuf::from("/fake/venv/bin");
        let existing = std::ffi::OsString::from("/usr/bin:/bin");
        let result = sidecar_path_env(&venv_bin, Some(existing));

        let parts: Vec<PathBuf> = std::env::split_paths(&result).collect();
        assert_eq!(
            parts,
            vec![
                venv_bin.clone(),
                PathBuf::from("/usr/bin"),
                PathBuf::from("/bin"),
            ]
        );
    }

    #[test]
    fn sidecar_path_env_handles_missing_existing_path() {
        let venv_bin = PathBuf::from("/fake/venv/bin");
        let result = sidecar_path_env(&venv_bin, None);

        let parts: Vec<PathBuf> = std::env::split_paths(&result).collect();
        assert_eq!(parts, vec![venv_bin]);
    }

    #[test]
    fn bootstrap_marker_roundtrip() {
        let dir = std::env::temp_dir().join("dpi-eval-marker-test");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        assert!(!marker_matches(&dir, "hash-1"));
        write_marker(&dir, "hash-1").unwrap();
        assert!(marker_matches(&dir, "hash-1"));
        assert!(!marker_matches(&dir, "hash-2")); // wheelhouse changed → rebuild
    }

    /// Full bootstrap against a real payload dir. Opt-in (`cargo test -- --ignored`)
    /// because it needs `DPI_EVAL_TEST_RESOURCES` pointing at a directory with the
    /// Task 4 layout: `runtime/cpython/` (real CPython) and `runtime/wheelhouse/`
    /// (wheels + MANIFEST). Leaves the built venv behind at
    /// `<tmp>/dpi-eval-bootstrap-test/venv` so a live app run can reuse it via
    /// DPI_EVAL_DESKTOP_VENV; reruns clean up first.
    #[test]
    #[ignore = "needs DPI_EVAL_TEST_RESOURCES pointing at a runtime payload"]
    fn ensure_venv_bootstraps_rebuilds_and_short_circuits() {
        let resources = PathBuf::from(
            std::env::var("DPI_EVAL_TEST_RESOURCES").expect("set DPI_EVAL_TEST_RESOURCES"),
        );
        let app_data = std::env::temp_dir().join("dpi-eval-bootstrap-test");
        let _ = std::fs::remove_dir_all(&app_data);

        let statuses = Mutex::new(Vec::<String>::new());
        let record = |s: &str| statuses.lock().unwrap().push(s.to_string());

        // Cold start: full install.
        let venv = ensure_venv(&app_data, &resources, &record).unwrap();
        assert!(
            venv_sidecar_exe(&venv).exists(),
            "dpi-eval-web entry point missing"
        );
        assert_eq!(*statuses.lock().unwrap(), ["installing", "ready"]);

        // Warm start: marker short-circuits, no reinstall.
        statuses.lock().unwrap().clear();
        ensure_venv(&app_data, &resources, &record).unwrap();
        assert_eq!(*statuses.lock().unwrap(), ["ready"]);

        // Stale marker (wheelhouse changed): delete-and-rebuild.
        write_marker(&venv, "stale-hash").unwrap();
        statuses.lock().unwrap().clear();
        ensure_venv(&app_data, &resources, &record).unwrap();
        assert_eq!(*statuses.lock().unwrap(), ["installing", "ready"]);
        let manifest = std::fs::read_to_string(
            resources
                .join("runtime")
                .join("wheelhouse")
                .join("MANIFEST"),
        )
        .unwrap();
        let hash = manifest.lines().nth(1).unwrap().trim();
        assert!(marker_matches(&venv, hash));
    }
}
