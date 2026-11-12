import argparse
from dataclasses import replace
import logging
from pathlib import Path
import time

from dotenv import load_dotenv
from filelock import FileLock, Timeout

from .config import load_config
from .data_loader import load_data, ValidationError
from .anomaly_detector import detect
from .report_generator import render_reports, save_reports
from .alert_history import AlertHistory
from .email_alert import deliver

logger = logging.getLogger(__name__)


def run(config, dry_run=False, history_factory=AlertHistory):
    config.database_dir.mkdir(parents=True, exist_ok=True)
    with FileLock(str(config.database_dir / 'monitor.lock'), timeout=0):
        records = load_data(config.excel_path)
        findings = detect(records, config.baseline_window, config.anomaly_threshold)
        html, text = render_reports(findings, config.baseline_window, config.anomaly_threshold)
        save_reports(config.reports_dir, findings[0].reporting_date, html, text)
        history = history_factory(config.database_dir / 'alerts.sqlite3')
        try:
            status = deliver(config, findings, html, text, history, dry_run)
        finally:
            history.close()
        logger.info('event=monitor_complete reporting_date=%s metrics=%s anomalies=%s email_status=%s',
                    findings[0].reporting_date, len(findings), sum(f.anomaly for f in findings), status)
        return 3 if status == 'failed' else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='Monitor the latest daily Excel business metrics.')
    parser.add_argument('--excel-path', type=Path)
    parser.add_argument('--dry-run', action='store_true', help='Generate reports and history without sending email.')
    args = parser.parse_args(argv)
    logging.Formatter.converter = time.gmtime
    logging.basicConfig(level=logging.INFO, format='%(asctime)sZ level=%(levelname)s %(message)s', datefmt='%Y-%m-%dT%H:%M:%S')
    load_dotenv('.env', override=False)
    try:
        config = load_config()
        if args.excel_path:
            config = replace(config, excel_path=args.excel_path)
        return run(config, args.dry_run)
    except (ValidationError, ValueError) as exc:
        logger.error('event=validation_failed detail=%s', exc)
        return 2
    except Timeout:
        logger.error('event=run_locked detail=Another monitoring process holds the history lock')
        return 4
    except Exception as exc:
        logger.error('event=unexpected_failure category=%s', type(exc).__name__)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
