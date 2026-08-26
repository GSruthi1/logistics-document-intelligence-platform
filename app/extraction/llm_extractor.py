"""
Multimodal LLM extractor. Supports Anthropic (Claude) and OpenAI (GPT-4o)
behind the same `Extractor` interface — provider choice is a config value
(`LLM_PROVIDER`), not a code fork anywhere else in the app.

Both providers are called with their native structured-output mechanism
(tool use / function calling) so we never parse free-text JSON out of a
model response — see app/extraction/prompts.py for why that matters.
"""
import base64
import json
import logging

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import Settings, get_settings
from app.extraction.base import ExtractionOutput, Extractor, FieldExtractionResult
from app.extraction.field_schema import get_field_schema
from app.extraction.image_utils import prepare_image
from app.extraction.prompts import SYSTEM_PROMPT, build_extraction_tool_schema, build_user_instruction

logger = logging.getLogger(__name__)

TOOL_NAME = "extract_fields"


class LLMExtractor(Extractor):
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def extract(self, file_bytes: bytes, content_type: str, doc_type: str) -> ExtractionOutput:
        image_bytes, media_type = prepare_image(file_bytes, content_type)
        fields = get_field_schema(doc_type)
        tool_schema = build_extraction_tool_schema(fields)
        user_text = build_user_instruction(doc_type, fields)
        b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

        if self.settings.llm_provider == "anthropic":
            raw, model_used = self._call_anthropic(b64, media_type, user_text, tool_schema)
        else:
            raw, model_used = self._call_openai(b64, media_type, user_text, tool_schema)

        results = [
            FieldExtractionResult(
                field_name=f.name,
                value=(raw.get(f.name) or {}).get("value"),
                confidence=float((raw.get(f.name) or {}).get("confidence", 0.0)),
            )
            for f in fields
        ]
        return ExtractionOutput(fields=results, model_used=model_used, extraction_method="llm")

    # --- Anthropic ---
    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        retry=retry_if_exception_type(Exception),
    )
    def _call_anthropic(self, b64: str, media_type: str, user_text: str, tool_schema: dict):
        import anthropic

        client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        model = self.settings.llm_model_anthropic
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=[
                {
                    "name": TOOL_NAME,
                    "description": "Record the extracted document fields.",
                    "input_schema": tool_schema,
                }
            ],
            tool_choice={"type": "tool", "name": TOOL_NAME},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": media_type, "data": b64},
                        },
                        {"type": "text", "text": user_text},
                    ],
                }
            ],
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == TOOL_NAME:
                return block.input, model
        raise RuntimeError("Anthropic response did not include the expected tool_use block")

    # --- OpenAI ---
    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        retry=retry_if_exception_type(Exception),
    )
    def _call_openai(self, b64: str, media_type: str, user_text: str, tool_schema: dict):
        from openai import OpenAI

        client = OpenAI(api_key=self.settings.openai_api_key)
        model = self.settings.llm_model_openai
        response = client.chat.completions.create(
            model=model,
            max_tokens=2048,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64}"}},
                    ],
                },
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": TOOL_NAME,
                        "description": "Record the extracted document fields.",
                        "parameters": tool_schema,
                    },
                }
            ],
            tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
        )
        call = response.choices[0].message.tool_calls[0]
        return json.loads(call.function.arguments), model
