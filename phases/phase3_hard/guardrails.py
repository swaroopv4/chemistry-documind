from __future__ import annotations

import os
import re


class GuardrailError(ValueError):
    def __init__(self, reason: str, code: str = "blocked"):
        self.reason, self.code = reason, code
        super().__init__(reason)


def enabled() -> bool:
    return os.getenv("GUARDRAILS_ENABLED", "true").lower() in {"true", "1", "yes"}


INJECTION = re.compile(
    r"\b(?:ignore|disregard|discard)\s+(?:all\s+)?(?:previous|prior|system)\s+instructions\b"
    r"|\bforget\s+(?:all\s+)?(?:previous\s+instructions|everything)\b"
    r"|\bact\s+as\s+(?:an?\s+)?unrestricted\s+(?:ai|assistant)\b"
    r"|\bdeveloper\s+mode\s+(?:enabled|activated)\b", re.I)
OFF_TOPIC = re.compile(r"^\s*(?:please\s+)?(?:tell\s+me\s+a\s+joke|write\s+(?:me\s+)?a\s+poem|what(?:'s|\s+is)\s+the\s+weather\s+today)[.!?\s]*$", re.I)
PATTERNS = {
    "EMAIL": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    "PAN": re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"),
    "PERSON": re.compile(r"(?im)\b((?:student|patient|employee|person|author|researcher)\s*(?:name)?\s*[:=]\s*)[^\r\n;]+"),
    "ADDRESS": re.compile(r"(?im)\b(?:home|residential|mailing|street)\s+address\s*[:=]\s*[^\r\n;]+"),
    "IDENTIFIER": re.compile(r"(?im)\b(?:student\s+id|employee\s+id|ssn|social\s+security\s+number|passport\s+(?:number|no))\s*[:=]\s*[^\r\n;]+"),
    "DOB": re.compile(r"(?im)\b(?:date\s+of\s+birth|dob)\s*[:=]\s*[^\r\n;]+"),
    # Explicit label avoids mistaking crystallographic numbers for phones.
    "PHONE": re.compile(r"(?i)(\b(?:phone|mobile|tel(?:ephone)?)\s*[:=]\s*)(\+?[\d ()-]{8,22}\d)"),
}
CARD = re.compile(r"(?<![\w.])(?:\d[ -]?){12,18}\d(?![\w.])")
SECRETS = re.compile(r"\b(?:gsk_[A-Za-z0-9]{20,}|pcsk_[A-Za-z0-9_-]{20,})\b")


def _luhn(value: str) -> bool:
    digits = [int(x) for x in value if x.isdigit()]
    if len(digits) not in range(13, 20) or len(set(digits)) < 2:
        return False
    total = sum((d * 2 - 9 if d * 2 > 9 else d * 2) if i % 2 else d
                for i, d in enumerate(reversed(digits)))
    return total % 10 == 0


def redact_pii(text: str) -> tuple[str, list[str]]:
    found = []
    text, count = SECRETS.subn("[REDACTED_API_KEY]", text)
    if count:
        found.append("API_KEY")
    for name, pattern in PATTERNS.items():
        replacement = (lambda m: m.group(1) + "[REDACTED_PHONE]") if name == "PHONE" else f"[REDACTED_{name}]"
        text, count = pattern.subn(replacement, text)
        if count:
            found.append(name)
    def replace_card(match):
        if _luhn(match.group()):
            if "CARD" not in found:
                found.append("CARD")
            return "[REDACTED_CARD]"
        return match.group()
    return CARD.sub(replace_card, text), found


def check_input(question: str) -> str:
    question = question.strip()
    if not question:
        raise GuardrailError("Enter a question.", "empty_input")
    if INJECTION.search(question):
        raise GuardrailError("This question contains a request to override the assistant's instructions.", "prompt_injection")
    if OFF_TOPIC.fullmatch(question):
        raise GuardrailError("Please ask a question related to chemistry or the shared chemistry documents.", "off_topic")
    return redact_pii(question)[0]


def check_output(answer: str, retrieved_chunks: list[dict]) -> str:
    answer = redact_pii(answer.strip())[0]
    if not answer:
        raise GuardrailError("The model returned an empty answer. Try again.", "empty_output")
    refusal = answer in {"I couldn't find a clear answer in the uploaded documents.",
                        "I couldn't find relevant evidence in the uploaded documents.",
                        "I could not find relevant passages."}
    if retrieved_chunks and not refusal:
        # Validate every citation location. This proves source membership, not
        # scientific entailment; the benchmark/manual evidence review remains.
        # Models may use nonbreaking spaces in a locator (e.g. "page\u202f7").
        # Accept equivalent whitespace while preserving every document/locator
        # token and the paragraph boundaries used below. Chemical Unicode in
        # the answer must remain untouched.
        valid = [re.compile(r'\((?i:Source):\s*'+re.escape(s.get('doc_name',''))+r'\s*,\s*'+
                 r'\s+'.join(re.escape(token) for token in re.split(r'\s+',
                    s.get('locator','page '+str(s.get('page_num',0))).strip()))+r'\s*\)')
                 for s in retrieved_chunks if s.get('doc_name')]
        starts = list(re.finditer(r'\(Source:',answer,re.I))
        if not starts or any(not any(pattern.match(answer,start.start()) for pattern in valid) for start in starts):
            raise GuardrailError('I could not verify the answer citations against the retrieved documents. Please ask a more specific question.','citation_blocked')
        for paragraph in re.split(r'\n\s*\n',answer):
            heading = paragraph.strip().lstrip('#* ').rstrip(':').strip()
            if heading.lower() in {'answer','summary','evidence','sources','comparison'}:
                continue
            if paragraph.strip() and not any(pattern.search(paragraph) for pattern in valid):
                raise GuardrailError('I could not verify a citation for every answer paragraph. Please ask a more specific question.','citation_blocked')
    return answer
