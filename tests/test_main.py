from dataclasses import replace
from pathlib import Path
import sqlite3
import os
import subprocess
import sys
from unittest.mock import Mock

from filelock import FileLock
import pytest

from app.config import Config, load_config
from app.main import run, main
from app.data_loader import load_data, ValidationError


def test_end_to_end(excel, tmp_path, monkeypatch):
    path = excel(edit=lambda s: setattr(s['B9'], 'value', 500))
    config = Config(excel_path=path, reports_dir=tmp_path / 'reports', database_dir=tmp_path / 'state',
                    smtp_host='smtp.example.test', smtp_from='agent@example.test', alert_recipients=('boss@example.test',))
    sender = Mock()
    monkeypatch.setattr('app.email_alert.submit_message', sender)
    assert run(config, dry_run=True) == 0
    sender.assert_not_called()
    assert run(config) == 0
    assert run(config) == 0
    sender.assert_called_once()
    assert len(list(config.reports_dir.iterdir())) == 2
    with sqlite3.connect(config.database_dir / 'alerts.sqlite3') as db:
        assert [r[0] for r in db.execute('SELECT status FROM alerts ORDER BY id')] == ['dry_run', 'submitted', 'duplicate_skipped']


def test_invalid_never_sends(excel, tmp_path, monkeypatch):
    config = Config(excel_path=excel(edit=lambda s: setattr(s['B2'], 'value', None)),
                    database_dir=tmp_path / 'state', reports_dir=tmp_path / 'reports')
    sender = Mock()
    monkeypatch.setattr('app.email_alert.submit_message', sender)
    with pytest.raises(ValidationError):
        run(config)
    sender.assert_not_called()
    assert not config.reports_dir.exists()


def test_sample_workbook():
    rows = load_data(Path(__file__).resolve().parents[1] / 'data/sample_business_data.xlsx')
    assert len(rows) >= 30


def test_cli_and_lock(excel, tmp_path, monkeypatch):
    monkeypatch.setenv('EXCEL_PATH', str(excel()))
    monkeypatch.setenv('DATABASE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('REPORTS_DIR', str(tmp_path / 'reports'))
    assert main(['--dry-run']) == 0
    with FileLock(str(tmp_path / 'state/monitor.lock')):
        assert main(['--dry-run']) == 4
    monkeypatch.setenv('BASELINE_WINDOW', '0')
    assert main(['--dry-run']) == 2


@pytest.mark.parametrize('name,value', [('BASELINE_WINDOW','-1'), ('ANOMALY_THRESHOLD','NaN'),
                                     ('ANOMALY_THRESHOLD','0'), ('SMTP_PORT','bad')])
def test_invalid_config(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        load_config()


def test_lock_across_processes(excel, tmp_path):
    state = tmp_path / 'state'
    state.mkdir()
    env = {**os.environ, 'DATABASE_DIR': str(state), 'EXCEL_PATH': str(excel()),
           'REPORTS_DIR': str(tmp_path / 'reports')}
    with FileLock(str(state / 'monitor.lock')):
        result = subprocess.run([sys.executable, '-m', 'app.main', '--dry-run'],
                                env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 4
    assert 'run_locked' in result.stderr
    assert not (state / 'alerts.sqlite3').exists()


def test_smtp_failure_exit(excel, tmp_path, monkeypatch):
    import smtplib
    config = Config(excel_path=excel(edit=lambda s: setattr(s['B9'], 'value', 500)),
                    database_dir=tmp_path / 'state', reports_dir=tmp_path / 'reports',
                    smtp_host='smtp.example.test', smtp_from='agent@example.test', alert_recipients=('boss@example.test',))
    monkeypatch.setattr('app.email_alert.submit_message', Mock(side_effect=smtplib.SMTPException('failed')))
    assert run(config) == 3
    assert len(list(config.reports_dir.iterdir())) == 2
