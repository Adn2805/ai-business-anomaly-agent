from decimal import Decimal
from app.alert_history import AlertHistory, signature
from app.anomaly_detector import detect


def test_persistence(records, tmp_path):
    records[-1]['Revenue'] = Decimal(5)
    findings = detect(records)
    key, payload = signature(findings)
    path = tmp_path / 'alerts.sqlite3'
    history = AlertHistory(path)
    row = history.record(findings[0].reporting_date, key, payload, 'attempting', attempted=True)
    history.finish(row, 'submitted', 'accepted')
    history.close()
    reopened = AlertHistory(path)
    assert reopened.submitted(key)
    assert reopened.db.execute('SELECT findings FROM alerts').fetchone()[0] == payload
    reopened.close()
    records[-1]['Revenue'] = Decimal(6)
    assert signature(detect(records))[0] != key


def test_signature_ignores_number_format(records):
    records[-1]['Revenue'] = Decimal('5')
    key = signature(detect(records))[0]
    records[-1]['Revenue'] = Decimal('5.00')
    assert signature(detect(records))[0] == key
