import base64
import json

import httpx
import pytest

from auto_cnpscts.client import GoClient, GoError, image_part, text_part


def make_client(handler, **kwargs):
    transport = httpx.MockTransport(handler)
    client = GoClient(api_key="key-123", session_id="sess-abc", **kwargs)
    client._http = httpx.Client(
        transport=transport,
        timeout=client._timeout,
        headers=client._static_headers(),
    )
    return client


def png_b64():
    return base64.b64encode(b"\x89PNGfake").decode()


def resp_ok(content, usage=None):
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}], "usage": usage or {}},
        request=httpx.Request("POST", "https://x"),
    )


def test_chat_sends_request_format():
    seen = {}

    def handler(request):
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return resp_ok("hello")

    c = make_client(handler)
    result = c.chat([text_part("hi")], system="sys prompt")

    assert result.text == "hello"
    assert seen["body"]["model"] == "glm-5.3-flash"
    msgs = seen["body"]["messages"]
    assert msgs[0] == {"role": "system", "content": "sys prompt"}
    assert msgs[1]["role"] == "user"
    assert msgs[1]["content"][0] == {"type": "text", "text": "hi"}


def test_auth_and_agent_headers():
    seen = {}

    def handler(request):
        seen["headers"] = dict(request.headers)
        return resp_ok("ok")

    c = make_client(handler)
    c.chat([text_part("q")])

    assert seen["headers"]["authorization"] == "Bearer key-123"
    assert seen["headers"]["x-opencode-session"] == "sess-abc"
    assert seen["headers"]["user-agent"].startswith("auto-cnpscts/")


def test_image_part_format():
    part = image_part(png_b64())
    assert part["type"] == "image_url"
    assert part["image_url"]["url"] == "data:image/png;base64," + png_b64()


def test_retry_on_server_error_then_success():
    counter = {"n": 0}

    def handler(request):
        counter["n"] += 1
        if counter["n"] < 3:
            return httpx.Response(500, request=httpx.Request("POST", "https://x"))
        return resp_ok("done")

    c = make_client(handler, max_retries=3, retry_delay=0.0)
    result = c.chat([text_part("q")])
    assert result.text == "done"
    assert counter["n"] == 3


def test_gives_up_after_max_retries():
    counter = {"n": 0}

    def handler(request):
        counter["n"] += 1
        return httpx.Response(503, request=httpx.Request("POST", "https://x"))

    c = make_client(handler, max_retries=2, retry_delay=0.0)
    with pytest.raises(GoError):
        c.chat([text_part("q")])
    assert counter["n"] == 3


def test_api_error_body_is_reported():
    def handler(request):
        return httpx.Response(
            400,
            json={"error": {"message": "bad request"}},
            request=httpx.Request("POST", "https://x"),
        )

    c = make_client(handler, max_retries=0)
    with pytest.raises(GoError, match="bad request"):
        c.chat([text_part("q")])


def test_usage_is_parsed():
    def handler(request):
        return resp_ok("x", usage={"prompt_tokens": 10, "completion_tokens": 5})

    c = make_client(handler)
    result = c.chat([text_part("q")])
    assert result.usage == {"prompt_tokens": 10, "completion_tokens": 5}
