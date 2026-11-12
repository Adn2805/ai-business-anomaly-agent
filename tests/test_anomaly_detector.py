from decimal import Decimal
from datetime import timedelta

import pytest

from app.anomaly_detector import detect
from app.data_loader import METRICS, ValidationError


@pytest.mark.parametrize('value,percentage,direction,anomaly', [
    ('10', '0', 'unchanged', False), ('11', '10', 'increase', False),
    ('12', '20', 'increase', True), ('8', '-20', 'decrease', True),
    ('7', '-30', 'decrease', True), ('11.999', '19.99', 'increase', False)])
@pytest.mark.parametrize('metric', METRICS)
def test_movements(records, metric, value, percentage, direction, anomaly):
    records[-1][metric] = Decimal(value)
    result = next(f for f in detect(records) if f.metric == metric)
    assert result.historical_baseline == 10
    assert result.percentage_change == Decimal(percentage)
    assert result.absolute_difference == abs(Decimal(value) - 10)
    assert result.direction == direction
    assert result.anomaly is anomaly


@pytest.mark.parametrize('current,flag', [(0, False), (5, True)])
def test_zero(records, current, flag):
    for row in records:
        row['Refunds'] = Decimal(0)
    records[-1]['Refunds'] = Decimal(current)
    result = detect(records)[-1]
    assert result.percentage_change is None
    assert result.anomaly is flag


def test_history_and_gap(records):
    with pytest.raises(ValidationError, match='Insufficient'):
        detect(records[:7])
    records[-1]['Date'] += timedelta(days=1)
    with pytest.raises(ValidationError, match='missing daily'):
        detect(records)


def test_custom_settings(records):
    records[-1]['Revenue'] = Decimal(11)
    assert detect(records, window=3, threshold=10)[0].anomaly
    assert not detect(records, window=3, threshold=11)[0].anomaly


def test_interpretation(records):
    records[-1]['Revenue'] = Decimal(5)
    records[-1]['Cost'] = Decimal(20)
    findings = detect(records)
    assert 'Potentially unfavorable' in findings[0].interpretation
    assert 'Potentially unfavorable' in findings[4].interpretation
    records[-1]['Revenue'] = Decimal(20)
    assert 'Notable movement' in detect(records)[0].interpretation
