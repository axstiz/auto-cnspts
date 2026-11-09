import time
import uuid
from dataclasses import dataclass, field

import httpx

DEFAULT_BASE_URL = "https://opencode.ai/inference/go/openai/v1"
DEFAULT_MODEL = "glm-5.3-flash"
USER_AGENT = "auto-cnpscts/0.1"


class GoError(RuntimeError):
    pass


@dataclass
class ChatResult:
    text: str
    usage: dict = field(default_factory=dict)


def text_part(text: str) -> dict:
    return {"type": "text", "text": text}


def image_part(png_b64: str) -> dict:
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png_b64}"}}


class GoClient:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 300.0,
        session_id: str | None = None,
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._session_id = session_id or uuid.uuid4().hex
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "requests": 0}
        self._http = httpx.Client(
            timeout=timeout,
            headers=self._static_headers(),
        )

    def _static_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": USER_AGENT,
            "x-opencode-session": self._session_id,
        }

    def chat(self, content_parts: list[dict], system: str | None = None) -> ChatResult:
        messages = []
        if system is not None:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content_parts})

        body = {"model": self.model, "messages": messages}

        attempts = self._max_retries + 1
        last_err: str | None = None
        for attempt in range(attempts):
            response = self._http.post(f"{self.base_url}/chat/completions", json=body)
            if response.status_code == 200:
                data = response.json()
                self._account_usage(data.get("usage", {}))
                return ChatResult(text=data["choices"][0]["message"]["content"], usage=data.get("usage", {}))
            detail = self._error_detail(response)
            retryable = response.status_code == 429 or 500 <= response.status_code <= 599
            if not retryable:
                raise GoError(f"HTTP {response.status_code}: {detail}")
            last_err = f"HTTP {response.status_code}: {detail}"
            if attempt + 1 < attempts:
                time.sleep(self._retry_delay)
        raise GoError(last_err or "request failed")

    def _account_usage(self, usage: dict) -> None:
        self.usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
        self.usage["completion_tokens"] += usage.get("completion_tokens", 0)
        self.usage["requests"] += 1

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            data = response.json()
            return data.get("error", {}).get("message", "") or str(data)[:200]
        except Exception:
            return response.text[:200]

    def close(self) -> None:
        self._http.close()
