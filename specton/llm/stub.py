"""테스트용 stub. 준비한 응답·오류를 순서대로 돌려주고, 실제 API는 호출하지 않는다.

재요청·검증은 실제 client와 같은 LLMClient 코드를 거친다.

    client, transport = stub_client(reply(A01Output(...)))
    result = client.complete(request, A01Output)
"""

from collections.abc import Iterable

from pydantic import BaseModel

from specton.llm.client import LLMClient, RawReply
from specton.llm.types import LLMRequest

type StubStep = RawReply | Exception


def reply(output: BaseModel | str, *, input_tokens: int = 10, output_tokens: int = 10) -> RawReply:
    """정상 응답. 모델 객체를 주면 JSON으로, 문자열을 주면 그대로(형식 오류 재현용) 돌려준다."""
    text = output if isinstance(output, str) else output.model_dump_json()
    return RawReply(text=text, input_tokens=input_tokens, output_tokens=output_tokens)


def refusal(message: str = "요청을 처리할 수 없습니다") -> RawReply:
    """모델 거절 응답."""
    return RawReply(text=None, refusal=message)


class StubTransport:
    def __init__(self, steps: Iterable[StubStep]) -> None:
        self._steps = iter(tuple(steps))
        self.sent: tuple[LLMRequest, ...] = ()

    def send(self, request: LLMRequest, output_model: type[BaseModel]) -> RawReply:
        self.sent = (*self.sent, request)
        step = next(self._steps, None)
        if step is None:
            raise AssertionError("StubTransport: 준비한 응답보다 많이 호출됨")
        if isinstance(step, Exception):
            raise step
        return step


def stub_client(
    *steps: StubStep, max_structured_retries: int = 2
) -> tuple[LLMClient, StubTransport]:
    """stub transport를 끼운 client와, 보낸 요청을 확인할 transport를 함께 돌려준다."""
    transport = StubTransport(steps)
    return LLMClient(transport, max_structured_retries=max_structured_retries), transport
