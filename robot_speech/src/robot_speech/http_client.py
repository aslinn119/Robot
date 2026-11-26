"""TEAM_INTERFACE v1.0 的 HTTP 传输层。

只负责「把请求发出去、把 JSON 收回来、按规则重试」，不含业务判断。

规范要点（§2.2 / §13.1）：
- 头：`Content-Type` / `Authorization: Bearer <令牌>` / `X-Roban-Instance: <32位hex>`
- 连接 2 秒、读取 5 秒；长轮询最多等 1 秒
- POST 网络重试最多共 3 次，间隔 300ms / 900ms，**沿用原 request_id 与内容**
- 只对连接失败、超时、502/503/429 重试；400/401/403/404/409/413 不自动重发
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from .team_protocol import (
    API_PREFIX,
    PROTOCOL_VERSION,
    ProtocolError,
    is_valid_id,
    new_id,
    validate_command,
)

DEFAULT_CONNECT_TIMEOUT = 2.0
DEFAULT_READ_TIMEOUT = 5.0
DEFAULT_LONG_POLL_MS = 1000
RETRY_BACKOFF = (0.3, 0.9)
RETRY_STATUS = frozenset({429, 502, 503})


class RefereeHttpError(RuntimeError):
    """C 返回了错误，或网络失败且重试用尽。"""

    def __init__(self, status: int, code: str, message: str = "", data: Any = None):
        self.status = status
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"HTTP {status} {code}: {message}" if message else f"HTTP {status} {code}")


class HttpRefereeClient:
    """A/B/D 通用的客户端。A 用它拉命令、发事件。"""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        source: str = "A",
        instance_id: Optional[str] = None,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        max_attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        # HTTP 头只能放 ASCII；令牌里混进中文会炸在 urllib 最深处，报 UnicodeEncodeError，
        # 完全看不出是令牌的问题。这里提前挡住，给一句人话。
        if not _is_ascii(token):
            raise ProtocolError(
                "BAD_TOKEN",
                "令牌必须只含 ASCII 字符（是不是把说明文字或占位符当令牌填了？）",
            )
        self._token = token.strip()
        if not self._token:
            raise ProtocolError("BAD_TOKEN", "令牌为空")
        self._source = source
        self._instance_id = instance_id or new_id()
        if not is_valid_id(self._instance_id):
            raise ProtocolError("BAD_INSTANCE_ID", self._instance_id)
        self._read_timeout = read_timeout
        self._max_attempts = max(1, max_attempts)
        self._sleep = sleep

    # -- 只读 --------------------------------------------------------------

    @property
    def source(self) -> str:
        return self._source

    @property
    def instance_id(self) -> str:
        return self._instance_id

    @property
    def base_url(self) -> str:
        return self._base_url

    # -- 接口 --------------------------------------------------------------

    def health(self) -> Dict[str, Any]:
        return self._request("GET", f"{API_PREFIX}/health")

    def public_state(self) -> Dict[str, Any]:
        return self._request("GET", f"{API_PREFIX}/state/public")

    def pull_command(
        self,
        *,
        module: Optional[str] = None,
        lane: str = "main",
        wait_ms: int = DEFAULT_LONG_POLL_MS,
    ) -> Optional[Dict[str, Any]]:
        """领一条命令。`data.command` 为 null 表示暂无任务，**不是失败**。"""
        module = module or self._source
        wait_ms = max(0, min(int(wait_ms), DEFAULT_LONG_POLL_MS))
        payload = self._request(
            "GET",
            f"{API_PREFIX}/modules/{module}/commands/next",
            params={"lane": lane, "wait_ms": str(wait_ms)},
            # 长轮询可能正好等到 wait_ms，读取超时要留余量
            read_timeout=self._read_timeout + wait_ms / 1000.0,
        )
        command = (payload.get("data") or {}).get("command")
        if command is None:
            return None
        return validate_command(command)

    def command_status(self, command_id: str) -> Dict[str, Any]:
        """查命令状态：是否取消、是否过期、剩余时间。"""
        payload = self._request("GET", f"{API_PREFIX}/commands/{command_id}")
        return (payload.get("data") or {}).get("command") or {}

    def post_event(self, event: Mapping[str, Any]) -> Dict[str, Any]:
        """POST /events。**必须原样重发同一个事件**（request_id 与内容都不变）。"""
        return self._request("POST", f"{API_PREFIX}/events", body=dict(event))

    # -- 网络 --------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {self._token}",
            "X-Roban-Instance": self._instance_id,
            "Accept": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Optional[Mapping[str, Any]] = None,
        params: Optional[Mapping[str, str]] = None,
        read_timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        url = self._base_url + path
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        data = None
        if body is not None:
            data = json.dumps(dict(body), ensure_ascii=False).encode("utf-8")

        timeout = read_timeout or self._read_timeout
        last_error: Optional[BaseException] = None

        for attempt in range(1, self._max_attempts + 1):
            status, payload, headers = self._raw(method, url, data, timeout)
            if 200 <= status < 300:
                return payload

            code = str(payload.get("code") or f"HTTP_{status}")
            message = str(payload.get("message") or "")

            if status not in RETRY_STATUS or attempt == self._max_attempts:
                raise RefereeHttpError(status, code, message, payload.get("data"))

            if status == 429:
                # 规范：遵守 Retry-After 响应头，没有该头时等一秒
                delay = _retry_after_header(headers) or 1.0
            else:
                delay = RETRY_BACKOFF[min(attempt - 1, len(RETRY_BACKOFF) - 1)]
            self._sleep(delay)

        raise RefereeHttpError(0, "NETWORK_ERROR", "重试用尽")

    def _raw(
        self, method: str, url: str, data: Optional[bytes], timeout: float
    ) -> Tuple[int, Dict[str, Any], Dict[str, str]]:
        request = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, self._decode(response.read()), dict(response.headers)
        except urllib.error.HTTPError as exc:
            headers = dict(exc.headers) if exc.headers else {}
            return exc.code, self._decode(exc.read()), headers
        except (urllib.error.URLError, socket.timeout, ConnectionError, TimeoutError) as exc:
            # 视为可重试的网络失败
            return 503, {"code": "NETWORK_ERROR", "message": str(exc)}, {}

    @staticmethod
    def _decode(raw: bytes) -> Dict[str, Any]:
        if not raw:
            return {}
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {"code": "BAD_JSON", "message": "响应不是合法 JSON"}
        return parsed if isinstance(parsed, dict) else {"data": parsed}

    @staticmethod
    def _retry_after(payload: Mapping[str, Any]) -> Optional[float]:
        value = payload.get("retry_after")
        if isinstance(value, (int, float)):
            return float(value)
        return None


def _is_ascii(value: str) -> bool:
    return isinstance(value, str) and all(ord(ch) < 128 for ch in value)


def _retry_after_header(headers: Mapping[str, str]) -> Optional[float]:
    """读 429 的 `Retry-After`（秒数形式）。"""
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if raw is None:
        return None
    try:
        return max(0.0, float(str(raw).strip()))
    except ValueError:
        return None


def make_config(base_url: str, token: str, *, source: str = "A") -> HttpRefereeClient:
    """按共享配置构造客户端（`config/interface.local.json` 的 base_url 与令牌）。"""
    return HttpRefereeClient(base_url, token, source=source)


__all__ = [
    "DEFAULT_LONG_POLL_MS",
    "HttpRefereeClient",
    "PROTOCOL_VERSION",
    "RefereeHttpError",
    "make_config",
]
