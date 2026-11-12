from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
import os
import re


@dataclass(frozen=True)
class Config:
    excel_path: Path = Path('data/sample_business_data.xlsx')
    reports_dir: Path = Path('reports')
    database_dir: Path = Path('state')
    baseline_window: int = 7
    anomaly_threshold: Decimal = Decimal('20')
    smtp_host: str = ''
    smtp_port: int = 587
    smtp_username: str = field(default='', repr=False)
    smtp_password: str = field(default='', repr=False)
    smtp_from: str = ''
    alert_recipients: tuple = ()
    smtp_security: str = 'starttls'
    smtp_timeout: int = 30

    @property
    def email_configured(self):
        return bool(self.smtp_host and self.smtp_from and self.alert_recipients)

    def validate_email(self):
        if self.smtp_security not in ('starttls', 'ssl'):
            raise ValueError('SMTP_SECURITY must be starttls or ssl.')
        if not 1 <= self.smtp_port <= 65535 or self.smtp_timeout <= 0:
            raise ValueError('SMTP port or timeout is invalid.')
        if bool(self.smtp_username) != bool(self.smtp_password):
            raise ValueError('SMTP username and password must both be supplied, or both omitted for a trusted relay.')
        if any(not re.fullmatch(r'[^\s@,<>]+@[^\s@,<>]+', address)
               for address in (self.smtp_from, *self.alert_recipients)):
            raise ValueError('SMTP addresses must be plain email addresses without display names.')


def load_config():
    try:
        config = Config(
            excel_path=Path(os.getenv('EXCEL_PATH', 'data/sample_business_data.xlsx')),
            reports_dir=Path(os.getenv('REPORTS_DIR', 'reports')),
            database_dir=Path(os.getenv('DATABASE_DIR', 'state')),
            baseline_window=int(os.getenv('BASELINE_WINDOW', '7')),
            anomaly_threshold=Decimal(os.getenv('ANOMALY_THRESHOLD', '20')),
            smtp_host=os.getenv('SMTP_HOST', ''), smtp_port=int(os.getenv('SMTP_PORT', '587')),
            smtp_username=os.getenv('SMTP_USERNAME', ''), smtp_password=os.getenv('SMTP_PASSWORD', ''),
            smtp_from=os.getenv('SMTP_FROM', ''),
            alert_recipients=tuple(x.strip() for x in os.getenv('ALERT_RECIPIENTS', '').split(',') if x.strip()),
            smtp_security=os.getenv('SMTP_SECURITY', 'starttls'), smtp_timeout=int(os.getenv('SMTP_TIMEOUT', '30')))
        if config.baseline_window < 1 or not config.anomaly_threshold.is_finite() or config.anomaly_threshold <= 0:
            raise ValueError
        return config
    except (ValueError, InvalidOperation) as exc:
        raise ValueError('Invalid numeric configuration; check baseline, threshold, SMTP port and timeout.') from exc
