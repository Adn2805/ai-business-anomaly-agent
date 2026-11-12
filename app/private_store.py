"""Small private-repository file store. No tokens, responses or private URLs in logs."""
import base64
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPRedirectHandler

MAX_BYTES = 5 * 1024 * 1024
STATE_PATH = '.monitor/alerts.sqlite3'
INPUT_PATH = 'input/business.xlsx'


class OperationsError(RuntimeError):
    """Only controlled, secret-safe messages belong in this exception."""


class StorageError(OperationsError):
    """A checkpoint may be unacknowledged: never retry or overwrite it blindly."""


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GithubStore:
    def __init__(self, repository, token):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository) or not token:
            raise OperationsError('Private repository identity or workflow token is missing.')
        self.base = f'https://api.github.com/repos/{repository}'
        self.token = token
        self.opener = build_opener(NoRedirects())
        metadata = self.request('')
        if metadata.get('private') is not True:
            raise OperationsError('Operations require a PRIVATE repository; stopped before file access.')
        self.branch = metadata['default_branch']

    def request(self, suffix, data=None, missing_ok=False):
        body = json.dumps(data).encode() if data is not None else None
        request = Request(self.base + suffix, data=body, method='PUT' if data is not None else 'GET', headers={
            'Authorization': 'Bearer ' + self.token,
            'Accept': 'application/vnd.github+json',
            'Content-Type': 'application/json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': 'business-anomaly-agent',
        })
        try:
            with self.opener.open(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as exc:
            if missing_ok and exc.code == 404:
                return None
            # Do not log HTTP bodies, URLs or exception strings.
            raise StorageError(f'Private storage request failed (HTTP {exc.code}); no automatic retry.') from None
        except (URLError, OSError, ValueError):
            raise StorageError('Private storage response unavailable or invalid; no automatic retry.') from None

    def assert_private(self):
        metadata = self.request('')
        if metadata.get('private') is not True or metadata.get('default_branch') != self.branch:
            raise StorageError('Repository visibility or default branch changed; operations stopped.')

    def read(self, path):
        self.assert_private()
        result = self.request('/contents/' + path + '?ref=' + quote(self.branch, safe=''), missing_ok=True)
        if result is None:
            return None, None
        if result.get('type') != 'file' or result.get('size', MAX_BYTES + 1) > MAX_BYTES:
            raise OperationsError('Private file is invalid or exceeds the 5 MiB safety limit.')
        sha = result.get('sha', '')
        if not re.fullmatch(r'[0-9a-f]{40}', sha):
            raise OperationsError('Private file revision is invalid.')
        if result.get('encoding') != 'base64':
            result = self.request('/git/blobs/' + sha)
        try:
            content = base64.b64decode(''.join(result['content'].split()), validate=True)
        except (ValueError, KeyError):
            raise OperationsError('Private file encoding is invalid.') from None
        if len(content) > MAX_BYTES:
            raise OperationsError('Private file exceeds the 5 MiB safety limit.')
        return content, sha

    def save(self, content, previous_sha):
        self.assert_private()
        if len(content) > MAX_BYTES:
            raise OperationsError('History exceeds the 5 MiB safety limit; maintenance required.')
        data = {'message': 'Checkpoint monitoring history', 'branch': self.branch,
                'content': base64.b64encode(content).decode()}
        if previous_sha is not None:
            data['sha'] = previous_sha
        result = self.request('/contents/' + STATE_PATH, data=data)
        sha = result.get('content', {}).get('sha', '')
        if not re.fullmatch(r'[0-9a-f]{40}', sha):
            raise StorageError('History acknowledgement invalid; stop and inspect remote state.')
        return sha

    def ensure_run_finished(self, run_id):
        if not re.fullmatch(r'\d+:\d+', run_id):
            raise OperationsError('Recovery requires the original GitHub run ID and attempt.')
        identifier, attempt = run_id.split(':')
        result = self.request(f'/actions/runs/{identifier}/attempts/{attempt}')
        if result.get('status') != 'completed':
            raise OperationsError('Original workflow attempt is not completed; recovery refused.')
