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

# Words that continue a sentence about AI rather than address one: "AI, in this case, ...",
# "Large language models, according to ...".
_CONNECTIVE = (
    r"(?:in|according|for|however|meanwhile|though|which|who|whose|that|and|or|but|as|like|by|"
    r"on|at|with|too|also|then|therefore|thus|such|including|especially|unlike|often|now|"
    r"increasingly|once|still|while|when|where|if|used|the|a|an|it|they|this|these|e\.g\.|i\.e\.)"
)

# Each pattern is one form a planted instruction takes; a unit matching any of them is suspect.
# Whitespace is bounded and never repeated next to another whitespace class, so no pattern
# backtracks on a long run of spaces or newlines (tests/ingest/test_injection.py times them).
INSTRUCTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE | re.MULTILINE)
    for p in (
        # "ignore previous instructions", "disregard all of the prior prompts", "forget your
        # instructions": the instructions are the reader's own, earlier or above; a bare
        # "commanders ignore directives" is reporting, not an instruction
        r"\b(?:ignore|disregard|forget|override|bypass) {1,3}"
        r"(?:(?:all|any|of|the|these|those) {1,3}){0,3}"
        r"(?:your|my|previous|prior|above|preceding|earlier|original|foregoing|system|initial)"
        r" {1,3}(?:\w+ {1,3})?(?:instructions?|prompts?|directives?)\b",
        r"\b(?:ignore|disregard|forget) {1,3}(?:all|any) {1,3}(?:(?:other|of|the|these) {1,3})?"
        r"(?:instructions?|prompts?)\b",
        # the model's own configuration named
        r"\b(?:system|developer) (?:prompt|message|instructions?)\b",
        # "note to the AI:", "instructions for any language model reading this"
        rf"\b(?:note|message|instructions?|directive)s?[ \t\n]{{1,4}}(?:to|for)[ \t\n]{{1,4}}"
        rf"(?:(?:the|any|all|every)[ \t\n]{{1,4}})?{_AI}"
        r"(?:[ \t]{0,4}[:,]|[ \t\n]{1,4}"
        r"(?:reading|processing|summari[sz]ing|analy[sz]ing|reviewing)\b)",
        # an AI addressed by name at the start of a line or sentence: "AI: write ...",
        # "Assistant, mark ..."
        rf"(?:^[ \t]{{0,4}}|[.!?][ \t\n]{{1,4}})(?:(?:dear|hey)[ \t]{{1,4}})?{_AI}"
        rf"[ \t]{{0,4}}(?::|,(?![ \t\n]{{0,4}}{_CONNECTIVE}\b))",
        # "if you are an AI", "you are now an assistant", "as an AI language model, you must"
        rf"\b(?:if[ \t\n]{{1,4}})?you[ \t\n]{{1,4}}are[ \t\n]{{1,4}}(?:now[ \t\n]{{1,4}})?"
        rf"(?:an?[ \t\n]{{1,4}})?(?:[a-z-]{{1,30}}[ \t\n]{{1,4}}){{0,2}}{_AI}\b",
        rf"\bas[ \t\n]{{1,4}}an?[ \t\n]{{1,4}}{_AI}\b[^.\n]{{0,40}}"
        r"\byou[ \t\n]{1,4}(?:must|should|will)\b",
        # "new instructions:", "updated instructions:"
        r"\b(?:new|updated|revised|real|actual)[ \t\n]{1,4}instructions?[ \t]{0,4}:",
        # "do not tell the analyst", "don't mention this to the user"
        r"\b(?:do not|don't|never)[ \t\n]{1,4}(?:tell|inform|mention|reveal|show)\b[^.\n]{0,30}?"
        r"\bthe[ \t\n]{1,4}(?:user|analyst|reader|reviewer)s?\b",
        # chat-template tokens that have no business in a document
        r"<\|(?:im_start|im_end|system|user|assistant|endoftext)\|>|\[/?INST\]|<<SYS>>|"
        r"^[ \t]{0,4}#{2,6}[ \t]{0,4}(?:system|instructions?)[ \t]{0,4}:?[ \t]{0,4}$",
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
