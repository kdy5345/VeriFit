import json

from app.schemas.agent import AnalyzedUserInput, AnswerReview, DraftAnswer
from app.services.online_agent_llm import (
    GeminiOnlineAgent,
    _ANALYZER_EXAMPLES,
    _REVIEWER_EXAMPLES,
    _WRITER_EXAMPLES,
)


class _FakeResponse:
    def __init__(self, output: dict):
        self._output = output

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "candidates": [
                {"content": {"parts": [{"text": json.dumps(self._output, ensure_ascii=False)}]}}
            ]
        }


class _RecordingClient:
    def __init__(self, output: dict):
        self.output = output
        self.payload = None

    def post(self, url, headers, json):
        self.payload = json
        return _FakeResponse(self.output)


def test_few_shot_outputs_match_response_schemas() -> None:
    for _, output in _ANALYZER_EXAMPLES:
        AnalyzedUserInput.model_validate(output)
    for _, output in _WRITER_EXAMPLES:
        DraftAnswer.model_validate(output)
    for _, output in _REVIEWER_EXAMPLES:
        AnswerReview.model_validate(output)


def test_analyzer_sends_examples_as_turns_before_actual_input() -> None:
    output = _ANALYZER_EXAMPLES[0][1]
    client = _RecordingClient(output)
    agent = GeminiOnlineAgent("test-key", "test-model", client=client)

    actual_message = "매달 40만 원씩 2년 넣을래."
    agent.analyze(actual_message)

    contents = client.payload["contents"]
    assert len(contents) == len(_ANALYZER_EXAMPLES) * 2 + 1
    assert [turn["role"] for turn in contents[:-1]] == ["user", "model"] * len(
        _ANALYZER_EXAMPLES
    )
    assert contents[-1]["role"] == "user"
    assert json.loads(contents[-1]["parts"][0]["text"]) == {"message": actual_message}
    assert client.payload["generationConfig"]["temperature"] == 0.0
