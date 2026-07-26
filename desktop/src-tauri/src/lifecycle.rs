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
use std::sync::atomic::{AtomicBool, Ordering};
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

/// Env var carrying the per-launch token into the sidecar. The sidecar
/// requires it on `/grade-paths` (403 otherwise) and embeds it in the served
/// form page; absent env ⇒ the endpoint is refused entirely (plain uvx mode).
pub const TOKEN_ENV: &str = "DPI_EVAL_TOKEN";

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

/// The per-launch sidecar token: 16 OS-random bytes rendered as 32 lowercase
/// hex chars. Generated once per process (via `OnceLock`) so the value is
/// stable for the whole app session — every sidecar spawn and the served page
/// see the same token. Source is `getrandom` (OS CSPRNG); a low-entropy source
/// (e.g. a `SystemTime`+pid hash) would be guessable and defeat the localhost
/// token guard this exists to provide.
pub fn session_token() -> &'static str {
    static TOKEN: std::sync::OnceLock<String> = std::sync::OnceLock::new();
    TOKEN.get_or_init(|| {
        let mut bytes = [0u8; 16];
        getrandom::getrandom(&mut bytes).expect("OS RNG available for session token");
        bytes.iter().map(|b| format!("{b:02x}")).collect()
    })
}

/// Pick a non-colliding path for a download in `dir`.
///
/// Returns `dir/filename` when nothing there matches `exists`; otherwise
/// appends `" (1)"`, `" (2)"`, ... before the extension (`report (1).zip`)
/// until a free name is found. `exists` is injected so the collision check is
/// pure and testable; production passes `|p| p.exists()`. Mirrors the Finder /
/// browser "keep both" behaviour instead of overwriting.
pub fn dedupe_download_path(
    dir: &Path,
    filename: &str,
    exists: impl Fn(&Path) -> bool,
) -> PathBuf {
    let first = dir.join(filename);
    if !exists(&first) {
        return first;
    }
    let name = Path::new(filename);
    let stem = name
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or(filename);
    let ext = name.extension().and_then(|s| s.to_str());
    for n in 1u32.. {
        let candidate = match ext {
            Some(ext) => format!("{stem} ({n}).{ext}"),
            None => format!("{stem} ({n})"),
        };
        let path = dir.join(candidate);
        if !exists(&path) {
            return path;
        }
    }
    unreachable!("u32 counter exhausted while deduplicating {filename}")
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

/// Set once [`shutdown`] has been asked for (window close, app exit, or
/// SIGTERM/SIGINT). Startup failures that are really just "the user quit while
/// we were still booting" consult this instead of raising an error dialog after
/// exit was already requested.
static SHUTDOWN_REQUESTED: AtomicBool = AtomicBool::new(false);

fn shutdown_requested() -> bool {
    SHUTDOWN_REQUESTED.load(Ordering::SeqCst)
}

/// The bootstrap step currently running, if any — its process group (unix) or
/// its Job Object (windows). Separate from [`SIDECAR`] because the two never
/// overlap in time and the bootstrap child is owned by [`run_step`]'s own thread.
#[cfg(unix)]
static BOOTSTRAP_STEP: Mutex<Option<i32>> = Mutex::new(None);
#[cfg(windows)]
static BOOTSTRAP_STEP: Mutex<Option<job::JobHandle>> = Mutex::new(None);

// ---------------------------------------------------------------------------
// Entry point (called from `setup` on a worker thread)
// ---------------------------------------------------------------------------

pub fn run(app: AppHandle) {
    let log_path = sidecar_log_path(&app);
    if let Err(detail) = run_inner(&app, &log_path) {
        eprintln!("[dpi-eval-desktop] startup failed: {detail}");
        // Was the app already quitting when this failed? Read before our own
        // cleanup sets the flag.
        let quitting = shutdown_requested();
        // Every failure path after the sidecar is spawned leaves a server
        // listening on loopback with the launch token. Take the tree down before
        // telling the user we could not start; target machines have no terminal
        // for them to clean up by hand.
        shutdown();
        if quitting {
            // The user asked to exit; an error modal raised after that is noise
            // they cannot act on.
            return;
        }
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
    // Record the sidecar before anything that can fail: `std::process::Child`
    // has no killing `Drop`, so an early return here would leave a listening,
    // token-bearing server with no handle for `shutdown` to reach.
    let stdout = sidecar.child.stdout.take();
    *SIDECAR.lock().unwrap() = Some(sidecar);
    let stdout = stdout.ok_or_else(|| "sidecar stdout was not piped".to_string())?;

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
        drain_lines(stdout, |line| {
            if let Some(log) = log.as_mut() {
                let _ = writeln!(log, "{line}");
            }
            // Ignore send errors: once the handshake drops the receiver we keep
            // draining so the sidecar's stdout pipe never fills up.
            let _ = tx.send(line);
        });
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

/// Read `source` line by line, decoding each line lossily, and hand every line
/// to `on_line`. Returns at EOF or on a genuine read error.
///
/// Deliberately not `BufRead::lines()`: that yields `Err(InvalidData)` for a
/// single non-UTF-8 byte anywhere in the stream. Treating that as end-of-stream
/// both misreports a healthy sidecar ("closed stdout before announcing its URL")
/// and stops draining stdout, which would eventually fill the pipe and block the
/// sidecar's own writes. One stray byte in a traceback or a filename must not
/// abort startup.
fn drain_lines(source: impl std::io::Read, mut on_line: impl FnMut(String)) {
    let mut reader = BufReader::new(source);
    let mut buf = Vec::new();
    loop {
        buf.clear();
        match reader.read_until(b'\n', &mut buf) {
            Ok(0) => return, // EOF
            Ok(_) => {}
            Err(e) => {
                eprintln!("[dpi-eval-desktop] error reading sidecar stdout: {e}");
                return;
            }
        }
        while matches!(buf.last(), Some(b'\n' | b'\r')) {
            buf.pop();
        }
        on_line(String::from_utf8_lossy(&buf).into_owned());
    }
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

/// Err unless a sidecar is recorded *and* still running.
///
/// An empty slot is a failure, not health: the handshake only calls this after
/// registration, so `None` means [`shutdown`] has already taken the sidecar
/// (the user is quitting). Reporting "alive" there made the handshake poll a
/// dead port for the rest of its 60 s budget and then raise a modal dialog.
fn check_alive() -> Result<(), String> {
    let mut guard = SIDECAR.lock().unwrap();
    let Some(sidecar) = guard.as_mut() else {
        return Err("dpi-eval-web is no longer running".into());
    };
    match sidecar.child.try_wait() {
        Ok(None) => Ok(()),
        Ok(Some(status)) => Err(format!("dpi-eval-web exited during startup ({status})")),
        // A failing waitpid is not evidence of health.
        Err(e) => Err(format!("cannot check on dpi-eval-web: {e}")),
    }
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
///
/// Bootstrap steps get the same tree-kill treatment as the sidecar: `python -m
/// venv` and the `pip install` runs are the longest window in the whole
/// lifecycle (minutes on a cold start), and quitting mid-install must not leave
/// pip writing into `<app_data>/venv`. The bootstrap marker is written only
/// after the last step succeeds, so an orphan surviving here would still be
/// unpacking wheels while the *next* launch's `remove_dir_all` tore the tree out
/// from under it.
fn run_step(what: &str, cmd: &mut Command) -> Result<(), String> {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    #[cfg(unix)]
    configure_child(cmd);

    // Capture both streams (as `Command::output` did) so pip's chatter stays out
    // of the app's own stdio; only the stderr tail is reported.
    cmd.stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    // Windows: create the job *before* spawning, so the only thing that can fail
    // with a live unregistered child is the assignment itself.
    #[cfg(windows)]
    let job =
        job::JobHandle::new().map_err(|e| format!("{what}: cannot create job object: {e}"))?;

    #[allow(unused_mut)]
    let mut child = cmd.spawn().map_err(|e| format!("{what}: {e}"))?;

    #[cfg(unix)]
    {
        // `configure_child` made the child its own process-group leader, so its
        // pid doubles as the pgid `shutdown` kills.
        *BOOTSTRAP_STEP.lock().unwrap() = Some(child.id() as i32);
    }
    #[cfg(windows)]
    {
        if let Err(e) = job.assign(&child) {
            let _ = child.kill();
            let _ = child.wait();
            return Err(format!("{what}: cannot assign job object: {e}"));
        }
        *BOOTSTRAP_STEP.lock().unwrap() = Some(job);
    }

    let waited = child.wait_with_output().map_err(|e| format!("{what}: {e}"));
    // Deregister before inspecting the result: the child is reaped, so the pid
    // (and hence the pgid) may be reused from here on. On windows dropping the
    // taken `JobHandle` closes the now-empty job.
    let _taken = BOOTSTRAP_STEP.lock().unwrap().take();
    let out = waited?;

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

/// An all-clear signal set, computed in the parent so a `pre_exec` closure can
/// install it with a single async-signal-safe call.
#[cfg(unix)]
fn empty_sigset() -> libc::sigset_t {
    // SAFETY: `sigset_t` is a plain bitset/array; zeroing then `sigemptyset`ing
    // it is the portable way to obtain an initialised empty set.
    unsafe {
        let mut set: libc::sigset_t = std::mem::zeroed();
        libc::sigemptyset(&mut set);
        set
    }
}

/// Unix child setup shared by the sidecar and every bootstrap step.
///
/// 1. New session, so the child leads its own process group and a later
///    `killpg` reaches every descendant (uvicorn workers, `dinglehopper`).
/// 2. Empty signal mask. [`install_signal_watcher`] blocks SIGTERM/SIGINT for
///    the whole app process, and a signal mask survives fork+execve, so without
///    this reset the child would start with both signals blocked — [`shutdown`]'s
///    `killpg(SIGTERM)` would be ignored, uvicorn's graceful shutdown would never
///    run, and every quit would end in SIGKILL.
#[cfg(unix)]
fn configure_child(cmd: &mut Command) {
    use std::os::unix::process::CommandExt;
    // Built here, in the parent, so the closure body stays allocation-free.
    let empty = empty_sigset();
    // SAFETY: the closure runs in the forked child between fork and execve, so
    // it may only make async-signal-safe calls and must not allocate or lock.
    // `setsid` and `pthread_sigmask` are both async-signal-safe, and `empty` is
    // a plain `Copy` bitset captured by value.
    unsafe {
        cmd.pre_exec(move || {
            if libc::setsid() == -1 {
                return Err(std::io::Error::last_os_error());
            }
            // pthread_sigmask returns the errno rather than setting it.
            let rc = libc::pthread_sigmask(libc::SIG_SETMASK, &empty, std::ptr::null_mut());
            if rc != 0 {
                return Err(std::io::Error::from_raw_os_error(rc));
            }
            Ok(())
        });
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
        // Per-launch token gating /grade-paths (see TOKEN_ENV).
        .env(TOKEN_ENV, session_token())
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::from(log));

    #[cfg(unix)]
    configure_child(&mut cmd);

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    // Create the job *before* spawning: a failure here must not leave a spawned
    // child unregistered, since `Child` has no killing `Drop`.
    #[cfg(windows)]
    let job = job::JobHandle::new().map_err(std::io::Error::other)?;

    #[allow(unused_mut)]
    let mut child = cmd.spawn()?;

    #[cfg(windows)]
    {
        // Assign immediately after spawn; kill-on-close then covers the child
        // and everything it forks from here on. (The tiny window before
        // assignment closes before Python has run any code.) If assignment
        // fails we own a live, unregistered child — kill it rather than orphan a
        // server that is about to start listening with the launch token.
        if let Err(e) = job.assign(&child) {
            let _ = child.kill();
            let _ = child.wait();
            return Err(std::io::Error::other(e));
        }
    }

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

/// Kill whatever child tree we own — an in-flight bootstrap step, or the
/// running sidecar. Idempotent (both slots are taken), so wiring it to
/// ExitRequested, Exit, the signal watcher, and startup failure is safe.
pub fn shutdown() {
    SHUTDOWN_REQUESTED.store(true, Ordering::SeqCst);
    kill_bootstrap_step();

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

/// Kill an in-flight bootstrap step (`python -m venv` / `pip install`) and its
/// descendants.
///
/// Unix sends SIGTERM only, and does not wait: `run_step`'s own thread owns the
/// child and reaps it, so there is nothing here to `wait` for, and a follow-up
/// SIGKILL could land on a recycled pgid. Neither `venv` nor `pip` installs a
/// SIGTERM handler, so the default disposition ends them promptly.
fn kill_bootstrap_step() {
    #[cfg(unix)]
    if let Some(pgid) = BOOTSTRAP_STEP.lock().unwrap().take() {
        eprintln!("[dpi-eval-desktop] terminating bootstrap process group {pgid}");
        unsafe {
            let _ = libc::killpg(pgid, libc::SIGTERM);
        }
    }

    #[cfg(windows)]
    if let Some(job) = BOOTSTRAP_STEP.lock().unwrap().take() {
        // Closing the handle triggers JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.
        eprintln!("[dpi-eval-desktop] terminating bootstrap job object");
        drop(job);
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
        let inherited = [PathBuf::from("/usr/bin"), PathBuf::from("/bin")];
        // Build the input with join_paths so the test uses the platform's
        // PATH separator (':' Unix, ';' Windows) rather than hardcoding ':'.
        let existing = std::env::join_paths(inherited.iter()).unwrap();
        let result = sidecar_path_env(&venv_bin, Some(existing));

        let parts: Vec<PathBuf> = std::env::split_paths(&result).collect();
        assert_eq!(
            parts,
            vec![venv_bin.clone(), inherited[0].clone(), inherited[1].clone()]
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
    fn session_token_is_32_lowercase_hex_and_stable() {
        let token = session_token();
        assert_eq!(token.len(), 32, "token must be 32 hex chars");
        assert!(
            token
                .chars()
                .all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase()),
            "token must be lowercase hex: {token}"
        );
        // OnceLock ⇒ the value is stable for the whole process/session.
        assert_eq!(token, session_token());
    }

    #[test]
    fn dedupe_download_path_suffixes_only_on_collision() {
        let dir = Path::new("/downloads");

        // No collision → the plain name in the target dir.
        let free = dedupe_download_path(dir, "report.zip", |_| false);
        assert_eq!(free, PathBuf::from("/downloads/report.zip"));

        // First name taken → " (1)" before the extension.
        let taken = [PathBuf::from("/downloads/report.zip")];
        let one = dedupe_download_path(dir, "report.zip", |p| taken.contains(&p.to_path_buf()));
        assert_eq!(one, PathBuf::from("/downloads/report (1).zip"));

        // (1) also taken → keep counting.
        let taken = [
            PathBuf::from("/downloads/report.zip"),
            PathBuf::from("/downloads/report (1).zip"),
        ];
        let two = dedupe_download_path(dir, "report.zip", |p| taken.contains(&p.to_path_buf()));
        assert_eq!(two, PathBuf::from("/downloads/report (2).zip"));

        // Extensionless name → suffix with no dot.
        let taken = [PathBuf::from("/downloads/archive")];
        let noext = dedupe_download_path(dir, "archive", |p| taken.contains(&p.to_path_buf()));
        assert_eq!(noext, PathBuf::from("/downloads/archive (1)"));
    }

    /// A single non-UTF-8 byte on sidecar stdout must not abandon the stream:
    /// the bad line is decoded lossily and later lines (including the sentinel)
    /// still arrive. `BufRead::lines()` fails this — it yields
    /// `Err(InvalidData)`, which used to be read as "the sidecar closed stdout".
    #[test]
    fn drain_lines_survives_invalid_utf8_and_keeps_reading() {
        let input: &[u8] =
            b"starting\nlatin-1 caf\xe9\ndpi-eval-web running at http://127.0.0.1:8765\nbye\n";
        let mut lines = Vec::new();
        drain_lines(input, |line| lines.push(line));

        assert_eq!(lines.len(), 4, "every line must survive: {lines:?}");
        assert_eq!(lines[0], "starting");
        assert!(
            lines[1].starts_with("latin-1 caf"),
            "bad bytes decode lossily, not fatally: {:?}",
            lines[1]
        );
        assert_eq!(
            parse_sentinel(&lines[2]),
            Some("http://127.0.0.1:8765".to_string()),
            "the sentinel after the bad line must still be seen"
        );
        assert_eq!(lines[3], "bye");
    }

    #[test]
    fn drain_lines_strips_crlf_and_yields_a_final_unterminated_line() {
        let mut lines = Vec::new();
        drain_lines(&b"one\r\ntwo"[..], |line| lines.push(line));
        assert_eq!(lines, vec!["one".to_string(), "two".to_string()]);
    }

    /// `main` blocks SIGTERM/SIGINT process-wide so a watcher thread can
    /// tree-kill the sidecar first. That mask survives fork+execve, so without
    /// an explicit reset the sidecar (and everything it forks) ignores the
    /// SIGTERM `shutdown` sends. Verified behaviourally: a child that signals
    /// itself must die, not print.
    #[cfg(unix)]
    #[test]
    fn child_does_not_inherit_a_blocked_signal_mask() {
        use std::os::unix::process::ExitStatusExt;

        let mut blocked = empty_sigset();
        let mut previous = empty_sigset();
        unsafe {
            libc::sigaddset(&mut blocked, libc::SIGTERM);
            assert_eq!(
                libc::pthread_sigmask(libc::SIG_BLOCK, &blocked, &mut previous),
                0
            );
        }

        let mut cmd = Command::new("/bin/sh");
        cmd.arg("-c").arg("kill -TERM $$; echo SURVIVED");
        configure_child(&mut cmd);
        let out = cmd.output().expect("/bin/sh is spawnable");

        // Restore this thread's mask before asserting, so a failure cannot
        // leave the rest of the test binary with SIGTERM blocked.
        unsafe {
            libc::pthread_sigmask(libc::SIG_SETMASK, &previous, std::ptr::null_mut());
        }

        let stdout = String::from_utf8_lossy(&out.stdout);
        assert!(
            !stdout.contains("SURVIVED"),
            "child ran past its own SIGTERM, so the signal was blocked: {stdout:?}"
        );
        assert_eq!(
            out.status.signal(),
            Some(libc::SIGTERM),
            "child should have been terminated by SIGTERM, got {:?}",
            out.status
        );
    }

    /// `shutdown` reaches descendants via `killpg`, which only works if the
    /// child leads its own process group.
    #[cfg(unix)]
    #[test]
    fn child_leads_its_own_process_group() {
        let mut cmd = Command::new("/bin/sh");
        cmd.arg("-c")
            .arg("exec sleep 30")
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        configure_child(&mut cmd);
        let mut child = cmd.spawn().expect("/bin/sh is spawnable");
        let pid = child.id() as i32;

        let pgid = unsafe { libc::getpgid(pid) };
        unsafe {
            libc::killpg(pid, libc::SIGKILL);
        }
        let _ = child.wait();

        assert_eq!(pgid, pid, "child must be its own process-group leader");
    }

    /// `check_alive` is the handshake's liveness gate. With no sidecar recorded
    /// there is nothing to hand a URL to, so reporting "alive" makes the
    /// handshake poll a dead port for the rest of its 60 s budget.
    #[test]
    fn check_alive_errors_when_no_sidecar_is_recorded() {
        // The slot is process-global; no other test registers a sidecar.
        assert!(SIDECAR.lock().unwrap().is_none());
        assert!(
            check_alive().is_err(),
            "an empty sidecar slot is not a healthy sidecar"
        );
    }

    /// Startup-failure reporting must stay quiet once the app is quitting:
    /// otherwise cancelling during bootstrap raises a modal error dialog after
    /// exit was already requested.
    #[test]
    fn shutdown_marks_the_process_as_quitting() {
        assert!(!shutdown_requested(), "flag starts clear");
        shutdown();
        assert!(shutdown_requested(), "shutdown must record the intent");
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
