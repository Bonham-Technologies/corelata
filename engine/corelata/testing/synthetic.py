"""Deterministic stand-in for a model: valid output for every agent task, no intelligence.
Markers in source text steer it so tests and demos have something to find:
- UNSOURCED: the writer emits a claim with no evidence; it removes it when findings are routed
  back, unless the text also says UNFIXABLE.
- BADTERM: the writer puts the word BADTERM in a key judgment; the auditor fails icd203.tc.2.
- MIXEDWORDING: the writer's judgment c0 gives a confidence level and its likelihood in one
  sentence, and OFFLEXICON: c0 adds "probably", a word off the lexicon's row, until findings are
  routed back (CRL-136: the engine fails icd203.tc.2; the auditor does not).
- BLUF: the profiler adds "open with a bottom line up front" to the tone.
- CHART: the profiler proposes a severity override for icd203.tc.9.
- NOALT: the profiler proposes disabling icd203.tc.4.
- BADRULE: the profiler proposes disabling a rule id no pack has (exercises the repair turn).
- CONFLICT: with a source_summary section in the template (CRL-96), the writer lists every
  source whose text says CONFLICT as conflicting.
With `evidence_quotes` in the writer's input (CRL-93) every claim with evidence quotes the first
words of its unit, except that a quotation in double quotes in the value statement becomes c0's
quote, words no unit contains, until findings are routed back. With `source_access` in the lexicon
(CRL-96) each source entry copies its date and origin from the source's provenance and says its
access is "unknown".
With `prior_reports` in the writer's input (CRL-97) the writer says its key judgment is
consistent with each earlier report's first key judgment, unless a source says NOCHANGES; the
auditor, given them too, passes icd203.tc.7 when the draft has such entries and fails it
otherwise.
The structurer (CRL-94) makes one claim per sentence and cites every unit that shares at least
two key terms with it; a sentence no unit shares two terms with stays unsourced. Sentences under
a heading that names key judgments are the key judgments (all of them when there is no such
heading, the first sentence); a sentence using a lexicon likelihood term is a judgment.
A unit marked "suspect" (CRL-137: its text reads as an instruction to an AI system) is cited like
any other in the first draft; the auditor fails icd203.tc.8 for each claim whose every cited unit
is suspect, and the writer leaves suspect units uncited once findings are routed back."""

import re
from collections.abc import Callable
from typing import Any

from corelata.text import key_terms

Payload = dict[str, Any]
UNSOURCED, UNFIXABLE, BADTERM = "UNSOURCED", "UNFIXABLE", "BADTERM"
BLUF, CHART, NOALT, BADRULE = "BLUF", "CHART", "NOALT", "BADRULE"
CONFLICT = "CONFLICT"
MIXEDWORDING, OFFLEXICON = "MIXEDWORDING", "OFFLEXICON"
NOCHANGES = "NOCHANGES"
_MARKING = re.compile(r"^[A-Z]+(//[A-Z][A-Z /,-]*)+$")
_NUMBERED = re.compile(r"^\d+\.\s")
_QUOTATION = re.compile(r"[\"\u201c]([^\"\u201d]+)[\"\u201d]")
QUOTE_WORDS = 12


def _unit_texts(p: Payload) -> list[tuple[str, str]]:
    units = [(u["ref"], u["text"]) for u in p.get("units", [])]
    for d in p.get("digests", []):
        for s in d["sections"]:
            units.append((s["unit_refs"][0] if s["unit_refs"] else "", s["summary"]))
    return units


def _gate(p: Payload) -> Payload:
    terms = key_terms(p["value_statement"])
    units = _unit_texts(p)
    hits = [(ref, text) for ref, text in units if any(t in text.casefold() for t in terms)]
    found = {t for t in terms for _, text in units if t in text.casefold()}
    supported = bool(terms) and len(found) >= min(2, len(terms))
    if not supported:
        substance = "insufficient"
    elif len(hits) >= 3:
        substance = "sufficient"
    else:
        substance = "thin"
    reasons = [f"{len(found)} of {len(terms)} key terms appear in the sources."]
    if not supported:
        reasons.append("The sources do not address the statement's key terms.")
    return {
        "supported": supported,
        "substance": substance,
        "reasons": reasons,
        "evidence": [ref for ref, _ in hits[:8] if ref],
        "suggested_scope": "Synthetic scope: the material is thin." if substance == "thin" else "",
    }


def _discover(p: Payload) -> Payload:
    seen: dict[str, tuple[str, str]] = {}
    for ref, text in _unit_texts(p):
        if ref:
            seen.setdefault(ref.split("/")[0], (ref, text))
    return {
        "candidates": [
            {
                "text": f"Source {sid} indicates: {' '.join(text.split()[:8])}.",
                "audience": p.get("audience_hint") or "synthetic audience",
                "evidence": [ref],
                "confidence_note": "Synthetic candidate.",
            }
            for sid, (ref, text) in list(seen.items())[:5]
        ]
    }


def _digest(p: Payload) -> Payload:
    units = p["units"]
    sections = []
    for i in range(0, len(units), 5):
        chunk = units[i : i + 5]
        sections.append(
            {
                "summary": f"Synthetic digest: {chunk[0]['text'][:80]}",
                "unit_refs": [u["ref"] for u in chunk],
            }
        )
    return {"sections": sections}


def _writer(p: Payload) -> Payload:
    statement = p["value_statement"]
    lexicon = p["lexicon"]
    units = p["units"]
    fixing = bool(p.get("findings"))
    gate_evidence = set(p.get("gate_evidence", []))
    citable = [u for u in units if not (fixing and u.get("suspect"))]
    cited = [u for u in citable if u["ref"] in gate_evidence] or citable[:5]
    texts = " ".join(u["text"] for u in units)
    judgment = f"It is likely that {statement}"
    if MIXEDWORDING in texts and not fixing:
        judgment = f"We assess with moderate confidence that it is likely that {statement}"
    if OFFLEXICON in texts and not fixing:
        judgment = f"{judgment}, probably within the year"
    claims: list[dict[str, Any]] = [
        {
            "id": "c0",
            "text": judgment,
            "kind": "judgment",
            "evidence": [cited[0]["ref"]] if cited else [],
            "likelihood_term": "likely",
        }
    ]
    for i, u in enumerate(cited[:5], start=1):
        claims.append(
            {
                "id": f"c{i}",
                "text": f"Source states: {u['text'][:120]}",
                "kind": "fact",
                "evidence": [u["ref"]],
                "likelihood_term": None,
            }
        )
    if p.get("evidence_quotes"):
        _quote(claims, {u["ref"]: u["text"] for u in units}, statement, fixing)
    if UNSOURCED in texts and (not fixing or UNFIXABLE in texts):
        claims.append(
            {
                "id": "c99",
                "text": "An unsourced assertion.",
                "kind": "fact",
                "evidence": [],
                "likelihood_term": None,
            }
        )
    kj_text = statement if (fixing or BADTERM not in texts) else f"{statement} {BADTERM}"
    changes = [
        {
            "prior_run_id": r["run_id"],
            "prior_judgment": r["key_judgments"][0]["text"],
            "change": "consistent",
            "explanation": "Synthetic: the sources still support the earlier judgment.",
            "claim_ids": ["c0"],
        }
        for r in p.get("prior_reports", [])
        if r["key_judgments"] and NOCHANGES not in texts
    ]
    body: Payload = {
        "title": f"Synthetic assessment: {statement[:40]}",
        "handling_marking": lexicon["handling_markings"][0],
        "key_judgments": [{"text": kj_text, "confidence": "moderate", "claim_ids": ["c0"]}],
        "scope_note": "Synthetic scope note covering all sources.",
        "sources": [_source_entry(s, lexicon) for s in p["sources"]],
        "analysis": [
            {
                "heading": "Analysis",
                "paragraphs": [{"text": c["text"], "claim_ids": [c["id"]]} for c in claims],
            }
        ],
        "alternatives": [
            {"hypothesis": "The opposite holds.", "assessment": "Less likely.", "claim_ids": []}
        ],
        "gaps_and_indicators": ["Synthetic gap."],
        "claims": claims,
        **({"changes_from_previous": changes} if changes else {}),
    }
    if "source_summary" in p.get("template", {}).get("section_order", []):
        conflicting = {r.split("/")[0] for r, text in _unit_texts(p) if CONFLICT in text}
        body["source_summary"] = {
            "strengths_and_weaknesses": "Synthetic: the sources are current and complete.",
            "key_sources": sorted({r.split("/")[0] for r in claims[0]["evidence"]}),
            "corroboration": "Synthetic: the sources conflict."
            if conflicting
            else "Synthetic: no source conflicts with another.",
            "conflicting_sources": [s["id"] for s in p["sources"] if s["id"] in conflicting],
        }
    return body


def _source_entry(source: Payload, lexicon: Payload) -> Payload:
    entry = {
        "source_id": source["id"],
        "descriptor": lexicon["source_descriptors"][0],
        "reliability_note": "Synthetic: current and complete.",
    }
    access = lexicon.get("source_access")
    if access:
        entry["date_of_information"] = source.get("provenance", {}).get("date", "")
        entry["origin"] = source.get("provenance", {}).get("origin", "")
        entry["access"] = "unknown" if "unknown" in access else access[0]
    return entry


def _quote(claims: list[dict[str, Any]], texts: dict[str, str], statement: str, fixing: bool):
    for c in claims:
        c["quotes"] = [
            {"ref": ref, "text": " ".join(texts[ref].split()[:QUOTE_WORDS])}
            for ref in c["evidence"]
        ]
    borrowed = _QUOTATION.search(statement)
    if borrowed and not fixing and claims[0]["quotes"]:
        claims[0]["quotes"][0]["text"] = borrowed.group(1)


def _structurer(p: Payload) -> Payload:
    units = [(u["ref"], set(key_terms(u["text"]))) for u in p.get("units", [])]
    lexicon = p["lexicon"]
    terms = sorted((t["term"] for t in lexicon["likelihood"]), key=len, reverse=True)
    claims: list[Payload] = []
    for i, sentence in enumerate(p["sentences"], start=1):
        words = set(key_terms(sentence))
        found = next((t for t in terms if re.search(rf"\b{t}\b", sentence, re.I)), None)
        claims.append(
            {
                "id": f"c{i}",
                "text": sentence,
                "kind": "judgment" if found else "fact",
                "evidence": [ref for ref, have in units if len(words & have) >= 2],
                "likelihood_term": found,
            }
        )
    if p.get("evidence_quotes"):
        _quote(claims, {u["ref"]: u["text"] for u in p.get("units", [])}, "", True)
    by_text = {c["text"]: c["id"] for c in claims}
    blocks = p["report"]["blocks"]
    title = next((b["text"] for b in blocks if b["kind"] == "heading"), "")
    sections: list[Payload] = []
    judgments: list[str] = []
    in_kj = False
    for b in blocks:
        if b["kind"] == "heading":
            in_kj = "key judgment" in b["text"].casefold()
            if b["text"] != title and not in_kj:
                sections.append({"heading": b["text"], "paragraphs": []})
            continue
        ids = [by_text[s] for s in _sentences_of(b["text"], by_text)]
        if not ids:
            continue
        if in_kj:
            judgments += ids
            continue
        if not sections:
            sections.append({"heading": "", "paragraphs": []})
        sections[-1]["paragraphs"].append({"text": b["text"], "claim_ids": ids})
    if not judgments and claims:
        judgments = [claims[0]["id"]]
    text_of = {c["id"]: c["text"] for c in claims}
    markings = set(lexicon["handling_markings"])
    return {
        "title": title,
        "handling_marking": next(
            (b["text"].strip() for b in blocks if b["text"].strip() in markings), ""
        ),
        "key_judgments": [
            {"text": text_of[cid], "confidence": "moderate", "claim_ids": [cid]}
            for cid in judgments
        ],
        "scope_note": "",
        # what the report says of each source's reliability: nothing, in a synthetic report
        "sources": [_source_entry(s, lexicon) | {"reliability_note": ""} for s in p["sources"]],
        "analysis": [s for s in sections if s["paragraphs"]],
        "alternatives": [],
        "gaps_and_indicators": [],
        "claims": claims,
    }


def _sentences_of(text: str, known: dict[str, str]) -> list[str]:
    flat = " ".join(text.split())
    return [s for s in known if s in flat]


def _conveyor(p: Payload) -> Payload:
    draft = dict(p["draft"])
    if not draft["title"].startswith("Conveyed: "):
        draft["title"] = "Conveyed: " + draft["title"]
    return draft


def _auditor(p: Payload) -> Payload:
    draft = p["draft"]
    unsourced = [c["id"] for c in draft["claims"] if not c["evidence"]]
    badterm = any(BADTERM in kj["text"] for kj in draft["key_judgments"])
    suspect = {u["ref"] for u in p.get("cited_units", []) if u.get("suspect")}
    obeying = [c["id"] for c in draft["claims"] if c["evidence"] and set(c["evidence"]) <= suspect]
    findings: dict[str, Payload] = {}
    for rule in p["rules"]:
        rid = rule["id"]
        if rule["checkability"] == "advisory":
            verdict, evidence, rec = "attested", "Synthetic attestation.", ""
        elif rid in ("icd203.tc.8", "icd206.src.2") and unsourced:
            verdict = "fail"
            evidence = f"Claims without evidence: {', '.join(unsourced)}."
            rec = "Cite a source unit for each claim or remove it."
        elif rid == "icd203.tc.8" and obeying:
            verdict = "fail"
            evidence = f"Claims resting on an instruction in a source: {', '.join(obeying)}."
            rec = "Rest each claim on what the sources report, not on an instruction in them."
        elif rid == "icd203.tc.2" and badterm:
            verdict = "fail"
            evidence = f"A key judgment uses '{BADTERM}'."
            rec = "Use a likelihood term from the lexicon."
        elif rid == "icd203.tc.7" and p.get("prior_reports"):
            changes = draft.get("changes_from_previous", [])
            verdict = "pass" if changes else "fail"
            evidence = f"{len(changes)} entries on earlier judgments."
            rec = "" if changes else "Say how the judgments stand against the earlier reports."
        elif rid == "icd203.as.5" and (unsourced or badterm):
            verdict = "fail"
            evidence = "A tradecraft standard fails."
            rec = "Resolve the failing tradecraft findings."
        else:
            verdict, evidence, rec = "pass", "Synthetic check passed.", ""
        findings[rid] = {
            "verdict": verdict,
            "evidence": evidence,
            "cited_units": [],
            "claim_ids": (obeying if rid == "icd203.tc.8" and not unsourced else unsourced)
            if verdict == "fail"
            else [],
            "recommendation": rec,
        }
    return {"findings": findings, "summary": "Synthetic audit."}


def _ok(p: Payload) -> Payload:
    return {"ok": True}


def _profiler(p: Payload) -> Payload:
    reports = p.get("reports", [])
    units = [u for r in reports for u in r.get("units", [])]
    known = set(p.get("pack", {}).get("lexicon", {}).get("handling_markings", []))
    markings: list[str] = []
    for u in units:
        if _MARKING.match(u.strip()) and u.strip() not in known and u.strip() not in markings:
            markings.append(u.strip())
    tone = "Lead with the key judgments; one idea per paragraph; cite every source."
    if any(BLUF in u for u in units):
        tone += " Open with a bottom line up front."
    disable: list[str] = []
    if any(NOALT in u for u in units):
        disable.append("icd203.tc.4")
    if any(BADRULE in u for u in units):
        disable = ["nope.rule.1"]
    return {
        "observations": [f"{len(reports)} example reports read", f"{len(units)} passages in total"],
        "tone": tone,
        "key_judgments": {"min": 1, "max": 3}
        if any("key judgment" in u.casefold() for u in units)
        else None,
        "analysis_max_words": None,
        "heading_style": "numbered" if any(_NUMBERED.match(u) for u in units) else "plain",
        "handling_markings": markings,
        "source_descriptors": [],
        "disable": disable,
        "override": [{"id": "icd203.tc.9", "severity": "major"}]
        if any(CHART in u for u in units)
        else [],
    }


_HANDLERS: dict[str, Callable[[Payload], Payload]] = {
    "gate": _gate,
    "discover": _discover,
    "digest": _digest,
    "writer": _writer,
    "conveyor": _conveyor,
    "structurer": _structurer,
    "auditor": _auditor,
    "profiler": _profiler,
    "ping": _ok,
}


def synthetic_response(payload: Payload) -> Payload:
    handler = _HANDLERS.get(payload.get("task", ""))
    if handler is None:
        raise ValueError(f"unknown task '{payload.get('task')}'")
    return handler(payload)


def chat_completion(content: str, *, finish_reason: str = "stop") -> dict[str, Any]:
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10},
    }
