#!/usr/bin/env python3
"""Gemini FREE-tier connectivity/editorial-format probe for HPI.

This sends one short prompt based only on the existing public demo article.
It NEVER posts to a site/social platform, cannot choose a paid model and does
not change any repository content. See GEMINI_FREE_TEST.md.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

MODEL = "gemini-3.5-flash-lite"
ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    + MODEL + ":generateContent"
)
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "_test_output" / "gemini_probe.json"


def public_sample():
    rows = json.loads((ROOT / "news.json").read_text(encoding="utf-8"))
    row = next((x for x in rows if x.get("id") == "google-search-ai-links"), None)
    if not row:
        raise RuntimeError("Public sample article not found in news.json")
    allowed = ("title", "summary", "event_date", "source_url")
    if not all(row.get(k) for k in allowed):
        raise RuntimeError("Incomplete public demo facts")
    return {k: row[k] for k in allowed}


def build_payload():
    prompt = (
        "Проба редакционного ИИ для «Хроник Пикирующего ИИ». "
        "Ниже уже имеющаяся публичная новость; это проверка переформулировки, "
        "а не подтверждение её достоверности. Нельзя добавлять новые факты, "
        "домыслы, несуществующие цитаты или выводы о последствиях. "
        "Напиши короткий, понятный, небанальный заголовок и лид на русском. "
        "В fact_checks_needed укажи, что перед реальной публикацией требуется "
        "сверить дату события и формулировки с первоисточником. "
        "approved_for_publication должен быть false. "
        "Исходные данные: " + json.dumps(public_sample(), ensure_ascii=False)
    )
    return {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.35,
            "maxOutputTokens": 1024,
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "headline": {"type": "STRING"},
                    "lead": {"type": "STRING"},
                    "fact_checks_needed": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "approved_for_publication": {"type": "BOOLEAN"},
                },
                "required": ["headline", "lead", "fact_checks_needed", "approved_for_publication"],
            },
        },
    }


def extract_draft(raw):
    if not isinstance(raw, dict):
        raise RuntimeError("Gemini returned non-object response")
    candidates = raw.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini returned no candidates (safety or quota limitation)")
    candidate = candidates[0]
    parts = (candidate.get("content") or {}).get("parts") or []
    message = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    if not message:
        raise RuntimeError("Gemini returned empty text")
    try:
        draft = json.loads(message)
    except (ValueError, TypeError):
        raise RuntimeError("Gemini did not return valid JSON") from None
    if not isinstance(draft, dict):
        raise RuntimeError("Gemini JSON has invalid structure")
    for field in ("headline", "lead"):
        if not isinstance(draft.get(field), str) or not draft[field].strip():
            raise RuntimeError("Gemini returned empty " + field)
    if not isinstance(draft.get("fact_checks_needed"), list):
        raise RuntimeError("Gemini returned invalid fact-check list")
    if draft.get("approved_for_publication") is not False:
        raise RuntimeError("Safety requirement not met: publication flag must be false")
    return draft


def run():
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GitHub secret GEMINI_API_KEY is absent. Create it first.")
    payload = json.dumps(build_payload(), ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": key,
            "User-Agent": "HPI-Gemini-Free-Probe/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            if response.status != 200:
                raise RuntimeError("Unexpected Gemini HTTP status " + str(response.status))
            raw = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Do not print request headers, API keys, or untrusted error body.
        hints = {
            400: "Check API-key project/model permissions",
            401: "API key is invalid",
            403: "Region, model or project access denied",
            404: "The selected model is not available",
            429: "Free quota/rate limit exhausted; no retry or paid fallback",
        }
        raise RuntimeError(
            "Gemini returned HTTP " + str(exc.code) + "; "
            + hints.get(exc.code, "Request failed")
        ) from None
    except urllib.error.URLError:
        raise RuntimeError("Cannot reach Gemini API from GitHub runner") from None
    draft = extract_draft(raw)
    result = {
        "model": MODEL,
        "mode": "manual-only, no publishing",
        "source": public_sample()["source_url"],
        "editorial_draft": draft,
        "usage": {
            k: v for k, v in (raw.get("usageMetadata") or {}).items()
            if k in {"promptTokenCount", "candidatesTokenCount", "totalTokenCount"}
            and isinstance(v, (int, float))
        },
    }
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Gemini responded successfully using model " + MODEL, flush=True)
    print("Draft saved as an Actions artifact; nothing published.", flush=True)


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print("GEMINI PROBE ERROR: " + str(exc), file=sys.stderr, flush=True)
        sys.exit(1)
