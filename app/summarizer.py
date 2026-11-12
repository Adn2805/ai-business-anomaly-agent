def movement(finding):
    if finding.percentage_change is None:
        return 'percentage change undefined for zero baseline'
    return f'{finding.percentage_change:+.2f}%'


def summarize(findings):
    anomalies = [f for f in findings if f.anomaly]
    if not anomalies:
        return 'No significant anomalies were detected in the latest reporting period.'
    changes = '; '.join(f'{f.metric.replace("_", " ")} {f.direction} ({movement(f)})' for f in anomalies)
    return (f'Compared with recent daily averages: {changes}. '
            'These movements may warrant investigation. Review business context before drawing conclusions about causes.')
