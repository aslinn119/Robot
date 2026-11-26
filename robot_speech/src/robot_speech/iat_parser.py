"""AIUI IAT（自由听写）结果处理（A 模块阶段一）。

⚠️ 重要边界
-----------
本模块**尚未接入真实 IAT 数据**。下面所有行为都是依据
`A_speech/aiui_reference/EventListener.py` 里 `parse_iat()` 能看到的片段结构
推导出来的**假设**，并用**明确标注的模拟数据**测试。

真实情况仍需实机核对：
- `ls`（是否最后一段）在最终结果时的确切取值与语义；
- `ws` 是「累积到当前的全部词」还是「本次新增的词」——见 `IatAssembler(mode=...)`；
- 中间结果是否会修订（同一位置换词）、是否可能重复推送同一片段；
- **一句话的边界**：一次唤醒对应几次 VAD，事件之间如何切分。

在拿到真实样本前，不得声称 IAT 已打通。参见交接文档「四、当前最值得研究的
技术问题：IAT 自由听写」。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Union

SIMULATED_DATA_NOTICE = (
    "模拟数据：以下内容不是机器人采集的真实 IAT 样本，仅用于验证解析逻辑。"
)

_IAT_TEXT_KEY = "text"
_IAT_WORDS_KEY = "ws"
_IAT_LAST_KEY = "ls"

#: cumulative = 每个事件带「到目前为止的全部内容」（当前默认，与 parse_iat 的用法一致）
#: delta       = 每个事件只带「本次新增的片段」
_MODE_CUMULATIVE = "cumulative"
_MODE_DELTA = "delta"
_MODES = (_MODE_CUMULATIVE, _MODE_DELTA)


class IatError(ValueError):
    """IAT 数据格式或内容异常。"""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


@dataclass(frozen=True)
class IatSegment:
    """单条 IAT 事件的解析结果。"""

    text: str
    is_final: bool


@dataclass(frozen=True)
class IatUpdate:
    """组装器对外输出的更新。

    text         当前完整文本（中间结果时为「到目前为止」的文本）
    delta        相比上次新增的部分，便于上层做增量展示
    is_final     **本条是否产生了一个新的最终结果**；重复推送的最终事件为 False
    is_duplicate 本条与已有内容重复，可忽略
    revision     本条推翻了已有内容（换词），上层应整段替换
    event_index  事件序号，从 1 开始，便于日志对齐
    """

    text: str
    delta: str
    is_final: bool
    is_duplicate: bool
    revision: bool
    event_index: int


def parse_segment(payload: Union[str, bytes, bytearray, Mapping[str, Any]]) -> IatSegment:
    """解析单条 AIUI IAT 事件。

    payload 可以是 JSON 字符串、JSON 字节串或已解析的 dict。
    格式不符合预期时抛 IatError，不返回「猜测结果」。
    """
    data = _coerce_mapping(payload)

    text_block = data.get(_IAT_TEXT_KEY)
    if not isinstance(text_block, Mapping):
        raise IatError("MISSING_TEXT", f"缺少或错误的 {_IAT_TEXT_KEY!r} 字段")

    words = text_block.get(_IAT_WORDS_KEY)
    if not isinstance(words, list):
        raise IatError("MISSING_WS", f"缺少或错误的 {_IAT_WORDS_KEY!r} 字段")

    is_final = _coerce_flag(text_block.get(_IAT_LAST_KEY))
    assembled = _join_words(words)
    return IatSegment(text=assembled, is_final=is_final)


def _coerce_mapping(
    payload: Union[str, bytes, bytearray, Mapping[str, Any]]
) -> Mapping[str, Any]:
    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IatError("DECODE_ERROR", str(exc)) from exc

    if isinstance(payload, str):
        if not payload.strip():
            raise IatError("EMPTY_PAYLOAD", "空字符串")
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise IatError("JSON_ERROR", str(exc)) from exc

    if not isinstance(payload, Mapping):
        raise IatError("FORMAT_ERROR", f"不支持的类型 {type(payload).__name__}")
    return payload


def _coerce_flag(value: Any) -> bool:
    """ls 字段容错：接受 bool / 0 / 1 / "true" / "false"；缺省视为中间结果。"""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes"):
            return True
        if lowered in ("false", "0", "no", ""):
            return False
    raise IatError("BAD_FLAG", f"{_IAT_LAST_KEY!r} 取值无法识别: {value!r}")


def _join_words(words: List[Any]) -> str:
    """把 ws 列表拼成文本。

    与参考实现 `parse_iat()` 保持一致：**只取 `cw[0]["w"]`**。
    `cw` 是同一位置的多个候选（n-best），不是同一个词的续写，
    把它们首尾拼接会造出参考实现里根本不存在的文本。
    """
    pieces: List[str] = []
    for index, item in enumerate(words):
        if not isinstance(item, Mapping):
            raise IatError("BAD_WORD_ITEM", f"ws[{index}] 不是对象")
        candidates = item.get("cw")
        if not isinstance(candidates, list) or not candidates:
            raise IatError("BAD_WORD_ITEM", f"ws[{index}] 缺少 cw 列表")
        best = candidates[0]
        if not isinstance(best, Mapping):
            raise IatError("BAD_WORD_ITEM", f"ws[{index}].cw 不是对象")
        word = best.get("w")
        if word is None:
            continue
        if not isinstance(word, str):
            raise IatError("BAD_WORD", f"ws[{index}].cw 的 w 不是字符串")
        pieces.append(word)
    return "".join(pieces)


class IatAssembler:
    """把多次 IAT 事件拼成一句完整的话。

    两条**待实机验证的假设**，用构造参数显式选择，不靠猜：

    ``mode="cumulative"``（默认）
        每个事件带「到目前为止的全部内容」。规则：
        1. 新文本以已有文本开头 → 累积更新，只取新增部分作为 delta；
        2. 新文本与已有文本相同、是已有文本的前缀或后缀 → 迟到的重复片段，
           标记 duplicate 并保留已有文本；
        3. 其余情况 → 视为修订，整段替换并标记 revision。

        规则 2 的「前缀」判定是保守选择：迟到的短片段若被当成修订会**截断**
        已识别文本（「大于五吗」变成「大于」），比丢弃一次合法缩短更危险。

    ``mode="delta"``
        每个事件只带本次新增的片段。直接用 ``+=`` 追加；与上一片段完全相同的
        事件视为重复。**若真实事件其实是累积式的，用这个模式会重复叠加文本**，
        因此真实样本到手前不要切换。

    最终结果去重
    ------------
    `is_final=True` 表示「本条产生了一个**新的**最终结果」。
    同一个最终事件被重复推送时返回 `is_final=False, is_duplicate=True`，
    避免上层把一局算成两局。去重只作用于最终结果之后**紧邻**的重复事件，
    因此玩家连着说两句完全相同的话仍然会被当作两个最终结果。
    """

    def __init__(self, mode: str = _MODE_CUMULATIVE) -> None:
        if mode not in _MODES:
            raise ValueError(f"mode 必须是 {_MODES} 之一，收到 {mode!r}")
        self._mode = mode
        self._buffer = ""
        self._final = False
        self._index = 0
        self._last_fragment = ""
        self._delivered_final: str | None = None
        self._since_final = 0
        self.auto_reset_last = False

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def text(self) -> str:
        return self._buffer

    @property
    def is_final(self) -> bool:
        return self._final

    @property
    def event_index(self) -> int:
        return self._index

    def reset(self) -> None:
        """开始新一句。"""
        self._buffer = ""
        self._final = False
        self._last_fragment = ""
        self._delivered_final = None
        self._since_final = 0
        self.auto_reset_last = False

    def push(self, payload: Union[str, bytes, bytearray, Mapping[str, Any]]) -> IatUpdate:
        segment = parse_segment(payload)
        self._index += 1
        text = segment.text

        # 紧邻上一最终结果的重复推送：不再产生新的最终结果
        if (
            self._delivered_final is not None
            and self._since_final == 0
            and text == self._delivered_final
        ):
            return self._update("", is_final=False, duplicate=True, revision=False)

        auto_reset = self._final
        if auto_reset:
            # 上一句已结束但调用方没有 reset，自动开始新一句
            self._buffer = ""
            self._final = False
            self._last_fragment = ""
        self.auto_reset_last = auto_reset

        if self._mode == _MODE_DELTA:
            update = self._push_delta(text, segment.is_final)
        else:
            update = self._push_cumulative(text, segment.is_final)

        if update.is_final:
            self._delivered_final = update.text
            self._since_final = 0
        else:
            self._since_final += 1
        return update

    # -- 两种组装模式 ------------------------------------------------------

    def _push_cumulative(self, text: str, is_final: bool) -> IatUpdate:
        previous = self._buffer
        was_final = self._final

        if not text or text == previous:
            self._final = self._final or is_final
            # 末尾补发的 ls=True 常常不带新词，但它**就是**这句话的结束。
            # 只有已经交付过 final 才不算「新的最终结果」，否则上层会永远等不到收尾。
            closing = self._closing_final(is_final, was_final)
            return self._update("", is_final=closing, duplicate=not closing, revision=False)

        if text.startswith(previous):
            self._buffer = text
            self._final = is_final
            return self._update(text[len(previous):], is_final=is_final, duplicate=False, revision=False)

        if previous.startswith(text) or previous.endswith(text):
            # 迟到的短片段：既不累积也不是修订，保留已有文本
            self._final = self._final or is_final
            closing = self._closing_final(is_final, was_final)
            return self._update("", is_final=closing, duplicate=not closing, revision=False)

        self._buffer = text
        self._final = is_final
        return self._update(text, is_final=is_final, duplicate=False, revision=True)

    def _push_delta(self, text: str, is_final: bool) -> IatUpdate:
        was_final = self._final

        if not text:
            self._final = self._final or is_final
            closing = self._closing_final(is_final, was_final)
            return self._update("", is_final=closing, duplicate=not closing, revision=False)

        if text == self._last_fragment or self._buffer.endswith(text):
            self._final = self._final or is_final
            closing = self._closing_final(is_final, was_final)
            return self._update("", is_final=closing, duplicate=not closing, revision=False)

        self._last_fragment = text
        self._buffer += text
        self._final = is_final
        return self._update(text, is_final=is_final, duplicate=False, revision=False)

    def _closing_final(self, is_final: bool, was_final: bool) -> bool:
        """这一条是否算「新产生了一个最终结果」。

        条件：本条是 final、这句话此前还没交付过 final、并且确实攒到了文本。
        没有文本的空 final 不对外交付——那是「没识别到内容」，交给上层按空输入处理。
        """
        return bool(is_final and not was_final and self._buffer)

    # -- 内部 --------------------------------------------------------------

    def _update(self, delta: str, is_final: bool, duplicate: bool, revision: bool) -> IatUpdate:
        return IatUpdate(
            text=self._buffer,
            delta=delta,
            is_final=is_final,
            is_duplicate=duplicate,
            revision=revision,
            event_index=self._index,
        )


def build_simulated_payload(words: List[str], is_final: bool, note: str = "") -> Dict[str, Any]:
    """构造**模拟** IAT 事件，结构对齐参考实现里 `parse_iat` 的用法。

    生成的数据带 `_simulated: true` 标记，防止被误当成实机样本。
    """
    return {
        "_simulated": True,
        "_note": note or SIMULATED_DATA_NOTICE,
        "text": {
            "ls": bool(is_final),
            "ws": [{"cw": [{"w": word}]} for word in words],
        },
    }


__all__ = [
    "IatAssembler",
    "IatError",
    "IatSegment",
    "IatUpdate",
    "SIMULATED_DATA_NOTICE",
    "build_simulated_payload",
    "parse_segment",
]
