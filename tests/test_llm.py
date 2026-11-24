import pytest
from pydantic import BaseModel

from conftest import ScriptedTransport
from matchwise.config import Settings
from matchwise.llm import LLMClient, LLMNotConfigured, LLMOutputError, RateLimiter, client_from_settings


class Answer(BaseModel):
    n: int


def ask(transport: ScriptedTransport) -> Answer:
    return LLMClient(transport).structured(system="Count.", user="How many?", schema=Answer, purpose="test")


def test_valid_reply_on_the_first_try():
    transport = ScriptedTransport(['{"n": 3}'])
    assert ask(transport) == Answer(n=3)
    system = transport.calls[0][0]["content"]
    assert system.startswith("Count.") and '"n"' in system  # the JSON schema is in the prompt


def test_invalid_reply_is_sent_back_with_the_error_and_retried():
    transport = ScriptedTransport(['{"n": "three"}', '{"n": 3}'])
    client = LLMClient(transport)
    assert client.structured(system="Count.", user="How many?", schema=Answer, purpose="test").n == 3
    retry = transport.calls[1]
    assert retry[-2] == {"role": "assistant", "content": '{"n": "three"}'}
    assert "n: Input should be a valid integer" in retry[-1]["content"]
    assert (client.usage.calls, client.usage.invalid_replies, client.usage.input_tokens) == (2, 1, 200)


def test_gives_up_after_three_invalid_replies():
    transport = ScriptedTransport(["not json", "{}", "[1]"])
    with pytest.raises(LLMOutputError, match="no valid reply after 3 attempts"):
        ask(transport)
    assert len(transport.calls) == 3


def test_a_check_can_reject_a_valid_looking_reply():
    def at_most_five(answer: Answer) -> None:
        if answer.n > 5:
            raise ValueError("n must be at most 5")

    transport = ScriptedTransport(['{"n": 9}', '{"n": 4}'])
    result = LLMClient(transport).structured(system="Count.", user="?", schema=Answer, purpose="t", check=at_most_five)
    assert result.n == 4
    assert "n must be at most 5" in transport.calls[1][-1]["content"]


def test_code_fences_are_stripped():
    assert ask(ScriptedTransport(['```json\n{"n": 1}\n```'])).n == 1


def test_missing_key_or_model_means_not_configured():
    settings = Settings("postgresql://x", "INFO", "https://example.test/v1", None, "some-model", 10)
    with pytest.raises(LLMNotConfigured):
        client_from_settings(settings)


def test_rate_limiter_spaces_calls():
    now = [0.0]
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(30, clock=lambda: now[0], sleep=sleep)  # 30/min = one per 2 s
    limiter.wait()
    limiter.wait()
    assert slept == [2.0]
    now[0] += 5  # a quiet spell: the next call needn't wait
    limiter.wait()
    assert slept == [2.0]
