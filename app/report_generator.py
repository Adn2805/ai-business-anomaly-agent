from html import escape
from pathlib import Path
import os
import tempfile

from .summarizer import movement, summarize


def render_reports(findings, window, threshold):
    status = 'Attention required' if any(f.anomaly for f in findings) else 'Normal'
    day = findings[0].reporting_date.isoformat()
    summary = summarize(findings)
    method = f'Baseline: previous {window} consecutive daily observations. Absolute deviation threshold: {threshold}%.'
    caveat = ('Conversion_Rate values are percentage points; movement is relative percent change. '
              'Monetary values use the input currency. Seasonality, holidays and promotions may cause false positives. '
              'This report does not establish causes.')
    headings = ['Metric', 'Current', 'Baseline', 'Absolute difference', 'Movement', 'Direction', 'Attention', 'Possible business impact']
    rows = []
    for f in findings:
        rows.append([f.metric, f'{f.current_value:,.2f}', f'{f.historical_baseline:,.2f}',
                     f'{f.absolute_difference:,.2f}', movement(f), f.direction,
                     'Review anomaly' if f.anomaly else 'Normal', f.interpretation])
    anomalies = ', '.join(f.metric for f in findings if f.anomaly) or 'None'
    intro = f'AI Business Anomaly Agent\nReporting date: {day}\nMonitoring status: {status}\n\n{summary}\n\n{method}\nDetected anomalies: {anomalies}'
    text = intro + '\n\nMetrics evaluated\n' + '\n\n'.join(
        '\n'.join(f'{h}: {v}' for h, v in zip(headings, row)) for row in rows) + '\n\n' + caveat + '\n'
    table = ''.join('<tr>' + ''.join(f'<td>{escape(v)}</td>' for v in row) + '</tr>' for row in rows)
    html = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Business anomaly report — {day}</title>
<style>body{{font:16px/1.5 Arial,sans-serif;color:#203047;background:#f3f5f8;margin:0;padding:28px}}
main{{max-width:1250px;margin:auto;background:white;padding:28px;border-radius:8px}}
h1{{margin-top:0}}.status{{font-weight:bold;color:#714800}}table{{border-collapse:collapse;width:100%;font-size:14px}}
th,td{{text-align:left;padding:12px;border-bottom:1px solid #dde3ea;vertical-align:top}}th{{background:#203047;color:white}}
.scroll{{overflow-x:auto}}footer{{margin-top:24px;color:#526171}}</style></head><body><main>
<h1>AI Business Anomaly Agent</h1><p>Reporting date: {day}</p><p class="status">Monitoring status: {status}</p>
<h2>Executive summary</h2><p>{escape(summary)}</p><p>{escape(method)}</p>
<h2>Detected anomalies</h2><p>{escape(anomalies)}</p><h2>Metrics evaluated</h2><div class="scroll"><table>
<thead><tr>{''.join('<th scope="col">' + escape(h) + '</th>' for h in headings)}</tr></thead><tbody>{table}</tbody>
</table></div><footer>{escape(caveat)}</footer></main></body></html>'''
    return html, text


def save_reports(directory, day, html, text):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for extension, content in [('html', html), ('txt', text)]:
        target = directory / f'anomaly-report-{day}.{extension}'
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory, delete=False) as handle:
                temporary = handle.name
                handle.write(content)
            os.replace(temporary, target)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
