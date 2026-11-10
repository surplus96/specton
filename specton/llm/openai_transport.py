"""실제 OpenAI 호출. 구조화 출력(JSON schema)으로 요청하고, 검증·재요청은 LLMClient가 한다."""

import openai
from openai import Omit, OpenAI
from openai.lib._parsing._responses import type_to_text_format_param
from openai.types.responses import Response, ResponseInputParam, ResponseTextConfigParam
from openai.types.shared_params import Reasoning
from pydantic import BaseModel

from specton.config import Settings
from specton.llm.client import LLMClient, RawReply
from specton.llm.errors import LLMAPIError, LLMTimeoutError
from specton.llm.types import LLMRequest

# type_to_text_format_param은 SDK 내부 모듈이다. SDK 버전은 uv.lock으로 고정하고,
# SDK를 올릴 때 test_openai_transport.py로 동작을 다시 확인한다.


class OpenAITransport:
    def __init__(self, client: OpenAI) -> None:
        self._client = client

    def send(self, request: LLMRequest, output_model: type[BaseModel]) -> RawReply:
        messages: ResponseInputParam = [
            {"role": m.role, "content": m.content} for m in request.messages
        ]
        text: ResponseTextConfigParam = {"format": type_to_text_format_param(output_model)}
        reasoning: Reasoning | Omit = (
            {"effort": request.reasoning_effort} if request.reasoning_effort else openai.omit
        )
        try:
            response = self._client.responses.create(
                model=request.model,
                input=messages,
                text=text,
                max_output_tokens=request.max_output_tokens,
                reasoning=reasoning,
                store=False,
            )
        except openai.APITimeoutError as exc:
            raise LLMTimeoutError(f"{request.stage}: OpenAI 호출 타임아웃") from exc
        except openai.APIError as exc:
            raise LLMAPIError(f"{request.stage}: OpenAI {type(exc).__name__}") from exc
        usage = response.usage
        return RawReply(
            text=response.output_text or None,
            refusal=_refusal(response),
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0,
            truncated=getattr(getattr(response, "incomplete_details", None), "reason", None)
            == "max_output_tokens",
        )


def _refusal(response: Response) -> str | None:
    for item in response.output:
        if item.type != "message":
            continue
        for content in item.content:
            if content.type == "refusal":
                return content.refusal
    return None


def openai_client(settings: Settings) -> LLMClient:
    """설정값(ADR-0007)으로 실제 OpenAI client를 만든다. 키가 없으면 바로 실패한다.

    `.env.example`을 그대로 복사한 빈 값도 키 없음으로 본다. 그대로 넘기면 SDK가 자체 오류를 내
    실행이 「키 없음」이 아니라 서버 오류(INTERNAL)로 끝난다.
    """
    key = settings.openai_api_key
    if key is None or not key.get_secret_value().strip():
        raise LLMAPIError("SPECTON_OPENAI_API_KEY가 설정되지 않았다")
    sdk = OpenAI(
        api_key=key.get_secret_value(),
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_api_retries,
    )
    return LLMClient(OpenAITransport(sdk), max_structured_retries=settings.max_structured_retries)
