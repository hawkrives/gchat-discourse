import pytest


def test_make_request_includes_api_headers(monkeypatch):
    """Ensure DiscourseClient sends Api-Key and Api-Username headers and builds URL correctly."""

    recorded = {}

    def fake_request(method, url, headers=None, json=None, params=None, timeout=None):
        # record the call
        recorded['method'] = method
        recorded['url'] = url
        recorded['headers'] = headers
        recorded['json'] = json
        recorded['params'] = params
        recorded['timeout'] = timeout

        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"categories": []}

        return FakeResponse()

    # Patch the requests.request used in the module
    monkeypatch.setattr(
        'gchat_discourse.discourse_client.requests.request', fake_request
    )

    from gchat_discourse.discourse_client import DiscourseClient

    # Test with a base URL that includes a trailing slash
    client = DiscourseClient('http://example.com/', 'APIKEY123', 'apiuser')
    result = client._make_request('GET', '/categories.json')

    assert result == {"categories": []}
    assert recorded['method'] == 'GET'
    # trailing slash on base url should not produce double-slash in final URL
    assert recorded['url'] == 'http://example.com/categories.json'
    assert recorded['headers']['Api-Key'] == 'APIKEY123'
    assert recorded['headers']['Api-Username'] == 'apiuser'
    assert recorded['headers']['Content-Type'] == 'application/json'


def test_make_request_handles_base_url_without_trailing_slash(monkeypatch):
    recorded = {}

    def fake_request(method, url, headers=None, json=None, params=None, timeout=None):
        recorded['url'] = url

        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"ok": True}

        return FakeResponse()

    monkeypatch.setattr(
        'gchat_discourse.discourse_client.requests.request', fake_request
    )

    from gchat_discourse.discourse_client import DiscourseClient

    client = DiscourseClient('http://example.com', 'K', 'u')
    _ = client._make_request('GET', 'categories.json')
    assert recorded['url'] == 'http://example.com/categories.json'
