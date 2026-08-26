"""
Prompt + structured-output schema construction for the LLM extractor.

Key production decision: we do NOT ask the model to "return JSON" in free
text and then regex/json.loads the response. Free-text JSON from an LLM
breaks in production — trailing commas, markdown code fences, the model
adding a sentence before the JSON, etc. Instead we use each provider's native
structured-output mechanism (Anthropic tool use / OpenAI function calling)
with a JSON Schema built from FieldSchema, so the provider itself guarantees
schema-conformant output.
"""
from app.extraction.field_schema import FieldSpec

SYSTEM_PROMPT = (
    "You are a document data extraction engine for a freight logistics company. "
    "You will be shown an image of a logistics document (Bill of Lading, Proof "
    "of Delivery, or Freight Invoice). Extract exactly the requested fields.\n\n"
    "Rules:\n"
    "- If a field is not present or not legible on the document, set its value "
    "to null and its confidence to 0.0. Never guess or hallucinate a value.\n"
    "- confidence must reflect how certain you are the extracted value is "
    "correct, based on print/handwriting clarity, ambiguity, and whether the "
    "field label match is exact vs inferred. 1.0 = printed text, unambiguous "
    "label. Below 0.5 = illegible, smudged, handwritten, or you had to infer "
    "which field this is.\n"
    "- Dates must be normalized to YYYY-MM-DD.\n"
    "- Currency values must be plain numbers with no currency symbol or commas "
    "(e.g. '1245.50', not '$1,245.50').\n"
    "- Do not include any explanation outside of the tool call."
)


def build_extraction_tool_schema(fields: list[FieldSpec]) -> dict:
    """Builds a JSON Schema object: one property per field, each an object of
    {value, confidence}. Used as the Anthropic tool `input_schema` / OpenAI
    function `parameters`.
    """
    properties = {}
    for f in fields:
        properties[f.name] = {
            "type": "object",
            "description": f.description,
            "properties": {
                "value": {"type": ["string", "null"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["value", "confidence"],
        }
    return {
        "type": "object",
        "properties": properties,
        "required": [f.name for f in fields],
    }


def build_user_instruction(doc_type: str, fields: list[FieldSpec]) -> str:
    field_lines = "\n".join(f"- {f.name}: {f.description}" for f in fields)
    return (
        f"Document type: {doc_type.replace('_', ' ')}\n\n"
        f"Extract these fields:\n{field_lines}\n\n"
        "Call the `extract_fields` tool with your results."
    )
