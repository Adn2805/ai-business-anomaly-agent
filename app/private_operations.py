"""Private Actions adapter: restore, checkpoint every transition, fail closed.

The detector and SMTP implementation remain shared with local/Docker execution.
"""
import argparse
from contextlib import closing
from dataclasses import replace
import logging
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time

from .alert_history import AlertHistory, utc_now
from .config import load_config
from .main import run
from .private_store import GithubStore, OperationsError, StorageError, STATE_PATH, INPUT_PATH

logger = logging.getLogger(__name__)
MODES = ('initialize', 'dry-run', 'live', 'recover-run', 'confirm-submitted', 'confirm-not-sent')
SAFE_REJECTIONS = ('SMTPAuthenticationError:', 'SMTPConnectError:', 'SMTPHeloError:',
                   'SMTPNotSupportedError:', 'SMTPRecipientsRefused:', 'SMTPDataError:', 'ValueError:')


def pending(db):
    return db.execute("SELECT id FROM alerts WHERE status IN ('attempting','ambiguous') ORDER BY id LIMIT 1").fetchone()


class CheckpointHistory(AlertHistory):
    def __init__(self, path, store, sha, run_id):
        super().__init__(path)
        self.path, self.store, self.sha, self.run_id = Path(path), store, sha, run_id

    def checkpoint(self):
        # SQLite's backup API produces a consistent snapshot, including committed changes.
        snapshot = self.path.with_suffix('.snapshot')
        destination = sqlite3.connect(snapshot)
        try:
            self.db.backup(destination)
        finally:
            destination.close()
        try:
            self.sha = self.store.save(snapshot.read_bytes(), self.sha)
        finally:
            snapshot.unlink(missing_ok=True)

    def record(self, day, key, findings, status, attempted=False):
        if attempted and pending(self.db):
            raise OperationsError('Unresolved SMTP attempt exists; reconciliation required.')
        identifier = super().record(day, key, findings, status, attempted)
        if attempted:
            with self.db:
                self.db.execute('INSERT INTO ops_attempts VALUES (?,?)', (identifier, self.run_id))
        # Failure here propagates BEFORE deliver() can contact SMTP.
        self.checkpoint()
        return identifier

    def finish(self, attempt, status, result, error=None):
        # Disconnects, partial acceptance and generic transport errors may follow DATA.
        if status == 'failed' and not (error or '').startswith(SAFE_REJECTIONS):
            status = 'ambiguous'
        super().finish(attempt, status, result, error)
        # Failure leaves durable 'attempting' state remotely: never blind-retry it.
        self.checkpoint()


def validate_history(path):
    try:
        with closing(sqlite3.connect(path)) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise OperationsError('Private history integrity check failed.')
            if db.execute('PRAGMA user_version').fetchone()[0] != 1:
                raise OperationsError('Private history version is unsupported.')
            db.execute('SELECT id, signature, status, attempted_at FROM alerts LIMIT 0')
            db.execute('SELECT run_id, status, started_at, finished_at, error FROM ops_runs LIMIT 0')
            db.execute('SELECT attempt_id, run_id FROM ops_attempts LIMIT 0')
    except sqlite3.Error:
        raise OperationsError('Private history is corrupt or incomplete; refusing an empty replacement.') from None


def initialize(path, store):
    history = AlertHistory(path)
    try:
        with history.db:
            history.db.execute('''CREATE TABLE ops_runs (
                run_id TEXT PRIMARY KEY, status TEXT NOT NULL, started_at TEXT NOT NULL,
                finished_at TEXT, error TEXT)''')
            history.db.execute('CREATE TABLE ops_attempts (attempt_id INTEGER PRIMARY KEY, run_id TEXT NOT NULL)')
            history.db.execute('PRAGMA user_version=1')
        adapter = CheckpointHistory(path, store, None, 'initialization')
        try:
            adapter.checkpoint()
        finally:
            adapter.close()
    finally:
        history.close()


def recover(history, mode, attempt_id, confirm_run_id):
    db = history.db
    if mode == 'recover-run':
        if pending(db):
            raise OperationsError('Reconcile the unresolved SMTP attempt before recovering its run.')
        row = db.execute("SELECT run_id FROM ops_runs WHERE run_id=? AND status='running'", (confirm_run_id,)).fetchone()
        if not row:
            raise OperationsError('No matching interrupted run; recovery refused.')
    else:
        row = db.execute('''SELECT ops_attempts.run_id FROM alerts JOIN ops_attempts ON alerts.id=ops_attempts.attempt_id
                            WHERE alerts.id=? AND alerts.status IN ('attempting','ambiguous')''', (attempt_id,)).fetchone()
        if not row or row[0] != confirm_run_id:
            raise OperationsError('Attempt and original run do not match; reconciliation refused.')
    history.store.ensure_run_finished(confirm_run_id)
    with db:
        if mode != 'recover-run':
            status = 'submitted' if mode == 'confirm-submitted' else 'failed'
            db.execute('UPDATE alerts SET status=?, submission_result=?, error=NULL WHERE id=?',
                       (status, 'Operator reconciled against provider evidence: ' + mode, attempt_id))
        db.execute("UPDATE ops_runs SET status='reconciled',finished_at=? WHERE run_id=?", (utc_now(), confirm_run_id))
        db.execute('INSERT INTO ops_runs VALUES (?,?,?,?,?)',
                   (history.run_id, mode, utc_now(), utc_now(), None))
    history.checkpoint()
    return 0


def execute(store, config, mode, run_id, attempt_id=0, confirm_run_id=''):
    if mode not in MODES or not re.fullmatch(r'\d+:\d+', run_id):
        raise OperationsError('Invalid operation or workflow run identity.')
    content, sha = store.read(STATE_PATH)
    with tempfile.TemporaryDirectory(prefix='anomaly-private-') as directory:
        path = Path(directory) / 'alerts.sqlite3'
        if mode == 'initialize':
            if content is not None:
                raise OperationsError('History already exists; initialization cannot reset it.')
            initialize(path, store)
            logger.info('event=private_state_initialized')
            return 0
        if content is None:
            raise OperationsError('Private history missing; explicit initialization required. Never reset lost history.')
        path.write_bytes(content)
        validate_history(path)
        history = CheckpointHistory(path, store, sha, run_id)
        try:
            if mode in ('recover-run', 'confirm-submitted', 'confirm-not-sent'):
                return recover(history, mode, attempt_id, confirm_run_id)
            unresolved = pending(history.db)
            active = history.db.execute("SELECT run_id FROM ops_runs WHERE status='running' LIMIT 1").fetchone()
            if unresolved or active:
                logger.error('event=private_recovery_required attempt_id=%s original_run=%s',
                             unresolved[0] if unresolved else 'none',
                             history.db.execute('SELECT run_id FROM ops_attempts WHERE attempt_id=?',
                                                (unresolved[0],)).fetchone()[0] if unresolved else active[0])
                raise OperationsError('History has an interrupted run or uncertain submission; manual reconciliation required.')
            with history.db:
                history.db.execute('INSERT INTO ops_runs VALUES (?,?,?,?,?)', (run_id, 'running', utc_now(), None, None))
            history.checkpoint()  # Remote compare-and-swap claims this execution before any send.
            try:
                data, _ = store.read(INPUT_PATH)
                if data is None:
                    raise OperationsError('Private Excel input missing.')
                excel = Path(directory) / 'business.xlsx'
                excel.write_bytes(data)
                if mode == 'live':
                    if not config.email_configured:
                        raise OperationsError('Live operation requires complete SMTP configuration.')
                    config.validate_email()
                settings = replace(config, excel_path=excel, database_dir=Path(directory))
                # run() closes its history; reuse the restored/checkpointed instance.
                result = run(settings, dry_run=mode == 'dry-run', history_factory=lambda unused: history)
                history = CheckpointHistory(path, store, history.sha, run_id)
            except StorageError:
                # A remote write may have succeeded without an acknowledgement. Never
                # overwrite or reclassify that uncertain checkpoint in a cleanup handler.
                raise
            except Exception as exc:
                # run() may have closed the connection; preserve the latest acknowledged SHA.
                history.close()
                history = CheckpointHistory(path, store, history.sha, run_id)
                with history.db:
                    history.db.execute("UPDATE ops_runs SET status='failed',finished_at=?,error=? WHERE run_id=?",
                                       (utc_now(), type(exc).__name__, run_id))
                history.checkpoint()
                raise OperationsError('Monitoring failed; safe error category saved in private history.') from None
            with history.db:
                history.db.execute('UPDATE ops_runs SET status=?,finished_at=? WHERE run_id=?',
                                   ('completed' if result == 0 else 'failed', utc_now(), run_id))
            history.checkpoint()
            return result
        finally:
            history.close()


def main():
    parser = argparse.ArgumentParser(description='Private Actions persistence adapter; no public storage.')
    parser.add_argument('--mode', choices=MODES, default=os.getenv('OPERATIONS_MODE', 'dry-run'))
    args = parser.parse_args()
    logging.Formatter.converter = time.gmtime
    logging.basicConfig(level=logging.INFO, format='%(asctime)sZ level=%(levelname)s %(message)s', datefmt='%Y-%m-%dT%H:%M:%S')
    try:
        store = GithubStore(os.getenv('GITHUB_REPOSITORY', ''), os.getenv('GITHUB_TOKEN', ''))
        if os.getenv('GITHUB_REF') != 'refs/heads/' + store.branch:
            raise OperationsError('Operations require the private default branch.')
        result = execute(store, load_config(), args.mode,
                         os.getenv('GITHUB_RUN_ID', '') + ':' + os.getenv('GITHUB_RUN_ATTEMPT', ''),
                         int(os.getenv('RECOVERY_ATTEMPT_ID', '') or '0'), os.getenv('RECOVERY_RUN_ID', ''))
        logger.info('event=private_operation_complete exit_code=%s', result)
        return result
    except OperationsError as exc:
        logger.error('event=private_operation_failed detail=%s', exc)
        return 5
    except Exception as exc:
        logger.error('event=private_operation_failed category=%s', type(exc).__name__)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
