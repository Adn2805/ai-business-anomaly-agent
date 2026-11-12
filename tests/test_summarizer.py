from decimal import Decimal
from app.anomaly_detector import detect
from app.summarizer import summarize
from app.report_generator import render_reports, save_reports


def test_normal(records):
    findings = detect(records)
    assert summarize(findings).startswith('No significant anomalies')
    html, text = render_reports(findings, 7, 20)
    assert 'Monitoring status: Normal' in html
    assert 'Detected anomalies: None' in text


def test_dynamic_reports(records, tmp_path):
    records[-1]['Revenue'] = Decimal(7)
    records[-1]['Cost'] = Decimal(15)
    findings = detect(records)
    summary = summarize(findings)
    assert 'Revenue decrease (-30.00%)' in summary
    assert 'Cost increase (+50.00%)' in summary
    assert 'may warrant' in summary
    html, text = render_reports(findings, 7, 20)
    for metric in records[0].keys() - {'Date'}:
        assert metric in html and metric in text
    assert '<table>' in html and 'Absolute difference' in text
    save_reports(tmp_path, findings[0].reporting_date, html, text)
    assert (tmp_path / 'anomaly-report-2026-01-08.html').read_text(encoding='utf-8') == html
    assert (tmp_path / 'anomaly-report-2026-01-08.txt').read_text(encoding='utf-8') == text


def test_zero_explanation(records):
    for r in records[:-1]:
        r['Revenue'] = Decimal(0)
    html, text = render_reports(detect(records), 7, 20)
    assert 'undefined for zero baseline' in html and 'undefined for zero baseline' in text
