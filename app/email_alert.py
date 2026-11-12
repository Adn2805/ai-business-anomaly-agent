from email.message import EmailMessage
from email.utils import formatdate, make_msgid
import logging
import smtplib
import ssl

from .alert_history import signature

logger = logging.getLogger(__name__)


def build_message(config, findings, html, text):
    message = EmailMessage()
    metrics = ', '.join(f.metric for f in findings if f.anomaly)
    message['Subject'] = f'Business anomaly alert | {findings[0].reporting_date} | {metrics}'
    message['From'] = config.smtp_from
    message['To'] = ', '.join(config.alert_recipients)
    message['Date'] = formatdate(localtime=False)
    message['Message-ID'] = make_msgid()
    message.set_content(text)
    message.add_alternative(html, subtype='html')
    return message


def submit_message(config, message):
    context = ssl.create_default_context()
    if config.smtp_security == 'ssl':
        client = smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=config.smtp_timeout, context=context)
    else:
        client = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=config.smtp_timeout)
    # Once DATA is accepted, a later QUIT failure must not turn success into a retry.
    try:
        if config.smtp_security == 'starttls':
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
        if config.smtp_username:
            client.login(config.smtp_username, config.smtp_password)
        refused = client.send_message(message, from_addr=config.smtp_from, to_addrs=config.alert_recipients)
        if refused:
            raise smtplib.SMTPException('Some recipients were refused')
    finally:
        try:
            client.close()
        except OSError:
            # Cleanup must neither erase acceptance nor replace the original failure.
            logger.warning('event=smtp_cleanup_failed detail=Connection cleanup failed; submission result unchanged')


def deliver(config, findings, html, text, history, dry_run=False):
    if not any(f.anomaly for f in findings):
        return 'no_anomalies'
    key, payload = signature(findings)
    day = findings[0].reporting_date
    if history.submitted(key):
        history.record(day, key, payload, 'duplicate_skipped')
        return 'duplicate_skipped'
    if dry_run or not config.email_configured:
        status = 'dry_run' if dry_run else 'not_configured'
        history.record(day, key, payload, status)
        return status
    attempt = history.record(day, key, payload, 'attempting', attempted=True)
    try:
        config.validate_email()
        message = build_message(config, findings, html, text)
        submit_message(config, message)
    except (smtplib.SMTPException, OSError, ValueError) as exc:
        # SMTP responses may echo credentials or addresses. Store only a safe category.
        error = f'{type(exc).__name__}: SMTP submission failed; verify settings, connectivity and server logs.'
        history.finish(attempt, 'failed', 'not confirmed', error)
        logger.error('event=email_failed category=%s', type(exc).__name__)
        return 'failed'
    history.finish(attempt, 'submitted', 'SMTP accepted all recipients; inbox delivery not guaranteed')
    return 'submitted'
