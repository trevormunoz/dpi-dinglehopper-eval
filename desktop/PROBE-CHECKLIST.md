# dpi-eval desktop probe — test checklist

**What this is.** A one-time test of whether an *unsigned* dpi-eval desktop
app can be installed and launched on a managed HDC lab machine **without
admin rights and without a terminal**. We are testing the machine's
policies as much as the app. "It refused to run" is a *successful test
result* — please record it, don't work around it with an admin account.

**Artifacts** (from CI run
github.com/trevormunoz/dpi-dinglehopper-eval/actions/runs/29601715549;
downloading requires a GitHub login, so Trevor downloads both and hands
the Windows installer to the Windows tester directly):

- macOS: `dpi-eval_0.1.0_aarch64.dmg` (Apple Silicon only — an Intel Mac
  cannot run it; if the lab Mac is Intel, record that and stop)
- Windows: `dpi-eval_0.1.0_x64-setup.exe`

**Ground rules for both testers**

- Use a normal student/staff account. Never enter admin credentials —
  if any step demands them, that IS the finding: screenshot it, stop.
- Never open a terminal/PowerShell.
- The app has no OCR engine in this build: after setup, grading any
  folder will show a red "pages failed" banner. **That is expected** —
  the probe tests install/launch, not grading.
- Nothing you do sends any file off the machine; the app talks only to
  the machine itself (localhost).

---

## Part A — macOS (Trevor)

1. Copy the `.dmg` to the lab Mac (USB/AirDrop/download — whatever a
   student could do). Open it; drag **dpi-eval** into your **home**
   `Applications` folder (make `~/Applications` in Finder if it doesn't
   exist). Do NOT use the system `/Applications`.
2. Double-click the app. Expect macOS to claim the app **"is damaged and
   can't be opened"** — it isn't; that's how macOS words "unsigned."
   Screenshot the exact dialog.
3. Open System Settings → Privacy & Security, scroll to the blocked-app
   notice, click **Open Anyway**, confirm. (If there is no Open Anyway —
   MDM may remove it — that's the finding; screenshot, stop.)
4. On launch: a window saying "Setting up…" should appear, then within a
   minute or so the **Grade OCR against ground truth** form. Time it
   roughly.
5. Quit the app (⌘Q). Relaunch — it should reach the form much faster.
   Quit again.
6. Record (template below): machine model/OS version, security software
   if known, each dialog seen, timings, outcome.

## Part B — Windows (colleague — no project context needed)

You've been handed a file `dpi-eval_0.1.0_x64-setup.exe`. It's a small
test app from UMD Libraries' digitization group; the test takes ~10
minutes. Please use your normal (non-admin) account throughout.

1. Double-click the installer. Windows SmartScreen will likely show
   **"Windows protected your PC."** Click **More info → Run anyway**.
   Screenshot the dialog first. (If "Run anyway" isn't offered, or the
   file was deleted/quarantined the moment it landed — screenshot
   whatever you see and stop; that's a valid result.)
2. The installer should complete **without asking for an admin
   password**. If it asks (UAC prompt), screenshot, cancel, stop.
3. Launch **dpi-eval** from the Start menu. A window saying
   "Setting up…" should appear, then within a minute or so a form titled
   **Grade OCR against ground truth**. Note roughly how long it took.
4. Close the window. Launch it once more — it should open much faster.
   Close it.
5. If your antivirus shows any warning at any point, screenshot it.
6. Fill in the template below and send it back with your screenshots.

## Recording template (one per machine)

    Tester:
    Date:
    Machine (model / OS version):
    Security software (if known — Defender, CrowdStrike, etc.):
    Install: OK / blocked (how?)
    First-run approval: which dialogs, exact wording if odd
    Setup→form time (first launch):
    Second launch: faster? (yes/no)
    Any AV/quarantine events:
    Verdict: ran fine / ran with friction / blocked
    Screenshots attached: (list)

## What happens with the results

- **Both pass** → the real build proceeds on both platforms.
- **Friction only** (scary dialogs but a student *could* get through) →
  we weigh code-signing before piloting.
- **Hard block** (AV quarantine, MDM install ban, no Open Anyway) → the
  desktop app stops here for that platform; the existing `uvx` command
  path remains the supported route. Either way the result gets a
  findings entry — no result is a wasted test.
