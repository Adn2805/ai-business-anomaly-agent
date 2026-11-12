from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from .data_loader import METRICS, ValidationError


@dataclass(frozen=True)
class Finding:
    reporting_date: date
    metric: str
    current_value: Decimal
    historical_baseline: Decimal
    absolute_difference: Decimal
    percentage_change: Decimal | None
    direction: str
    anomaly: bool
    interpretation: str


def detect(records, window=7, threshold=Decimal('20')):
    threshold = Decimal(str(threshold))
    if window < 1 or not threshold.is_finite() or threshold <= 0:
        raise ValidationError('Window and threshold must be positive.')
    if len(records) < window + 1:
        raise ValidationError(f'Insufficient history: need {window} previous daily observations.')
    recent = records[-window - 1:]
    if any(b['Date'] - a['Date'] != timedelta(days=1) for a, b in zip(recent, recent[1:])):
        raise ValidationError('Latest baseline window contains missing daily dates.')
    latest = recent[-1]
    findings = []
    for metric in METRICS:
        baseline = sum((r[metric] for r in recent[:-1]), Decimal(0)) / window
        current = latest[metric]
        difference = current - baseline
        percentage = difference / baseline * 100 if baseline else None
        direction = 'increase' if difference > 0 else 'decrease' if difference < 0 else 'unchanged'
        anomaly = abs(percentage) >= threshold if percentage is not None else current > 0
        unfavorable = (metric in ('Cost', 'Refunds') and direction == 'increase') or (
            metric not in ('Cost', 'Refunds') and direction == 'decrease')
        if not anomaly:
            interpretation = 'Within the configured movement threshold.'
        elif unfavorable:
            impact = {
                'Revenue': 'pressure on sales income',
                'Orders': 'lower purchase volume',
                'Conversion_Rate': 'reduced efficiency in turning visits into orders',
                'Traffic': 'reduced audience reach',
                'Cost': 'higher spending and potential pressure on margins',
                'Refunds': 'higher refund losses and potential pressure on retained revenue',
            }[metric]
            interpretation = f'Potentially unfavorable: this may indicate {impact} and may warrant investigation.'
        else:
            interpretation = 'Notable movement; business significance depends on context and may warrant investigation.'
        findings.append(Finding(latest['Date'], metric, current, baseline, abs(difference),
                                percentage, direction, anomaly, interpretation))
    return findings
