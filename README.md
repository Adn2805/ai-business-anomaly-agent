# AI Business Anomaly Agent

A lightweight watcher for daily business metrics in Excel. It checks the latest reporting date, explains unusual movements, writes HTML and text reports, and submits SMTP alerts when attention is needed.

**Deployment status:** locally implemented and verified; not published or running unattended. The public GitHub Actions workflow is prepared for synthetic dry-run demonstrations only. Its daily job is disabled unless explicitly enabled. The private persistence adapter and workflow template are implemented and locally tested; remote setup, hosted verification and live-email authorization remain pending. Licensed under [MIT](LICENSE), selected by the project owner.

The operating workflow is: a fresh Excel export arrives, the daily scheduled run checks it, and unusual changes trigger an email for someone to investigate. Reports support that notification workflow. Continuous watching in this MVP means recurring daily checks; the application is a one-shot CLI invoked by cron, not a filesystem event listener.

## Business problem and objective

Teams often discover unusual revenue, cost or refund movements only after a manager manually checks a spreadsheet. This application automates that review so teams can investigate sooner. It provides transparent comparisons and cautious business explanations, with persistent alert history to make daily reruns practical.

The name describes automated monitoring. This MVP uses statistical rules and rule-based language, with no generative AI service, machine learning model, paid API, web dashboard or account system.

## Features and technology

- Strict Excel validation, date ordering and complete daily baseline checks.
- The same configurable moving-average rule across all six metrics.
- Dynamic explanations, attention indicators, HTML and plain-text reports.
- Secure SMTP submission with multiple recipients and explicit dry-run.
- SQLite attempt history, retries after failure and suppression of successfully submitted identical alerts.
- Cross-process file lock, UTC technical logs, meaningful exit codes and atomic individual report replacement.
- Python 3.12, openpyxl, Decimal arithmetic, SQLite, smtplib, filelock, python-dotenv and Pytest.
- Non-root Docker image, persistent host mounts and host cron scheduling.

## Input contract

Use the **first worksheet**, with exact column names in row 1. Additional columns and worksheets are ignored. Completely blank rows are ignored; partially populated records fail validation. Save numeric values rather than formulas.

| Column | Definition | Accepted values |
| --- | --- | --- |
| Date | Daily business reporting date | Excel date at midnight or exact `YYYY-MM-DD` text |
| Revenue | Total revenue | Nonnegative finite number |
| Orders | Number of orders | Nonnegative finite number |
| Conversion_Rate | Conversion rate in percentage points | Number from 0 to 100; **3.5 means 3.5%** |
| Traffic | Total visits or sessions | Nonnegative finite number |
| Cost | Business or marketing cost | Nonnegative finite number |
| Refunds | Refunded monetary amount | Nonnegative finite number |

Use a consistent monetary currency across rows. Numeric strings, Excel errors, formulas, missing required values, duplicate required headers, duplicate dates and timestamps with non-midnight times are rejected. Duplicate dates are never aggregated. Conversion cells using Excel `%` formatting are rejected because Excel stores these as fractions; export plain numeric percentage points instead. A plain numeric `0.035` means **0.035%**, not 3.5%; no unit guessing occurs.

All records are validated before any report or email is generated. Invalid data exits nonzero without sending an alert. Existing reports remain historical outputs; a failed run does not overwrite them with a normal status.

`data/sample_business_data.xlsx` contains **35 synthetic daily records**, October 1–November 4, 2026, with deliberate anomalies on October 15, October 22 and November 4. The workbook labels itself synthetic. Only the latest date is evaluated; older anomalies illustrate the data, rather than triggering historical backfill alerts.

## Detection and business interpretation

1. Sort valid observations by date and select the latest reporting date.
2. Require the configured number of complete, consecutive daily observations immediately before it (default 7). A gap within this window fails safely. Older gaps outside the selected window do not affect analysis.
3. Calculate each metric's mean using only those previous observations.
4. Calculate `((current - baseline) / baseline) * 100`.
5. Flag `abs(percentage_change) >= ANOMALY_THRESHOLD` (default 20%). Comparisons use unrounded Decimal values; display values are rounded to two decimals.

With a zero baseline, current zero is unchanged and not anomalous. A positive current value is an anomalous baseline-zero increase. In both cases percentage change is explicitly undefined; infinity is never displayed. Conversion-rate movements are **relative percentages**, while the current/baseline/difference values remain percentage points. Absolute difference is the nonnegative magnitude; direction supplies the sign.

Revenue, Orders, Conversion_Rate or Traffic decreases and Cost or Refunds increases are described as potentially unfavorable. Other anomalies receive neutral wording. Explanations describe possible implications, never a proven cause. The report includes all six metrics even when none is anomalous.

## Architecture and project structure

```text
Excel → strict validation → latest-date moving average → findings
      → business summary → HTML/text reports → SMTP decision → SQLite history
          [one shared process lock protects the complete run]

ai-business-anomaly-agent/
  app/
    __init__.py
    main.py                 # CLI and run orchestration
    config.py               # environment settings
    data_loader.py          # strict input contract
    anomaly_detector.py     # structured findings and interpretation
    summarizer.py           # dynamic concise summary
    report_generator.py     # HTML/text rendering and saving
    email_alert.py           # MIME message and secure SMTP
    alert_history.py         # SQLite attempts and signatures
    private_store.py         # private GitHub file API with conditional writes
    private_operations.py    # durable checkpoints and explicit recovery
  data/sample_business_data.xlsx
  tests/
    conftest.py
    test_data_loader.py
    test_anomaly_detector.py
    test_summarizer.py
    test_email_alert.py
    test_alert_history.py
    test_main.py
    test_private_store.py
    test_private_operations.py
  reports/                  # created at runtime, ignored by Git
  state/                    # created at runtime, ignored by Git
  requirements.txt
  requirements-dev.txt
  .env.example
  .gitignore
  .dockerignore
  Dockerfile
  docker-compose.yml
  .github/workflows/daily-monitor.yml
  operations/private-monitor.yml  # copy into the private repository only
  LICENSE
  README.md
```

## Local setup and execution

Run commands from this project directory. Python 3.12 is the tested version.

```bash
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell instead:
# .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
cp .env.example .env
# PowerShell alternative: Copy-Item .env.example .env
python -m app.main --dry-run
python -m pytest -q
```

For runtime-only installations use `requirements.txt`. If a restricted environment prevents Pytest from writing to its normal temporary directory, use `python -m pytest -q --basetemp .pytest-tmp-local` (this directory is disposable and Pytest may clear it).

```bash
# Default input comes from EXCEL_PATH:
python -m app.main
# Choose another input without editing source:
python -m app.main --excel-path data/business.xlsx --dry-run
```

The CLI reads `.env` from the current working directory without overriding exported environment variables. The provided `.env.example` leaves SMTP blank, so a normal run produces reports and records `not_configured` without attempting email. Once SMTP is configured, running without `--dry-run` authorizes SMTP submission. Use dry-run until recipients and content have been reviewed.

## Configuration

| Setting | Default | Purpose |
| --- | --- | --- |
| EXCEL_PATH | data/sample_business_data.xlsx | Local input path; overridden by `--excel-path` |
| BASELINE_WINDOW | 7 | Positive integer; also sets minimum required history |
| ANOMALY_THRESHOLD | 20 | Positive finite absolute percent deviation |
| REPORTS_DIR | reports | HTML/text output directory |
| DATABASE_DIR | state | Persistent SQLite and lock directory |
| SMTP_HOST | empty | SMTP server; empty disables sending |
| SMTP_PORT | 587 | Usually 587 for STARTTLS, 465 for implicit SSL |
| SMTP_SECURITY | starttls | `starttls` or `ssl`; plaintext is unsupported |
| SMTP_USERNAME | empty | Login username |
| SMTP_PASSWORD | empty | Password/app password; never logged |
| SMTP_FROM | empty | Plain sender address |
| ALERT_RECIPIENTS | empty | Comma-separated plain email addresses |
| SMTP_TIMEOUT | 30 | Positive network operation timeout in seconds |
| TZ | Asia/Kolkata | Container timezone; technical timestamps still use UTC |
| INPUT_FILENAME | sample_business_data.xlsx | Compose-only file inside the mounted data directory |

SMTP requires host, sender and at least one recipient. Missing any of them records `not_configured`. Username/password must be supplied together; both may be empty for a trusted relay that accepts unauthenticated submissions over verified TLS. TLS certificates and hostnames are verified; there is no insecure bypass. An incomplete or invalid active SMTP setup records a failure, preserves reports and returns exit code 3. Invalid numeric configuration returns 2 before analysis.

Keep `.env` private (for example `chmod 600 .env` on Linux). Do not commit actual exports, runtime reports, history, credentials or caches. The synthetic workbook is the only data file allowed by the provided Git ignore rules. Docker's build context contains only application source and runtime requirements.

### Gmail credentials for the private deployment

Store Gmail credentials only in the private repository's encrypted Actions secrets. Do not add them to local `.env`, commit them, or paste them into shell commands. Local execution remains available for dry-runs; authorized Gmail testing for this deployment uses the private workflow described below. Its initialization, dry-run and recovery modes receive no Gmail secrets.

## Reports and example alert

Reports are saved as `anomaly-report-YYYY-MM-DD.html` and `.txt`. Reanalysis replaces that date's reports. Reports describe analytical status, not inbox delivery status; use logs/history for email results.

Actual synthetic example from the default baseline, November 4, 2026:

| Metric | Current | Previous 7-day mean | Movement | Attention |
| --- | ---: | ---: | ---: | --- |
| Revenue | 6,600.00 | 9,915.43 | -33.44% | Review anomaly |
| Orders | 140.00 | 206.57 | -32.23% | Review anomaly |
| Conversion_Rate | 2.00 | 3.42 | -41.57% | Review anomaly |
| Traffic | 7,000.00 | 6,040.00 | +15.89% | Normal |
| Cost | 3,500.00 | 2,405.00 | +45.53% | Review anomaly |
| Refunds | 330.00 | 151.43 | +117.92% | Review anomaly |

Generated summary:

> Compared with recent daily averages: Revenue decrease (-33.44%); Orders decrease (-32.23%); Conversion Rate decrease (-41.57%); Cost increase (+45.53%); Refunds increase (+117.92%). These movements may warrant investigation. Review business context before drawing conclusions about causes.

Example email subject:

```text
Business anomaly alert | 2026-11-04 | Revenue, Orders, Conversion_Rate, Cost, Refunds
```

The multipart email contains the complete text and HTML reports, including that summary, current values, baseline values, movements and business implications. No normal-status email is sent. Example figures above are produced by the sample input, not embedded in monitoring logic.

### Before and after the next daily export

These are actual results calculated from the existing synthetic workbook: first using records through November 3, then including November 4. Each date uses its own preceding seven-day baseline.

| Metric | November 3 movement | November 4 movement | November 4 result |
| --- | ---: | ---: | --- |
| Revenue | +2.23% | -33.44% | Decrease anomaly |
| Orders | +2.23% | -32.23% | Decrease anomaly |
| Conversion_Rate | -0.42% | -41.57% | Decrease anomaly |
| Traffic | +2.65% | +15.89% | Within threshold |
| Cost | +2.91% | +45.53% | Increase anomaly |
| Refunds | +7.69% | +117.92% | Increase anomaly |

Before the new record: normal report, no alert needed. After the new record: five anomalies and an alert eligible for submission when SMTP is configured. This transition was verified in recreated Docker containers after updating a disposable copy at the same mounted Excel path. These checks used dry-run; they do not establish live email receipt.

## History, retries and concurrent runs

`state/alerts.sqlite3` stores reporting date, JSON anomaly findings, SHA-256 signature, UTC detection time, status, attempt time, submission result and a secret-safe error category. Statuses include `dry_run`, `not_configured`, `attempting`, `failed`, `submitted` and `duplicate_skipped`. Non-email events have no email attempt timestamp. Normal runs do not create an anomaly-history row.

The signature includes the reporting date and anomaly findings, including actual current/baseline values. Identical successfully submitted findings are skipped even after restarts; changed findings on the same date can produce a new alert. Formatting-only decimal changes do not change the signature. A successful submission remains suppressed if recipients are later changed. Dry-run and unconfigured records do not suppress a later live attempt.

Attempts are committed before contacting SMTP, then updated on success/failure. Failed or interrupted `attempting` records can be retried on a future run. A crash after SMTP acceptance but before the database commit can cause a duplicate retry. Partial recipient refusal is a failed submission and retry can duplicate mail for recipients already accepted. Exactly-once email delivery and inbox arrival are **not guaranteed**.

All runs must share the same persistent directory on a **single host with a local filesystem**. A file lock covers validation, report generation and email submission. A concurrent run exits with code 4; the OS releases the lock after termination. The lock file itself may remain and must not be deleted while a run is active. Separate databases, network filesystems and multiple hosts are outside the lock guarantee.

| Exit code | Meaning |
| --- | --- |
| 0 | Analysis completed; email submitted, suppressed, dry-run, unconfigured or not needed |
| 1 | Unexpected runtime/I/O failure; inspect the logged category and host permissions |
| 2 | Invalid input, insufficient history or invalid numeric configuration |
| 3 | SMTP configuration/submission failed; reports retained, retry permitted |
| 4 | Another process holds the monitoring lock |

Logs use UTC `Z` timestamps and `event=...` fields. Reporting dates remain business dates with no timezone conversion. SMTP error responses are not logged because they can echo sensitive data.

## Docker deployment

Docker/host cron remains a supported alternative. The preferred GitHub Actions demonstration and implemented private operations design are documented below; neither has been activated remotely. For the chosen private Actions deployment, Gmail credentials belong only in encrypted GitHub secrets; local/Docker commands below remain useful for dry-run verification.

Use an always-available Linux machine or VPS with Docker Engine and the Compose plugin. No paid cloud service is required. Deploy the project files and configure a real daily export and SMTP only when ready.

For a fresh Ubuntu VPS, install Docker Engine and Compose using the [official Ubuntu installation instructions](https://docs.docker.com/engine/install/ubuntu/). The commands below assume those prerequisites, SSH access, sudo access and a deployment user authorized to run Docker. No external server has been provisioned or configured by this project.

Transfer an explicit source-only archive from Windows (replace the SSH target):

```powershell
Set-Location C:\Users\admin\OneDrive\Documents\Intel\ai-business-anomaly-agent
$Vps = 'deploy@YOUR_SERVER_IP'
$Archive = Join-Path $env:TEMP 'ai-business-anomaly-agent.tar.gz'
tar --exclude=__pycache__ -czf $Archive app tests data/sample_business_data.xlsx requirements.txt requirements-dev.txt Dockerfile docker-compose.yml .dockerignore .gitignore .env.example README.md LICENSE
scp $Archive "${Vps}:ai-business-anomaly-agent.tar.gz"
ssh $Vps
```

On the VPS, for a **new installation**:

```bash
sudo install -d -o "$(id -u)" -g "$(id -g)" /opt/ai-business-anomaly-agent
tar -xzf ~/ai-business-anomaly-agent.tar.gz -C /opt/ai-business-anomaly-agent
docker version
docker compose version
```

Then initialize configuration and persistent directories. On upgrades preserve the existing `.env` and history instead of copying the example over them.

```bash
cd /opt/ai-business-anomaly-agent
cp .env.example .env
mkdir -p data reports state
# Container runs as UID/GID 10001. Apply these only to this project's outputs:
sudo chown -R 10001:10001 reports state
chmod 600 .env
# Review/set SMTP privately. Start with the sample and dry-run only.
nano .env
chmod 755 data
chmod 644 data/sample_business_data.xlsx
docker compose build
docker compose config --quiet
docker compose run --rm monitor --dry-run
```

Or build the image directly: `docker build -t ai-business-anomaly-agent:local .`.

Compose mounts `./data` read-only and `./reports`, `./state` read-write. The root filesystem is read-only with temporary `/tmp`, dropped capabilities and no-new-privileges. The Docker base is pinned by digest; update it deliberately alongside dependency maintenance.

For real data, place `business.xlsx` inside `data/` and set `INPUT_FILENAME=business.xlsx` in `.env`. Compose uses container paths for input, reports and history regardless of local path settings. Do not point it to the demonstration workbook in production. Supply new data **before each run**, preferably by writing a temporary export then atomically renaming it. The app never downloads or fabricates new business data.

For example, upload the real file from your workstation with `scp "C:\path\to\business.xlsx" "${Vps}:business.xlsx"`, then on the server:

```bash
cd /opt/ai-business-anomaly-agent
install -m 640 ~/business.xlsx data/business.next.xlsx
sudo chgrp 10001 data/business.next.xlsx
mv data/business.next.xlsx data/business.xlsx
# Set INPUT_FILENAME=business.xlsx using the private editor, then verify:
nano .env
docker compose run --rm -T monitor --dry-run
```

Use this temporary-file/rename pattern for future exports and preserve group readability. Keep all scheduled runs on the same host and persistent `state` directory. Never upload `.env` or real data to a public portfolio repository.

After reviewing dry-run output and configuring authorized SMTP recipients:

```bash
docker compose run --rm monitor
# For a retained one-shot container and its logs:
docker compose up --abort-on-container-exit --exit-code-from monitor
docker compose logs --tail=100 monitor
```

`run --rm` writes logs to the console and removes the container; capture stdout/stderr if retention is needed. Reports and SQLite survive removal because they are host mounts. Back up `state` and protect reports as business data. Preserve history when upgrading to retain duplicate suppression.

## Daily scheduling

Use host cron on the always-on Linux machine. There is no scheduler process inside the container. In this example the project is `/opt/ai-business-anomaly-agent` and the system timezone is configured to **Asia/Kolkata**. Choose the required IANA timezone on the host; the `.env` `TZ` value alone does not change cron scheduling.

```bash
# Check first. Changing host timezone affects other jobs on this machine.
timedatectl
sudo timedatectl set-timezone Asia/Kolkata
command -v docker  # use its absolute path below; commonly /usr/bin/docker
crontab -e
```

Add this line to the deployment user's crontab (user must have Docker access):

```cron
15 8 * * * { (cd /opt/ai-business-anomaly-agent && /usr/bin/docker compose run --rm -T monitor); code=$?; echo "$(date -u -Iseconds) event=scheduled_run exit_code=$code"; exit "$code"; } >> /opt/ai-business-anomaly-agent/monitor.log 2>&1
```

This runs daily at 08:15 in the **host cron timezone**. On distributions whose cron supports `CRON_TZ`, an explicit `CRON_TZ=Asia/Kolkata` line may be used instead of changing host time. Verify your cron implementation before relying on it. Configure host log rotation for `monitor.log` and inspect nonzero exits. New Excel data must arrive before 08:15. Repeated runs of the same successfully submitted findings will not intentionally resend.

On Ubuntu, confirm the scheduler is enabled and inspect its first real execution:

```bash
sudo systemctl enable --now cron
crontab -l
tail -n 100 /opt/ai-business-anomaly-agent/monitor.log
grep 'event=scheduled_run' /opt/ai-business-anomaly-agent/monitor.log | tail -n 7
grep -E 'level=ERROR|exit_code=[1-9]' /opt/ai-business-anomaly-agent/monitor.log
```

The explicit exit-code log also exposes Docker launch failures, not just application errors. Check that a new completion entry appears every day; absence can indicate a scheduler/export/host problem. The application does not send a separate failure-notification email when monitoring itself fails. Observability here is logs, exit codes and operator review. Cron execution on your VPS remains unverified until the first scheduled run is observed.

## Tests and verification

Run `python -m pytest -q`. Tests block network connections, mock SMTP, and cover all required validation/detection/report/history behaviors, a synthetic workbook end-to-end run, failure retry, durable duplicate suppression and a lock held across separate processes. No test sends real email.

Verified on November 11, 2026:

- Pinned dependencies installed in a Python 3.12.10 virtual environment.
- **88 tests passed** in the final acceptance review, including mocked successful submission, failed retry, duplicate suppression, persistence and cross-process locking. The original 86 passed before changes.
- Synthetic workbook executed locally in dry-run and with SMTP absent; six metrics evaluated and five anomalies detected.
- HTML/text reports matched current calculated findings. HTML rendered in headless Edge with six metric rows and no page overflow; report and sample workbook visually reviewed.
- SQLite integrity check returned `ok`; history retained across local runs and recreated Docker containers.
- Compose configuration validated. Final digest-pinned Docker image built and ran in dry-run as UID/GID `10001:10001` with mounted output/history directories.
- Independently checked every metric's baseline and percent movement using rational arithmetic for November 3 and November 4. Verified the transition from zero to five anomalies when a mounted Excel input was updated, without changing source code.
- Recreated Docker containers retained both dates' HTML/text reports and SQLite dry-run rows. An invalid mounted input logged `event=validation_failed` and returned exit code 2.
- Documented cron command passed POSIX shell syntax validation in Docker. Simulated success/failure commands emitted the expected exit-code records in network-disabled containers. This verifies the shell wrapper, not installation or execution by a real cron daemon.
- Fixed an SMTP cleanup edge case: a socket-close error could overwrite a successful submission or hide the original SMTP failure. Two regression tests reproduced those failures before the fix and now pass; accepted submissions remain suppressed on rerun.

One test run encountered a Windows access-denied error replacing a temporary report inside the OneDrive workspace. The complete suite passed using a nonsynced temporary directory. No report-storage bypass was added: unwritable/locked report paths still fail visibly. Production reports/history should use writable local server storage.

This project has not been deployed to an external server, the cron job has not been installed, and no live email has been sent. SMTP submission is verified with mocks; real server credentials, network access and authorized recipients still need deployment verification.

The initial public GitHub Actions preparation retained **88 passing tests**. The private operations adaptation now has **117 passing tests**, including the original 88. The original anomaly detector and SMTP functions are unchanged; `main.run()` gained only an optional history-factory hook. `actionlint 1.7.12` validated the workflow syntax, contexts and action inputs locally (optional shellcheck/pyflakes integrations were not installed). The release archive was checked against its published SHA-256 checksum. Action SHAs were resolved from official release metadata and their input manifests reviewed; this is not a full third-party source audit. Local CLI execution with dotenv disabled produced the expected six-metric, five-anomaly synthetic reports. A GitHub-hosted workflow run has **not** occurred.

The latest publication review scanned **32 public candidate files** with no potential secret matches, verified **20 ignored sensitive/runtime path cases**, and staged exactly the intended 32 files in an isolated temporary Git repository. The project itself remains uninitialized and unpublished. Earlier recreated Docker containers retained reports/history; the new private adapter also passed the complete Linux test suite and the updated Docker CLI dry-run.

### Final acceptance review

| Requirement | Implementation | Verification | Action still required |
| --- | --- | --- | --- |
| 1. Read and validate Excel | Implemented | Automated validation tests and actual synthetic Excel runs | Validate the first real export |
| 2. Monitor all six metrics | Implemented | All six checked in tests, independent calculations and Docker | None for code |
| 3. Detect unusual increases/decreases | Implemented | Boundary, normal, high/low, zero-baseline and actual before/after checks | Choose operational threshold/window |
| 4. Dynamic business explanations | Implemented | Automated summaries and generated sample reports | None for code |
| 5. Cautious business impact | Implemented | Per-metric wording reviewed; interpretation tests pass | Business owner supplies context when investigating |
| 6. HTML/text reports | Implemented | Generated contents verified; prior visual review retained | Verify the authorized private alert's content |
| 7. Email on anomalies | Implemented | TLS/SSL, construction, errors, dry-run and submission mocked | Configure SMTP; authorize one live test; verify receipt |
| 8. Durable history/duplicate prevention | Implemented | SQLite reopening, mocked successful duplicate suppression, Docker persistence and locking | Confirm duplicate skip after the authorized live test |
| 9. Daily automatic execution | Private Actions template and alternative cron instructions implemented; neither activated | Manual Docker runs and local workflow validation; no hosted scheduled execution | Set up private operations, verify manually, then authorize/observe the daily run |
| 10. Deployable portfolio project | Implemented | Docker build/run verified; README includes evidence and limitations | Authorize repository creation/publication and complete hosted verification |

### Post-deployment checklist

- Confirm real input schema, percentage-point units, currency consistency and at least window + 1 consecutive dates.
- Run dry-run, verify all six metrics and compare a baseline manually.
- Check HTML/text reports are readable and owned by the expected user.
- Verify SQLite and reports survive removal/recreation of a container.
- Confirm SMTP TLS, recipient list and sender authorization; submit an authorized test alert and check submission logs and recipient inbox independently.
- Rerun identical findings and verify `duplicate_skipped` without another intentional submission.
- Review a failed attempt and retry after resolving settings/connectivity.
- Verify cron timezone, export arrival time, cron execution, permissions, log rotation and history backup.

## Three-day implementation phases

1. **Day 1 — data reader and metric checker:** project setup, strict Excel validation, normalized dates and Decimal numbers, ordering, complete daily baseline and movement calculations. Exit: valid data produces correct latest-period movements.
2. **Day 2 — anomaly rules and business summaries:** configurable threshold, direction, zero baseline, cautious implications and HTML/text reporting. Exit: synthetic anomalies produce a meaningful business report.
3. **Day 3 — alerts, automation and packaging:** secure SMTP, dry-run, persistent SQLite, duplicate suppression, process locking, tests, Docker and cron instructions. Exit: verified end-to-end processing and deployable packaging. These are implementation phases, not a claim of three elapsed calendar days.

## Limitations

The moving-average threshold is an MVP method. Seasonality, holidays, promotions, small baselines and unusual business events can create false positives. Anomalies inside the baseline can mask later movements. The method does not identify causes, forecast outcomes, measure statistical significance or adjust for business calendars. It analyzes only the latest date and does not warn about stale exports or backfill missed dates. Operators must monitor export freshness and failed cron jobs. The entire workbook must pass validation; formulas must be converted to values by the data supplier. Two-decimal display can make a value near the threshold look rounded to the threshold even though the unrounded comparison is below it.

## Interview explanation

“The agent reads Excel business data, monitors key metrics, compares recent results against historical baselines, identifies anomalies, generates business-friendly explanations, and sends email alerts so teams can investigate unusual changes.”

## GitHub Actions: public demonstration

`.github/workflows/daily-monitor.yml` runs only the committed, checksum-verified synthetic workbook. It installs the pinned development requirements on Python 3.12, runs the complete tests and calls `python -m app.main --dry-run`. A missing input, failed test or CLI failure fails the job. It does not fabricate new dates or download business data.

Security boundaries:

- Only `workflow_dispatch` and `schedule` triggers; no pull-request, `pull_request_target` or `workflow_run` execution.
- The monitoring job requires the default branch. Other manual branches and `live-blocked` requests fail before checkout or secret access.
- `contents: read`, disabled checkout credential persistence, SHA-pinned official actions, a 15-minute timeout, and one concurrency group with cancellation of active runs disabled.
- Dotenv loading is disabled and SMTP values are explicitly empty. **No GitHub secret is referenced by this public workflow.**
- Only the exact synthetic HTML/text filenames are uploaded, after successful tests and analysis, with one-day retention. SQLite, logs, `.env`, recipient details and other reports are never uploaded.
- No Actions cache is used. The demo's local SQLite is deliberately disposable because dry-run sends nothing. This is **not** persistent operational alert history.

The schedule is `45 2 * * *`: 02:45 UTC / **08:15 Asia/Kolkata**. The scheduled monitoring job runs only when repository variable `ENABLE_DAILY_DEMO` equals `true`; leave it absent or `false` until daily demonstration execution is authorized. The workflow may appear as skipped before opt-in. Selecting `live-blocked` intentionally returns a failure; it never attempts email. There is no switch that bypasses the persistence blocker.

Standard public hosted runners are [free under GitHub's documented terms](https://docs.github.com/en/actions/concepts/billing-and-usage); no paid/larger runner is selected. GitHub schedules can be delayed or dropped, run from the default branch, and public schedules can be disabled after 60 days without repository activity. This is not an exact-time execution guarantee. See [schedule behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

### Manual GitHub setup and publication

No local `.git` repository was present during review, including in parent directories. Therefore no tracked-file list, local history or remote exposure could be audited. This is **not proof** that a separate remote repository has never contained sensitive data. No repository was created and no push was performed.

The public-file review covered source, tests, documentation, dependency/configuration templates, workflow and the labeled synthetic workbook. No potential secret match was found using known local sensitive values and common key/token patterns; matching values were never printed. Such a scan is not an absolute guarantee. `.env` and runtime files remain private on this machine. If any earlier publication contains a secret, stop, revoke/rotate it with the provider, replace the local/GitHub secret, and clean the exposed history; deleting the latest file does not revoke a credential.

After authorizing publication, create an **empty public repository** named `ai-business-anomaly-agent` in the GitHub web UI. Do not initialize it with another README/license. Review the exact candidate files locally before pushing:

```powershell
Set-Location C:\Users\admin\OneDrive\Documents\Intel\ai-business-anomaly-agent
git init -b main
git add -- app/*.py tests/*.py data/sample_business_data.xlsx README.md LICENSE requirements.txt requirements-dev.txt .env.example .gitignore .dockerignore Dockerfile docker-compose.yml .github/workflows/daily-monitor.yml operations/private-monitor.yml
git diff --cached --name-only
git diff --cached --stat
git ls-files -- .env 'reports/*' 'state/*' '*.sqlite3*' '*.log'
# The final command must produce no output. Do not use git add -f.
git commit -m "Prepare secure synthetic anomaly monitoring demonstration"
git remote add origin https://github.com/YOUR_USERNAME/ai-business-anomaly-agent.git
# Publication boundary: execute only after approving the staged files and push.
git push -u origin main
```

The expected public content is `app/*.py`, `tests/*.py`, the one synthetic workbook, README, MIT license, two requirements files, safe templates/ignore files, Docker files, the public workflow, and the credential-free `operations/private-monitor.yml` template. Do not add the surrounding Intel workspace. Ignore rules exclude all other Excel/CSV/TSV files, reports, state, databases/backups, emails, logs, environment files, common key containers and archives; Docker's existing allowlist contains only runtime source and requirements. Ignore rules do not protect files force-added or already tracked.

In GitHub Settings → Actions → General, use read-only default workflow permissions. Enable secret scanning/push protection if offered for the public repository. Keep production credentials **out of this public repository**. No secrets are needed for the current demo.

After publication and authorization to run it: Actions → **Daily anomaly monitor (synthetic demo)** → Run workflow → default branch → `demo-dry-run`. Confirm a green run, 117 passing tests, `email_status=dry_run`, and two synthetic reports in the one-day artifact. Do not treat a skipped job as execution evidence. Only after separately authorizing daily demos, add Actions repository variable `ENABLE_DAILY_DEMO=true`; then observe a real scheduled run. Remove/set it to `false` to stop daily analysis.

## Private operations repository — implemented locally

The public source repository and private operations repository are independent. The private repository contains a reviewed copy of the application and `requirements.txt`, its own default-branch workflow, `input/business.xlsx`, and the authoritative `.monitor/alerts.sqlite3`. It never receives changes by automatically executing public pull-request code. Review and copy source updates deliberately; do not set a public remote on the private repository.

The credential-free template is `operations/private-monitor.yml` in this public project. Copy it to `.github/workflows/private-monitor.yml` **only in the private repository**. The public demo continues to refuse live email and has no access to the private repository or Gmail secrets.

### How history survives runners and failures

`python -m app.private_operations` uses only standard Python libraries plus the application's existing dependencies:

1. Check repository privacy through the GitHub API and require its default branch. Recheck privacy/default branch before each file read or checkpoint. HTTP redirects are refused; certificate verification is not disabled. Only `api.github.com` is used, with 30-second request timeouts and secret-safe error categories.
2. Restore `.monitor/alerts.sqlite3`, validate SQLite integrity/schema, and refuse missing/corrupt history. Only explicit `initialize` can create first-time state; it refuses to reset existing history.
3. Add a `running` entry to `ops_runs` and save a consistent SQLite backup snapshot. Each Contents API write includes the previous file SHA. GitHub rejects a stale revision instead of allowing an old runner to overwrite a newer one. The workflow additionally serializes all modes through one concurrency group and never cancels an active run to start a newer one.
4. Fetch the current `input/business.xlsx` privately. Run the existing validation, detector, summary, report and email code through a checkpointing history adapter. No analysis rules were changed.
5. Persist every alert transition. An `attempting` record and its `ops_attempts` run association must be acknowledged remotely **before** SMTP is called. Save `submitted`, definite rejection, or ambiguous failure immediately afterward. Finalize the run's status as another durable checkpoint.
6. If a checkpoint fails or its acknowledgement is lost, stop without blind HTTP retries or resetting the database. Next execution restores the remote truth. Existing `submitted` signatures still suppress duplicate alerts. Any unfinished run or `attempting`/`ambiguous` alert blocks further analysis/sending until explicit reconciliation.

An SMTP success followed by checkpoint failure leaves a durable `attempting` record unless GitHub saved the success but its response was lost. Both cases stop the next run: either reconcile the alert or recover the unfinished run. If the alert checkpoint succeeded but a later report/workflow step fails, that successful signature remains saved and is not intentionally resent. **Exactly-once delivery is not guaranteed:** SMTP and GitHub cannot participate in one atomic transaction, and reconciliation depends on correct provider evidence.

Known complete rejections (authentication, connection/HELO rejection, unsupported STARTTLS, all recipients refused, or DATA rejection) are recorded as `failed` and may be retried. Disconnects, timeouts, partial recipient acceptance and generic SMTP errors are conservatively `ambiguous`; they require review. The stricter behavior belongs to the private adapter; local/Docker CLI behavior remains unchanged.

The existing `alerts` table is preserved. Additional tables contain run status/timestamps/error category and the association of each email attempt to its run. Technical logs include IDs and counts, never credentials, HTTP bodies, recipient addresses or metric values. Input/report failures are recorded when storage remains reachable. If storage itself fails or a runner is killed, private Actions failure logs and the last durable `running`/`attempting` record are the evidence; a fresh error record cannot be guaranteed while storage is unavailable.

### Security boundaries and permissions

- Private default branch only. No PR, `pull_request_target`, push or `workflow_run` trigger. Updating input or a checkpoint does not recursively trigger monitoring.
- `OPERATIONS_ENABLED`, `LIVE_EMAIL_ENABLED` and `ENABLE_DAILY_MONITORING` default to disabled. Daily work is skipped until enabled; manual live requests fail unless separately enabled.
- The gate job has no repository permissions or secrets. The operational job has only `contents: write` for its own private checkpoint file and `actions: read` to verify a previous workflow attempt has completed before recovery. The short-lived `GITHUB_TOKEN` is supplied only to the adapter step. No PAT or cross-repository credential is needed.
- Checkout does not persist credentials. Official actions are pinned to the same reviewed release SHAs as the public demo. Only runtime application source and root dependency files are checked out; private input/history are fetched through the adapter.
- Gmail secrets are mapped only on the operational step, only for `live` or an enabled scheduled run. Initialization, dry-run, recovery, dependency installation and the public workflow receive no SMTP credentials. Dotenv loading is disabled.
- No artifact upload action exists in the private workflow. Reports remain runner-local and expire with the runner; an authorized live anomaly email carries the HTML/text report. Normal-status reports can be inspected during a local synthetic test. Persistent report archiving is not implemented. Actions logs and run summaries remain inside the private repository.

**Maintainer trust is essential.** GitHub repository secrets cannot be restricted to one workflow filename. A person who can write workflow/application code can attempt to use those secrets. Keep the private repository owner-only or grant write/admin access exclusively to trusted operators, review all changes before default-branch use, and configure available branch/environment protections. Do not assume paid approval protections are available on GitHub Free. These guards protect against wrong-repository/branch execution and accidental misuse, not a malicious repository administrator. Never change operations-repository visibility to public; old Excel versions and SQLite commits contain confidential history even after files are removed.

### Exact initial setup (manual, not executed)

1. After authorizing publication, publish the public source using the explicit allowlist above, including `operations/private-monitor.yml`. Keep all real input, state, reports and secrets out of it.
2. After authorizing remote creation, create a **new empty PRIVATE** repository named `ai-business-anomaly-operations` in GitHub. Confirm its visibility and restrict collaborators. Do not initialize it with another README or license.
3. Prepare its separate working directory from the reviewed source. These commands copy no `.env`, runtime state or private reports. The initial input is the existing synthetic sample, renamed to the operational filename:

```powershell
$Source = 'C:UsersadminOneDriveDocumentsIntelai-business-anomaly-agent'
$Private = 'C:UsersadminOneDriveDocumentsIntelai-business-anomaly-operations'
# Use a new directory; stop and inspect if it already exists.
if (Test-Path $Private) { throw 'Private working directory already exists; inspect it first.' }
New-Item -ItemType Directory -Path "$Privateapp", "$Private.githubworkflows", "$Privateinput" -Force | Out-Null
Copy-Item "$Sourceapp*.py" "$Privateapp"
Copy-Item "$Source
equirements.txt", "$SourceLICENSE", "$Source.gitignore" $Private
Copy-Item "$Sourceoperationsprivate-monitor.yml" "$Private.githubworkflowsprivate-monitor.yml"
Copy-Item "$Sourcedatasample_business_data.xlsx" "$Privateinputusiness.xlsx"
Set-Location $Private
git init -b main
git add -- app/*.py requirements.txt LICENSE .gitignore .github/workflows/private-monitor.yml
# This exception is ONLY for this separate PRIVATE repo and this synthetic setup input.
git add -f -- input/business.xlsx
git diff --cached --name-only
git commit -m "Prepare private anomaly operations with synthetic verification input"
git remote add origin https://github.com/YOUR_USERNAME/ai-business-anomaly-operations.git
# Stop here until visibility and push have been explicitly approved.
git push -u origin main
```

Do not reuse this private directory for public publication. Local ignore rules intentionally exclude `input/` and `.monitor/`; API checkpoint writes bypass Git ignore rules only in the verified private repository. No Git history was initialized or pushed by the assistant.

4. In private repository Settings → Actions → General, permit the pinned official actions and use read-only default permissions; the reviewed operational job requests its narrowly scoped write/read permissions explicitly. Do not grant arbitrary collaborators write access. If branch rules block checkpoint updates, keep monitoring disabled and review a narrowly scoped rule configuration; do not replace the workflow token with a broad administrator PAT or weaken public-repository protections.
5. Configure spending limits to stop metered usage at the free allowance, review available account quota and leave paid overages disabled. No payment method or resource purchase is required by this project.
6. Under Settings → Secrets and variables → Actions → **Variables**, set `OPERATIONS_ENABLED=true`. Leave `LIVE_EMAIL_ENABLED` and `ENABLE_DAILY_MONITORING` absent or `false`. No Gmail secrets are needed yet.
7. Actions → **Private business anomaly monitoring** → Run workflow → default branch → mode `initialize`. Run this only once for genuinely new history. Confirm `.monitor/alerts.sqlite3` was created privately. If history was lost after prior live use, restore a known-good copy instead of initializing an empty ledger.
8. Run mode `dry-run` twice. Expect successful jobs, six metrics/five anomalies for the synthetic sample, no email and retained private dry-run history. This verifies the actual hosted transport/storage path, which has not yet been exercised locally against GitHub.

### Gmail secrets and authorized manual testing

Create these **encrypted repository secrets in the PRIVATE operations repository only**:

| Secret | Meaning |
| --- | --- |
| SMTP_USERNAME | Gmail login address |
| SMTP_PASSWORD | Gmail App Password, never the normal account password |
| SMTP_FROM | Gmail account or an authorized sender alias |
| ALERT_RECIPIENTS | Authorized comma-separated recipient addresses |

Safe repository variables map directly to the existing configuration: `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_SECURITY=starttls`, `SMTP_TIMEOUT=30`, `BASELINE_WINDOW=7`, `ANOMALY_THRESHOLD=20`. Defaults are supplied by the template. Alternatively use port `465` with `ssl`. TLS certificate/hostname verification remains enabled. Google requires 2-Step Verification for App Passwords and some account policies prohibit them; follow [Google's instructions](https://support.google.com/accounts/answer/185833).

Only after explicit live-email authorization, set `LIVE_EMAIL_ENABLED=true` and manually run mode `live` with the synthetic verification input and approved test recipient. Require a successful workflow, `email_status=submitted`, and independent inbox/provider confirmation. Rerun unchanged input: expect `duplicate_skipped`. Missing SMTP settings fail the private live run rather than silently declaring operational success. Failed submissions do not create false success records.

Keep credentials only in encrypted Actions secrets for this deployment. Do not create local password files, place them in Git, print environment variables, or enable SMTP debug logging. Remove/disable live permission after testing if production activation is not yet authorized.

### Fresh private Excel and daily operation

Replace `input/business.xlsx` **inside the private repository** using its authenticated Upload files interface before monitoring. The initial setup above creates the `input` directory so you can navigate there, upload the new `business.xlsx`, and commit the replacement. Keep the exact schema and units documented earlier. Confirm the upload completed and the latest reporting date is current. Files are limited to **5 MiB each** by the adapter; there is no silent truncation or fallback to the public sample.

Every run fetches the latest committed private input. A private input commit does not start a run. New data must be supplied before the scheduled time; the application does not invent records, scrape data, or check whether an unchanged export is stale. Old input versions remain in private Git history. The public demo always uses its static, checksum-verified synthetic workbook and cannot monitor confidential data.

After explicit authorization and successful manual verification, enable all three variables: `OPERATIONS_ENABLED=true`, `LIVE_EMAIL_ENABLED=true`, `ENABLE_DAILY_MONITORING=true`. The cron expression `45 2 * * *` targets **08:15 Asia/Kolkata**. Observe the first actual scheduled execution and review logs daily; GitHub may delay/drop scheduled jobs, so this is not an exact-time guarantee. Set `ENABLE_DAILY_MONITORING=false` to stop daily work, or `OPERATIONS_ENABLED=false` to block all monitoring modes until re-enabled. Cancellation can leave an unfinished record; prefer letting active runs finish.

### Recovery: do not erase history to resend

Private adapter exits: `0` completed; `3` SMTP submission failed; `5` storage/input/recovery safety stop; `1` unexpected adapter error. The original local CLI exit codes remain unchanged. The workflow fails on nonzero exits and writes a private job summary. On an interrupted or ambiguous run, the next invocation logs only `attempt_id` and `original_run` (format `GitHub run ID:attempt`) and stops.

Disable daily monitoring during investigation. Open the failed run/provider logs privately. Wait for the **original attempt** to finish or cancel it and wait until GitHub shows it completed. Recovery queries that exact attempt through the API and refuses to modify state while it is active. Start a **new manual workflow dispatch**, not a rerun of the original interrupted workflow.

| Situation | Manual mode and inputs | Result |
| --- | --- | --- |
| Original run unfinished, no unresolved email attempt | `recover-run`; `recovery_run_id` = original ID:attempt | Marks the run reconciled; existing submitted findings remain suppressed |
| Provider evidence confirms acceptance, or partial acceptance must not be duplicated | `confirm-submitted`; matching attempt ID and original run ID:attempt | Marks that finding submitted and suppresses further intentional sends |
| Provider evidence confirms no recipient accepted the message | `confirm-not-sent`; matching attempt ID and original run ID:attempt | Marks the attempt failed/retryable; a later live run may send |
| Definite SMTP rejection already durably recorded | Correct configuration, then a new `live` run | Retries without erasing history |
| Missing/invalid Excel | Upload a valid file, then a new dry-run/live run | Failed run remains recorded; no false alert was sent |
| Storage/API conflict, timeout or lost acknowledgement | Inspect the latest private ledger; rerun once to obtain block details | Do not retry writes manually or delete state; reconcile only if blocked |
| Missing/corrupt history after prior operation | Restore a verified private backup after checking all later submissions | Never initialize empty history as a shortcut |

If evidence is inconclusive, **leave monitoring blocked**. Do not choose `confirm-not-sent` merely because an inbox is empty. Partial recipient acceptance may require contacting the remaining recipient separately rather than rerunning the same alert. Recovery records an auditable operation in `ops_runs`; it does not contact SMTP. Operator mistakes and externally delivered mail mean exactly-once delivery cannot be promised.

### Free usage and private retention limits

The workflow uses a standard `ubuntu-24.04` runner, no paid services, no cache and no artifacts. The gate has a two-minute timeout and monitoring has a twelve-minute timeout. Once daily bounds scheduled execution time to at most 14 minutes per day, but **manual runs, account-wide usage and billing rates also consume the allowance**. The code cannot enforce an account's billing budget. Configure GitHub's spending controls to stop usage, leave paid overages disabled and review the account's actual allowance before enabling daily runs.

GitHub's current [included-usage documentation](https://docs.github.com/en/billing/reference/product-usage-included) lists a **$12 monthly included compute allowance and 500 MB Actions storage** for GitHub Free; it now expresses compute in monetary terms rather than the older fixed-minute figure. Follow the allowance actually displayed for your account. This is included usage, not a promise that unlimited monitoring is free. No account, remote resource or payment setup has been performed here.

SQLite snapshots are small Git file commits, not Actions artifacts. Every checkpoint retains a binary version; confidential history and older Excel exports remain in the private repository. The adapter caps input and current state at 5 MiB, fails instead of dropping history, and makes no automatic destructive pruning. Check repository growth regularly. GitHub blocks ordinary files above 100 MiB and [does not recommend Git for large database backups](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github). This is a small single-writer MVP, not an unlimited database service. Before the limit, disable monitoring and arrange reviewed private archival/maintenance that preserves successful signatures and uncertain attempts. Never make the repository public, delete the ledger, or rewrite it while runs are active.

### Deployment acceptance and evidence

| Criterion | Current status |
| --- | --- |
| Excel, six metrics, anomaly logic, summaries and reports | Existing implementation retained and locally verified |
| Private state initialization, restore and checkpoint writes | Implemented; mocked GitHub storage tests pass |
| Duplicate suppression across isolated executions | Verified with restored snapshots and mocked SMTP |
| SMTP accepted but later checkpoint/step fails | Tested: durable attempt/success remains; next run blocks or skips after reconciliation |
| Interrupted/ambiguous submission | Tested: no blind retry; explicit completed-run reconciliation required |
| Invalid input, definite rejection, lost acknowledgements and revision conflicts | Tested with synthetic input and fault injection |
| Private/public workflow security | Both validated locally with actionlint; no hosted run yet |
| Real private GitHub storage and fresh input | Awaiting authorized repository creation/push and hosted dry-runs |
| Gmail submission/receipt | No live email sent; explicit authorization and credentials still required |
| Daily monitoring | Template implemented, not enabled or observed |
| Public confidentiality | No publication performed; final staging/remote visibility review still required |

The private adapter was added after the original 88-test suite. Current complete suite: **117 passing tests** on Python 3.12 in both Windows and a disposable Linux Docker container. The updated non-root image built successfully and its original CLI completed a synthetic dry-run. Both workflow files pass `actionlint 1.7.12`; the private workflow's shell gate passed nine local cases covering repository visibility, branch, manual mode, authorization and scheduling. GitHub storage and SMTP are mocked in tests; no live hosted workflow, repository write or email has been verified. No remote repository, scheduled workflow or real email was created/activated by this implementation.
