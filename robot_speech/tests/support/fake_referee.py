"""C 裁判的**最小测试替身**。

它只实现 `docs/interface_v02.md` 里 A 模块用到的那部分语义：

- `propose` → 生成 `pending`（`pending_id` + 递增的 `version`）；
- `confirm` / `cancel` 必须带回一致的 `pending_id` + `version`，否则拒绝且状态不变；
- 同一 `game_id + request_id + 完全相同内容` 重发返回缓存响应并置 `duplicate=true`；
- 同编号不同内容 → `request_conflict`；旧局 → `stale_game`。

**这不是 C 的实现**：不做完整状态机、不做计次规则以外的判定、不做日志持久化。
计次、历史、秘密值、胜负全部由 C 维护，这里只是为了把 A 的时序验证出来。

错误码 `pending_mismatch` 是**临时占位**：v0.2 只定义了跨局的 `stale_game`，
同一局内「旧待确认项」的错误码还要和 C 对齐，测试只锁定「拒绝且状态不变」。
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Mapping, Optional

PROVISIONAL_STALE_PENDING_CODE = "pending_mismatch"

_KINDS = ("gt", "lt", "eq", "submit", "exit")
_COMPARE_KINDS = ("gt", "lt", "eq")


class FakeReferee:
    """内存版 C 裁判，仅覆盖 A 模块的调用路径。"""

    def __init__(self, *, game_id: str = "game-1", secret: int = 6, max_questions: int = 7) -> None:
        if not 1 <= secret <= 10:
            raise ValueError("secret 必须在 1~10")
        self.game_id = game_id
        self._secret = secret
        self._max_questions = max_questions
        self._reset_game()
        self._cache: Dict[Any, Any] = {}

    # -- 对外接口 ----------------------------------------------------------

    def public_state(self) -> Dict[str, Any]:
        phase = "finished" if self._finished else (
            "awaiting_confirm" if self._pending else "awaiting_question"
        )
        state: Dict[str, Any] = {
            "game_id": self.game_id,
            "phase": phase,
            "remaining": self._remaining,
            "history": copy.deepcopy(self._history),
            "pending": copy.deepcopy(self._pending),
            "finished": self._finished,
            "result": copy.deepcopy(self._result),
        }
        if self._revealed is not None:
            state["revealed_number"] = self._revealed
        return state

    def handle(self, event: Mapping[str, Any]) -> Dict[str, Any]:
        request_id = event.get("request_id")
        game_id = event.get("game_id")

        if game_id != self.game_id:
            return self._response(request_id, ok=False, code="stale_game", message="旧局消息")

        key = (game_id, request_id)
        fingerprint = json.dumps(event, sort_keys=True, ensure_ascii=False, default=str)
        cached = self._cache.get(key)
        if cached is not None:
            cached_fingerprint, cached_response = cached
            if cached_fingerprint == fingerprint:
                response = copy.deepcopy(cached_response)
                response["duplicate"] = True
                return response
            return self._response(
                request_id, ok=False, code="request_conflict", message="同编号不同内容"
            )

        response = self._dispatch(event)
        # 业务拒绝也缓存；格式错误在 _dispatch 里就返回，同样按 v0.2 处理
        self._cache[key] = (fingerprint, copy.deepcopy(response))
        return response

    # -- 状态 --------------------------------------------------------------

    @property
    def secret(self) -> int:
        return self._secret

    # -- 内部 --------------------------------------------------------------

    def _reset_game(self) -> None:
        self._remaining = self._max_questions
        self._history: List[Dict[str, Any]] = []
        self._pending: Optional[Dict[str, Any]] = None
        self._finished = False
        self._result: Optional[str] = None
        self._revealed: Optional[int] = None
        self._version = 0

    def _response(
        self, request_id: Any, *, ok: bool, code: str, message: str = ""
    ) -> Dict[str, Any]:
        return {
            "request_id": request_id,
            "ok": ok,
            "code": code,
            "message": message,
            "duplicate": False,
            "state": self.public_state(),
        }

    def _dispatch(self, event: Mapping[str, Any]) -> Dict[str, Any]:
        request_id = event.get("request_id")
        event_type = event.get("event_type")
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            return self._response(request_id, ok=False, code="bad_payload", message="payload 必须是对象")

        if event_type == "propose":
            return self._propose(request_id, payload)
        if event_type in ("confirm", "cancel"):
            return self._resolve(request_id, payload, cancel=(event_type == "cancel"))
        if event_type == "new_game":
            return self._new_game(request_id)
        return self._response(request_id, ok=False, code="unknown_event", message=str(event_type))

    def _propose(self, request_id: Any, payload: Mapping[str, Any]) -> Dict[str, Any]:
        if set(payload) != {"kind", "number"}:
            return self._response(request_id, ok=False, code="bad_payload", message="payload 恰为 kind、number")

        kind = payload["kind"]
        number = payload["number"]
        if kind not in _KINDS:
            return self._response(request_id, ok=False, code="bad_payload", message=f"未知 kind {kind!r}")
        if kind == "exit":
            if number is not None:
                return self._response(request_id, ok=False, code="bad_payload", message="exit 的 number 必须为 null")
        else:
            if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= 10:
                return self._response(request_id, ok=False, code="bad_payload", message="number 必须是 1~10 的整数")

        if self._finished:
            return self._response(request_id, ok=False, code="game_finished", message="本局已结束")
        if kind in _COMPARE_KINDS and self._remaining <= 0:
            return self._response(request_id, ok=False, code="no_questions_left", message="七问已用尽")

        self._version += 1
        self._pending = {
            "pending_id": f"p{self._version}",
            "version": self._version,
            "kind": kind,
            "number": number,
        }
        return self._response(request_id, ok=True, code="ok")

    def _resolve(
        self, request_id: Any, payload: Mapping[str, Any], *, cancel: bool
    ) -> Dict[str, Any]:
        if set(payload) != {"pending_id", "version"}:
            return self._response(
                request_id, ok=False, code="bad_payload", message="payload 恰为 pending_id、version"
            )
        if self._pending is None:
            return self._response(request_id, ok=False, code="nothing_pending", message="没有待确认内容")

        if (
            payload["pending_id"] != self._pending["pending_id"]
            or payload["version"] != self._pending["version"]
        ):
            return self._response(
                request_id,
                ok=False,
                code=PROVISIONAL_STALE_PENDING_CODE,
                message="待确认内容已变化",
            )

        pending = self._pending
        self._pending = None

        if cancel:
            return self._response(request_id, ok=True, code="cancelled")

        kind = pending["kind"]
        number = pending["number"]

        if kind in _COMPARE_KINDS:
            self._history.append(
                {"kind": kind, "number": number, "answer": self._compare(kind, number)}
            )
            self._remaining -= 1
            return self._response(request_id, ok=True, code="ok")

        if kind == "submit":
            self._finished = True
            self._revealed = self._secret
            self._result = "win" if number == self._secret else "lose"
            return self._response(request_id, ok=True, code="ok")

        # exit
        self._finished = True
        self._result = "exit"
        return self._response(request_id, ok=True, code="ok")

    def _new_game(self, request_id: Any) -> Dict[str, Any]:
        if not self._finished:
            return self._response(request_id, ok=False, code="game_in_progress", message="本局尚未结束")
        self._reset_game()
        return self._response(request_id, ok=True, code="ok")

    def _compare(self, kind: str, number: int) -> bool:
        if kind == "gt":
            return self._secret > number
        if kind == "lt":
            return self._secret < number
        return self._secret == number
