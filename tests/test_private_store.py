import base64
from urllib.error import HTTPError, URLError
from unittest.mock import Mock

import pytest

from app.private_store import GithubStore, MAX_BYTES, NoRedirects, OperationsError, StorageError, STATE_PATH


def fake_request(monkeypatch, responses):
    mock = Mock(side_effect=responses)
    monkeypatch.setattr(GithubStore, 'request', mock)
    return mock


def test_public_repository_rejected_before_file_access(monkeypatch):
    mock = fake_request(monkeypatch, [{'private': False, 'default_branch': 'main'}])
    with pytest.raises(OperationsError, match='PRIVATE'):
        GithubStore('owner/operations', 'fake-secret')
    mock.assert_called_once_with('')


def test_restore_and_conditional_save(monkeypatch):
    private = {'private': True, 'default_branch': 'main'}
    sha = 'a' * 40
    mock = fake_request(monkeypatch, [private, private,
        {'type': 'file', 'size': 5, 'sha': sha, 'encoding': 'base64', 'content': base64.b64encode(b'hello').decode()},
        private, {'content': {'sha': 'b' * 40}}])
    store = GithubStore('owner/operations', 'fake-secret')
    assert store.read(STATE_PATH) == (b'hello', sha)
    assert store.save(b'updated', sha) == 'b' * 40
    payload = mock.call_args.kwargs['data']
    assert payload['sha'] == sha and payload['branch'] == 'main'
    assert base64.b64decode(payload['content']) == b'updated'


def test_visibility_rechecked_before_checkpoint(monkeypatch):
    fake_request(monkeypatch, [{'private': True, 'default_branch': 'main'}, {'private': False, 'default_branch': 'main'}])
    store = GithubStore('owner/operations', 'fake-secret')
    with pytest.raises(StorageError, match='visibility'):
        store.save(b'data', None)


def test_large_file_stops_before_save(monkeypatch):
    private = {'private': True, 'default_branch': 'main'}
    mock = fake_request(monkeypatch, [private, private])
    store = GithubStore('owner/operations', 'fake-secret')
    with pytest.raises(OperationsError, match='5 MiB'):
        store.save(b'x' * (MAX_BYTES + 1), None)
    assert mock.call_count == 2


def test_recovery_checks_original_attempt_status(monkeypatch):
    mock = fake_request(monkeypatch, [{'private': True, 'default_branch': 'main'}, {'status': 'in_progress'}])
    store = GithubStore('owner/operations', 'fake-secret')
    with pytest.raises(OperationsError, match='not completed'):
        store.ensure_run_finished('123:2')
    mock.assert_called_with('/actions/runs/123/attempts/2')


@pytest.mark.parametrize('error', [HTTPError('https://example.test/secret', 409, 'secret', {}, None), URLError('secret')])
def test_http_errors_do_not_expose_tokens_or_response(error):
    store = GithubStore.__new__(GithubStore)
    store.base, store.token = 'https://api.github.com/repos/owner/private', 'fake-secret'
    store.opener = Mock()
    store.opener.open.side_effect = error
    with pytest.raises(StorageError) as raised:
        store.request('/contents/.monitor/alerts.sqlite3', data={'sha': 'a' * 40})
    assert 'secret' not in str(raised.value)
    assert store.opener.open.call_count == 1
    assert store.opener.open.call_args.kwargs['timeout'] == 30


def test_redirects_never_forward_credentials():
    assert NoRedirects().redirect_request(None, None, 302, '', {}, 'https://untrusted.test') is None
