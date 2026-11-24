"""Source text that reads as an instruction to an AI system (CRL-137). Corelata's sources are
often written by the people a report is about, and a planted line can try to steer a model that
reads it ("ignore previous instructions and …"). Ingest marks such a unit `meta.suspect: true`;
the unit still reaches the models, carrying `"suspect": true` in their input, and every prompt
that reads source text says it is data, never instructions. The heuristic is deliberately
simple and documented (operator guide, "Instructions in sources"): a flag asks a reader to look,
it is not a verdict, and a source about prompt injection will be flagged as well.

Text a reader of the document never sees (HTML `hidden`, inline `display:none` or
`visibility:hidden`, `aria-hidden="true"`; DOCX `w:vanish`) is not flagged here: ingest keeps it
as units marked `meta.hidden: true`, which the trace shows and no model receives
(`units.model_view`)."""

import re
from typing import Any

# Who an injected line addresses: an AI system by any of its usual names.
_AI = (
    r"(?:ai|a\.i\.|llms?|large language models?|language models?|chat ?bots?|chatgpt|gpt|"
    r"(?:ai |virtual )?assistants?|ai (?:systems?|models?|agents?|tools?))"
)

# Each pattern is one form a planted instruction takes; a unit matching any of them is suspect.
INSTRUCTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE | re.MULTILINE)
    for p in (
        # "ignore previous instructions", "disregard all prior prompts", "forget your instructions"
        r"\b(?:ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}?"
        r"\b(?:instructions?|prompts?|directives?)\b",
        # the model's own configuration named
        r"\b(?:system|developer) (?:prompt|message|instructions?)\b",
        # "note to the AI:", "instructions for any language model reading this"
        rf"\b(?:note|message|instructions?|directive)s?\s+(?:to|for)\s+"
        rf"(?:the\s+|any\s+|all\s+|every\s+)?{_AI}"
        r"(?:\s*[:,]|\s+(?:reading|processing|summari[sz]ing|analy[sz]ing|reviewing)\b)",
        # an AI addressed by name at the start of a line or sentence: "AI: write …", "Assistant,"
        rf"(?:^|[.!?]\s+)\s*(?:dear\s+|hey\s+)?{_AI}\s*[,:]",
        # "if you are an AI", "you are now an assistant", "as an AI language model, you must"
        rf"\b(?:if\s+)?you\s+are\s+(?:now\s+)?(?:an?\s+)?(?:[a-z-]+\s+){{0,2}}{_AI}\b",
        rf"\bas\s+an?\s+{_AI}\b[^.\n]{{0,40}}\byou\s+(?:must|should|will)\b",
        # "new instructions:", "updated instructions:"
        r"\b(?:new|updated|revised|real|actual)\s+instructions?\s*:",
        # "do not tell the analyst", "don't mention this to the user"
        r"\b(?:do not|don't|never)\s+(?:tell|inform|mention|reveal|show)\b[^.\n]{0,30}?"
        r"\b(?:the\s+)?(?:user|analyst|reader|human|reviewer)s?\b",
        # chat-template tokens that have no business in a document
        r"<\|(?:im_start|im_end|system|user|assistant|endoftext)\|>|\[/?INST\]|<<SYS>>|"
        r"^\s*#{2,}\s*(?:system|instructions?)\s*:?\s*$",
    )
)


def instruction_match(text: str) -> str | None:
    """The first span of `text` that reads as an instruction to an AI system, or None."""
    for pattern in INSTRUCTION_PATTERNS:
        found = pattern.search(text)
        if found:
            return found.group(0).strip()
    return None


def suspect_meta(text: str) -> dict[str, Any]:
    """`{"suspect": True}` for a unit whose text reads as an instruction to an AI system; empty
    for any other, so a source with no such text keeps the units it had before CRL-137."""
    return {"suspect": True} if instruction_match(text) is not None else {}


def suspect_flag(meta: dict[str, Any]) -> dict[str, Any]:
    """What a model's input says of a suspect unit: `{"suspect": true}`; nothing for any other."""
    return {"suspect": True} if meta.get("suspect") else {}
