from dataclasses import replace
from decimal import Decimal
import smtplib
from unittest.mock import Mock

import pytest

from app.config import Config
from app.anomaly_detector import detect
from app.alert_history import AlertHistory
from app.email_alert import build_message, deliver, submit_message
from app.report_generator import render_reports


@pytest.fixture
def setup(records, tmp_path):
    records[-1]['Revenue'] = Decimal(5)
    findings = detect(records)
    html, text = render_reports(findings, 7, 20)
    config = Config(smtp_host='smtp.example.test', smtp_from='agent@example.test',
                    alert_recipients=('one@example.test', 'two@example.test'))
    history = AlertHistory(tmp_path / 'history.sqlite3')
    yield config, findings, html, text, history
    history.close()


def test_message(setup):
    c, f, h, t, _ = setup
    message = build_message(c, f, h, t)
    assert '2026-01-08' in message['Subject'] and 'Revenue' in message['Subject']
    assert message['To'] == 'one@example.test, two@example.test'
    assert 'Baseline' in message.get_body(preferencelist=('plain',)).get_content()
    assert 'Executive summary' in message.get_body(preferencelist=('html',)).get_content()


@pytest.mark.parametrize('mode', ['dry_run', 'not_configured', 'no_anomalies'])
def test_no_send(setup, monkeypatch, mode):
    c, f, h, t, history = setup
    sender = Mock(side_effect=AssertionError('Must not send'))
    monkeypatch.setattr('app.email_alert.submit_message', sender)
    if mode == 'not_configured':
        c = replace(c, smtp_host='')
    if mode == 'no_anomalies':
        f = [replace(x, anomaly=False) for x in f]
    assert deliver(c, f, h, t, history, dry_run=mode == 'dry_run') == mode
    sender.assert_not_called()


def test_failed_retry_and_duplicate(setup, monkeypatch):
    c, f, h, t, history = setup
    sender = Mock(side_effect=[smtplib.SMTPException('secret-password'), None])
    monkeypatch.setattr('app.email_alert.submit_message', sender)
    assert deliver(c, f, h, t, history) == 'failed'
    assert deliver(c, f, h, t, history) == 'submitted'
    assert deliver(c, f, h, t, history) == 'duplicate_skipped'
    assert sender.call_count == 2
    rows = history.db.execute('SELECT status, attempted_at, error FROM alerts').fetchall()
    assert rows[0][1] and rows[0][2] and 'secret-password' not in rows[0][2]
    assert [r[0] for r in rows] == ['failed', 'submitted', 'duplicate_skipped']


@pytest.mark.parametrize('security', ['starttls', 'ssl'])
def test_secure_transport(setup, monkeypatch, security):
    c, f, h, t, _ = setup
    c = replace(c, smtp_security=security, smtp_username='user', smtp_password='password')
    client = Mock()
    client.send_message.return_value = {}
    factory = Mock(return_value=client)
    monkeypatch.setattr('app.email_alert.smtplib.SMTP' if security == 'starttls' else 'app.email_alert.smtplib.SMTP_SSL', factory)
    submit_message(c, build_message(c, f, h, t))
    assert factory.call_args.kwargs['timeout'] == 30
    if security == 'starttls':
        assert client.starttls.call_args.kwargs['context'].check_hostname
    else:
        assert factory.call_args.kwargs['context'].check_hostname
    client.login.assert_called_once_with('user', 'password')
    client.close.assert_called_once()


def test_partial_rejection(setup, monkeypatch):
    c, f, h, t, history = setup
    client = Mock()
    client.send_message.return_value = {'two@example.test': (550, b'refused')}
    monkeypatch.setattr('app.email_alert.smtplib.SMTP', Mock(return_value=client))
    assert deliver(c, f, h, t, history) == 'failed'


def test_bad_email_settings(setup):
    c, f, h, t, history = setup
    assert deliver(replace(c, smtp_security='plain'), f, h, t, history) == 'failed'


def test_close_failure_after_acceptance_does_not_resend(setup, monkeypatch):
    c, f, h, t, history = setup
    client = Mock()
    client.send_message.return_value = {}
    client.close.side_effect = OSError('connection cleanup failed')
    monkeypatch.setattr('app.email_alert.smtplib.SMTP', Mock(return_value=client))
    assert deliver(c, f, h, t, history) == 'submitted'
    assert deliver(c, f, h, t, history) == 'duplicate_skipped'
    client.send_message.assert_called_once()


def test_close_failure_preserves_submission_failure(setup, monkeypatch):
    c, f, h, t, history = setup
    client = Mock()
    client.send_message.side_effect = smtplib.SMTPDataError(550, b'rejected')
    client.close.side_effect = OSError('connection cleanup failed')
    monkeypatch.setattr('app.email_alert.smtplib.SMTP', Mock(return_value=client))
    assert deliver(c, f, h, t, history) == 'failed'
    error = history.db.execute('SELECT error FROM alerts').fetchone()[0]
    assert error.startswith('SMTPDataError:')
