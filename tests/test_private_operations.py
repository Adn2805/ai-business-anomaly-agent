import hashlib
from pathlib import Path
import smtplib
import sqlite3
from unittest.mock import Mock

import pytest

from app.config import Config
from app.private_operations import execute
from app.private_store import INPUT_PATH, STATE_PATH, OperationsError, StorageError


def inspect_state(content, query):
    db = sqlite3.connect(':memory:')
    try:
        db.deserialize(content)
        return db.execute(query).fetchall()
    finally:
        db.close()


class MemoryStore:
    """Mock private remote file service with conditional revision writes."""
    def __init__(self):
        self.content = None
        self.sha = None
        self.input = (Path(__file__).resolve().parents[1] / 'data/sample_business_data.xlsx').read_bytes()
        self.saved = []
        self.fail = lambda content: False
        self.accept_then_fail = False
        self.finished = True

    def read(self, path):
        return (self.content, self.sha) if path == STATE_PATH else (self.input, 'input-revision')

    def save(self, content, previous_sha):
        if previous_sha != self.sha:
            raise StorageError('Conflict; no overwrite.')
        failure = self.fail(content)
        if failure and not self.accept_then_fail:
            raise StorageError('Simulated persistence failure.')
        self.content = content
        self.sha = hashlib.sha1(content).hexdigest()
        self.saved.append(content)
        if failure:
            raise StorageError('Simulated lost acknowledgement.')
        return self.sha

    def ensure_run_finished(self, run_id):
        if not self.finished:
            raise OperationsError('Original workflow is still running.')


@pytest.fixture
def setup(tmp_path, monkeypatch):
    # A nonsynced writable temp root is selected by pytest in restricted environments.
    monkeypatch.setattr('tempfile.tempdir', str(tmp_path))
    store = MemoryStore()
    config = Config(reports_dir=tmp_path / 'reports', smtp_host='smtp.example.test',
                    smtp_from='agent@example.test', alert_recipients=('boss@example.test',))
    sender = Mock()
    monkeypatch.setattr('app.email_alert.submit_message', sender)
    return store, config, sender


def statuses(store):
    return inspect_state(store.content, 'SELECT status FROM alerts ORDER BY id')


def initialize(setup):
    store, config, _ = setup
    assert execute(store, config, 'initialize', '1:1') == 0
    return store, config


def test_explicit_initial_state_and_no_reset(setup):
    store, config, sender = setup
    with pytest.raises(OperationsError, match='initialization required'):
        execute(store, config, 'dry-run', '1:1')
    assert store.content is None
    initialize(setup)
    original = store.content
    assert inspect_state(original, 'PRAGMA integrity_check') == [('ok',)]
    with pytest.raises(OperationsError, match='cannot reset'):
        execute(store, config, 'initialize', '2:1')
    assert store.content == original
    sender.assert_not_called()


def test_restore_and_duplicate_across_separate_executions(setup):
    store, config = initialize(setup)
    sender = setup[2]
    def inspect_before_sending(*args):
        assert statuses(store) == [('attempting',)]  # Durable before SMTP call.
    sender.side_effect = inspect_before_sending
    assert execute(store, config, 'live', '2:1') == 0
    assert statuses(store) == [('submitted',)]
    assert execute(store, config, 'live', '3:1') == 0
    assert statuses(store) == [('submitted',), ('duplicate_skipped',)]
    sender.assert_called_once()
    assert inspect_state(store.content, 'SELECT status FROM ops_runs') == [('completed',), ('completed',)]


def test_dry_run_never_sends_and_does_not_suppress_live(setup):
    store, config = initialize(setup)
    assert execute(store, config, 'dry-run', '2:1') == 0
    setup[2].assert_not_called()
    assert execute(store, config, 'live', '3:1') == 0
    assert statuses(store) == [('dry_run',), ('submitted',)]


@pytest.mark.parametrize('input_value', [None, b'invalid workbook'])
def test_invalid_input_failure_persists_and_can_retry(setup, input_value):
    store, config = initialize(setup)
    original = store.input
    store.input = input_value
    with pytest.raises(OperationsError, match='Monitoring failed'):
        execute(store, config, 'live', '2:1')
    setup[2].assert_not_called()
    assert inspect_state(store.content, 'SELECT status FROM ops_runs') == [('failed',)]
    assert statuses(store) == []
    store.input = original
    assert execute(store, config, 'live', '3:1') == 0


def test_corrupt_history_never_replaced(setup):
    store, config = initialize(setup)
    store.content = b'not sqlite'
    before = len(store.saved)
    with pytest.raises(OperationsError, match='corrupt'):
        execute(store, config, 'live', '2:1')
    assert len(store.saved) == before
    setup[2].assert_not_called()


def test_pre_send_checkpoint_failure_prevents_email(setup):
    store, config = initialize(setup)
    store.fail = lambda content: bool(inspect_state(content, "SELECT 1 FROM alerts WHERE status='attempting'"))
    with pytest.raises(StorageError):
        execute(store, config, 'live', '2:1')
    setup[2].assert_not_called()
    assert statuses(store) == []
    store.fail = lambda content: False
    with pytest.raises(OperationsError, match='interrupted'):
        execute(store, config, 'live', '3:1')
    assert execute(store, config, 'recover-run', '4:1', confirm_run_id='2:1') == 0
    assert execute(store, config, 'live', '5:1') == 0


@pytest.mark.parametrize('ack_lost', [False, True])
def test_smtp_success_then_checkpoint_failure_never_blind_retry(setup, ack_lost):
    store, config = initialize(setup)
    store.fail = lambda content: bool(inspect_state(content, "SELECT 1 FROM alerts WHERE status='submitted'"))
    store.accept_then_fail = ack_lost
    with pytest.raises(StorageError):
        execute(store, config, 'live', '2:1')
    setup[2].assert_called_once()
    assert statuses(store) == [('submitted' if ack_lost else 'attempting',)]
    store.fail = lambda content: False
    with pytest.raises(OperationsError, match='interrupted'):
        execute(store, config, 'live', '3:1')
    setup[2].assert_called_once()
    mode = 'recover-run' if ack_lost else 'confirm-submitted'
    assert execute(store, config, mode, '4:1', attempt_id=1, confirm_run_id='2:1') == 0
    assert execute(store, config, 'live', '5:1') == 0
    setup[2].assert_called_once()
    assert statuses(store)[-1] == ('duplicate_skipped',)


def test_failure_after_submitted_checkpoint_preserves_success(setup):
    store, config = initialize(setup)
    store.fail = lambda content: bool(inspect_state(content, "SELECT 1 FROM ops_runs WHERE status='completed'"))
    with pytest.raises(StorageError):
        execute(store, config, 'live', '2:1')
    assert statuses(store) == [('submitted',)]
    store.fail = lambda content: False
    assert execute(store, config, 'recover-run', '3:1', confirm_run_id='2:1') == 0
    assert execute(store, config, 'live', '4:1') == 0
    setup[2].assert_called_once()


def test_definite_smtp_rejection_is_retryable(setup):
    store, config = initialize(setup)
    setup[2].side_effect = [smtplib.SMTPAuthenticationError(535, b'secret'), None]
    assert execute(store, config, 'live', '2:1') == 3
    assert statuses(store) == [('failed',)]
    assert execute(store, config, 'live', '3:1') == 0
    assert statuses(store) == [('failed',), ('submitted',)]


@pytest.mark.parametrize('error', [smtplib.SMTPServerDisconnected('secret'), smtplib.SMTPException('partial'), TimeoutError('secret')])
def test_uncertain_smtp_failure_requires_reconciliation(setup, error):
    store, config = initialize(setup)
    setup[2].side_effect = error
    assert execute(store, config, 'live', '2:1') == 3
    assert statuses(store) == [('ambiguous',)]
    with pytest.raises(OperationsError, match='uncertain'):
        execute(store, config, 'live', '3:1')
    with pytest.raises(OperationsError, match='Reconcile'):
        execute(store, config, 'recover-run', '4:1', confirm_run_id='2:1')
    setup[2].assert_called_once()
    assert execute(store, config, 'confirm-not-sent', '5:1', attempt_id=1, confirm_run_id='2:1') == 0
    setup[2].side_effect = None
    assert execute(store, config, 'live', '6:1') == 0


def test_recovery_refuses_active_original_run(setup):
    store, config = initialize(setup)
    setup[2].side_effect = smtplib.SMTPServerDisconnected()
    execute(store, config, 'live', '2:1')
    store.finished = False
    before = store.content
    with pytest.raises(OperationsError, match='still running'):
        execute(store, config, 'confirm-submitted', '3:1', attempt_id=1, confirm_run_id='2:1')
    assert store.content == before
    with pytest.raises(OperationsError, match='do not match'):
        execute(store, config, 'confirm-submitted', '4:1', attempt_id=1, confirm_run_id='999:1')


def test_concurrent_revision_conflict_stops_before_smtp(setup, monkeypatch):
    store, config = initialize(setup)
    original = store.save
    def concurrent_save(content, sha):
        store.sha = 'another-run-claimed-the-state'
        return original(content, sha)
    monkeypatch.setattr(store, 'save', concurrent_save)
    with pytest.raises(StorageError, match='Conflict'):
        execute(store, config, 'live', '2:1')
    setup[2].assert_not_called()


def test_missing_live_smtp_does_not_report_success(setup):
    from dataclasses import replace
    store, config = initialize(setup)
    with pytest.raises(OperationsError, match='Monitoring failed'):
        execute(store, replace(config, smtp_host=''), 'live', '2:1')
    assert inspect_state(store.content, 'SELECT status FROM ops_runs') == [('failed',)]
    setup[2].assert_not_called()


def test_interrupted_smtp_leaves_durable_attempt_and_blocks_retry(setup):
    store, config = initialize(setup)
    setup[2].side_effect = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        execute(store, config, 'live', '2:1')
    assert statuses(store) == [('attempting',)]
    assert inspect_state(store.content, 'SELECT status FROM ops_runs') == [('running',)]
    with pytest.raises(OperationsError, match='interrupted'):
        execute(store, config, 'live', '3:1')
    setup[2].assert_called_once()


def test_updated_private_excel_is_loaded_each_execution(setup, excel):
    store, config = initialize(setup)
    sample = store.input
    store.input = excel().read_bytes()  # Eight normal synthetic days.
    assert execute(store, config, 'live', '2:1') == 0
    setup[2].assert_not_called()
    assert statuses(store) == []
    store.input = sample
    assert execute(store, config, 'live', '3:1') == 0
    setup[2].assert_called_once()


def test_initialization_acknowledgement_lost_never_resets_history(setup):
    store, config, sender = setup
    store.fail = lambda content: True
    store.accept_then_fail = True
    with pytest.raises(StorageError):
        execute(store, config, 'initialize', '1:1')
    original = store.content
    store.fail = lambda content: False
    with pytest.raises(OperationsError, match='cannot reset'):
        execute(store, config, 'initialize', '2:1')
    assert store.content == original
    assert execute(store, config, 'dry-run', '3:1') == 0
    sender.assert_not_called()


def test_failure_checkpoint_loss_blocks_even_a_definite_rejection(setup):
    store, config = initialize(setup)
    setup[2].side_effect = smtplib.SMTPAuthenticationError(535, b'rejected')
    store.fail = lambda content: bool(inspect_state(content, "SELECT 1 FROM alerts WHERE status='failed'"))
    with pytest.raises(StorageError):
        execute(store, config, 'live', '2:1')
    assert statuses(store) == [('attempting',)]
    store.fail = lambda content: False
    with pytest.raises(OperationsError, match='interrupted'):
        execute(store, config, 'live', '3:1')
    setup[2].assert_called_once()
