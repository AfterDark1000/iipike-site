#!/usr/bin/env python3
"""ХПИИ: find rising short-video formats, inspect public YouTube URLs with Gemini.

Research ONLY. Never download/repost media or publish editorial material.
No third-party dependencies. Requires GEMINI_API_KEY; daily discovery also
requires YOUTUBE_API_KEY. API credentials are read from environment only.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "data" / "shorts_format_analysis.json"
HISTORY = ROOT / "data" / "shorts_trend_history.json"
MODEL = os.environ.get("SHORTS_GEMINI_MODEL", "gemini-3.5-flash-lite")
MAX_ANALYSES = min(5, max(1, int(os.environ.get("SHORTS_MAX_ANALYSES", "4"))))
LOOKBACK_DAYS = 7
PILOT_IDS = ("rXgv9bxT8gw", "_ncGUlKhKR8", "YkL5X5KB9ts", "7xS87iActkU")
SEARCHES = (
    "unexpected engineering explained",
    "oddly satisfying experiment",
    "science facts visualization",
    "technology surprising invention",
)
SCHEMA = {
    "type": "object",
    "properties": {
        "observed_visuals": {"type": "string"},
        "observed_audio": {"type": "string"},
        "hook_0_3s": {"type": "string"},
        "timeline": {"type": "array", "items": {
            "type": "object", "properties": {
                "time": {"type": "string"},
                "visible_action": {"type": "string"},
                "editing": {"type": "string"},
                "confidence": {"type": "string", "enum": ["seen", "inferred"]},
            }, "required": ["time", "visible_action", "editing", "confidence"]
        }},
        "format_mechanic": {"type": "string"},
        "transfer_to_hpii": {"type": "string"},
        "what_not_to_copy": {"type": "string"},
        "limitations": {"type": "string"},
        "evidence_quality": {"type": "string", "enum": ["observed", "partial", "unsupported"]},
    },
    "required": ["observed_visuals", "observed_audio", "hook_0_3s",
                 "timeline", "format_mechanic", "transfer_to_hpii",
                 "what_not_to_copy", "limitations", "evidence_quality"]
}
PROMPT = """Ты — видеоаналитик ХПИИ, а не генератор идей по заголовку.
Посмотри ПРИЛОЖЕННОЕ видео с изображением и звуком. Не считай описание,
заголовок, количество просмотров и гипотезы пользователя доказательством кадров.
Кратко разметь крючок 0–3 секунды, видимые события и монтаж с таймкодами.
Описывай только реально увиденное/услышанное; где нельзя различить движение,
озвучку, монтаж или последовательность, прямо укажи «не видно» или «не установлено»
и выставь confidence=inferred. Быстрые склейки могут пропадать при выборке 1 FPS.
Если видео недоступно, поставь evidence_quality=unsupported, не придумывай сцен.
Если просмотр частичный, поставь partial. Не переписывай чужой сценарий и
дословные реплики; выдели только общую драматургическую/монтажную механику.
Предложи ОРИГИНАЛЬНОЕ применение к новости об ИИ без копирования кадров/звука.
Строго верни JSON по схеме. Пиши по-русски."""

def now_utc():
    return datetime.now(timezone.utc)

def iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def parse_date(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default

def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def request_json(url, *, payload=None, headers=None, timeout=35):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    hdr = {"User-Agent": "HPII-format-research/1.0", **(headers or {})}
    if body is not None:
        hdr["Content-Type"] = "application/json"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=hdr), timeout=timeout) as response:
            return json.loads(response.read(2_000_000))
    except urllib.error.HTTPError as exc:
        # Never log URL, response body, or API credentials.
        raise RuntimeError("API HTTP " + str(exc.code)) from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError("API network/timeout error") from None

def youtube(endpoint, params, key):
    query = urllib.parse.urlencode({**params, "key": key})
    return request_json("https://www.googleapis.com/youtube/v3/" + endpoint + "?" + query)

def seconds_from_iso8601_duration(value):
    match = re.fullmatch(r"P(?:\d+D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not match:
        return None
    h, m, s = match.groups()
    return int(h or 0)*3600 + int(m or 0)*60 + int(s or 0)

def fetch_video_details(ids, key):
    if not ids:
        return []
    ids = list(dict.fromkeys(ids))[:50]
    res = youtube("videos", {"part": "snippet,contentDetails,statistics", "id": ",".join(ids)}, key)
    items = res.get("items", [])
    channel_ids = list({i.get("snippet", {}).get("channelId", "") for i in items} - {""})
    channels = {}
    if channel_ids:
        for item in youtube("channels", {"part": "statistics", "id": ",".join(channel_ids)}, key).get("items", []):
            stats = item.get("statistics", {})
            channels[item["id"]] = int(stats["subscriberCount"]) if "subscriberCount" in stats else None
    result = []
    for item in items:
        meta, stats = item.get("snippet", {}), item.get("statistics", {})
        duration = seconds_from_iso8601_duration(item.get("contentDetails", {}).get("duration"))
        if duration is None or duration < 8 or duration > 180:
            continue  # duration alone does NOT prove YouTube classified it as a Short
        try:
            views = int(stats.get("viewCount", 0))
            likes = int(stats.get("likeCount", 0)) if "likeCount" in stats else None
        except (TypeError, ValueError):
            continue
        result.append({
            "id": item["id"],
            "url": "https://www.youtube.com/shorts/" + item["id"],
            "title": meta.get("title", "")[:180],
            "channel": meta.get("channelTitle", "")[:120],
            "published_at": meta.get("publishedAt"),
            "duration_seconds": duration,
            "views": views,
            "likes": likes,
            "subscribers": channels.get(meta.get("channelId")),
            "statistics_source": "YouTube Data API v3",
            "statistics_checked_at": iso(now_utc()),
            "is_confirmed_short": False,  # Data API offers no definitive Shorts classifier
        })
    return result

def history_growth(video, history):
    observations = history.get("items", {}).get(video["id"], [])
    recent = [i for i in observations if i.get("views") is not None and i.get("checked_at")]
    if not recent or video.get("views") is None:
        return None
    try:
        previous = recent[-1]
        hours = (now_utc() - parse_date(previous["checked_at"])).total_seconds() / 3600
        if hours < 0.5 or hours > 168:
            return None
        return round((video["views"] - int(previous["views"])) / hours, 1)
    except (ValueError, KeyError, TypeError):
        return None

def score_video(video):
    age_h = max(1, (now_utc() - parse_date(video["published_at"])).total_seconds() / 3600)
    speed = video["views"] / age_h
    subs = video.get("subscribers")
    relative = video["views"] / max(1000, subs) if subs is not None else 0
    score = math.log1p(speed) + 0.8 * math.log1p(relative)
    if video.get("growth_views_per_hour") is not None:
        score += 0.6 * math.log1p(max(0, video["growth_views_per_hour"]))
    return round(score, 2)

def discover(key, history):
    since = iso(now_utc() - timedelta(days=LOOKBACK_DAYS))
    ids = []
    for q in SEARCHES:
        result = youtube("search", {
            "part": "snippet", "q": q, "type": "video",
            "order": "viewCount", "publishedAfter": since,
            "videoDuration": "short", "maxResults": 15,
        }, key)
        ids.extend(x.get("id", {}).get("videoId") for x in result.get("items", []))
    details = fetch_video_details([i for i in ids if i], key)
    cutoff = now_utc() - timedelta(days=LOOKBACK_DAYS)
    candidates = []
    for v in details:
        try:
            if parse_date(v["published_at"]) < cutoff:
                continue
        except (ValueError, KeyError, TypeError):
            continue
        v["growth_views_per_hour"] = history_growth(v, history)
        v["rank_score"] = score_video(v)
        v["viral_status"] = ("candidate_verified_stats" if v["views"] >= 10000
             and v["subscribers"] is not None and
             v["views"] >= 3 * max(1000, v["subscribers"]) else "unconfirmed")
        candidates.append(v)
    return sorted(candidates, key=lambda x: x["rank_score"], reverse=True)

def collect_history(history, candidates):
    items = history.setdefault("items", {})
    for video in candidates:
        if video.get("views") is None:
            continue
        observations = items.setdefault(video["id"], [])
        observations.append({"checked_at": iso(now_utc()),
                             "views": video["views"], "likes": video["likes"]})
        items[video["id"]] = observations[-30:]
    if len(items) > 300:
        ordered = sorted(items, key=lambda k: items[k][-1].get("checked_at", ""), reverse=True)
        history["items"] = {k: items[k] for k in ordered[:300]}
    history["schema_version"] = 1
    history["updated_at_utc"] = iso(now_utc())
    return history

def extract_output(result):
    if result.get("status") not in ("completed", None):
        raise RuntimeError("Gemini response not completed")
    texts = []
    for step in result.get("steps", []):
        if step.get("type") != "model_output":
            continue
        for part in step.get("content", []):
            if part.get("type") == "text":
                texts.append(part.get("text", ""))
    if not texts:
        raise RuntimeError("Gemini returned no text")
    return json.loads("".join(texts))

def analyze_gemini(video, key):
    body = {
        "model": MODEL, "store": False,
        "input": [{"type": "text", "text": PROMPT},
                  {"type": "video", "uri": "https://www.youtube.com/watch?v=" + video["id"]}],
        "response_format": {"type": "text", "mime_type": "application/json", "schema": SCHEMA},
    }
    response = request_json("https://generativelanguage.googleapis.com/v1beta/interactions",
                            payload=body, headers={"x-goog-api-key": key}, timeout=95)
    analysis = extract_output(response)
    if not isinstance(analysis, dict) or any(not analysis.get(k) for k in SCHEMA["required"] if k != "timeline"):
        raise RuntimeError("Gemini returned incomplete structured analysis")
    if analysis.get("evidence_quality") not in ("observed", "partial", "unsupported"):
        raise RuntimeError("Gemini evidence flag invalid")
    if not isinstance(analysis.get("timeline"), list):
        raise RuntimeError("Gemini timeline invalid")
    return analysis

def run(mode):
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    youtube_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not gemini_key:
        raise RuntimeError("Missing GEMINI_API_KEY secret (no API calls made)")
    if mode == "daily" and not youtube_key:
        raise RuntimeError("Missing YOUTUBE_API_KEY secret for daily discovery (no API calls made)")
    history = load_json(HISTORY, {"schema_version": 1, "items": {}})
    previous = load_json(RESULTS, {"videos": []})
    if mode == "pilot":
        if youtube_key:
            try:
                candidates = fetch_video_details(PILOT_IDS, youtube_key)
            except RuntimeError:
                candidates = []
        else:
            candidates = []
        by_id = {v["id"]: v for v in candidates}
        candidates = [by_id.get(i, {
            "id": i, "url": "https://www.youtube.com/shorts/" + i,
            "title": None, "views": None, "likes": None, "subscribers": None,
            "published_at": None, "duration_seconds": None,
            "statistics_source": "unavailable", "viral_status": "unconfirmed",
            "is_confirmed_short": False,
        }) for i in PILOT_IDS]
    else:
        candidates = discover(youtube_key, history)
    history = collect_history(history, candidates)
    # No Gemini repeat for the exact same URL within 72h in daily mode.
    recent_ids = set()
    for old in previous.get("videos", []):
        try:
            if old.get("status") == "analyzed" and now_utc() - parse_date(old["analyzed_at_utc"]) < timedelta(hours=72):
                recent_ids.add(old["id"])
        except (KeyError, TypeError, ValueError):
            pass
    selected = [v for v in candidates if mode == "pilot" or v["id"] not in recent_ids][:MAX_ANALYSES]
    output = {"schema_version": 1, "mode": mode, "generated_at_utc": iso(now_utc()),
              "status": "no_candidates" if not selected else "partial",
              "limits": {"maximum_gemini_requests": MAX_ANALYSES,
                         "daily_youtube_search_calls": len(SEARCHES) if mode == "daily" else 0},
              "videos": [], "errors": []}
    for video in selected:
        record = dict(video)
        try:
            analysis = analyze_gemini(video, gemini_key)
            record.update({"analysis": analysis, "analyzed_at_utc": iso(now_utc()),
                           "model": MODEL,
                           "status": "analyzed" if analysis["evidence_quality"] != "unsupported" else "unsupported"})
        except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
            record.update({"status": "failed", "failure": str(exc)[:120]})
            output["errors"].append({"video_id": video["id"], "code": "analysis_failed"})
        output["videos"].append(record)
    successful = sum(v["status"] == "analyzed" for v in output["videos"])
    if selected:
        output["status"] = "ok" if successful == len(selected) else "partial"
    save_json(HISTORY, history)
    save_json(RESULTS, output)
    print(f"mode={mode} candidates={len(candidates)} analyzed={successful} failures={len(output['errors'])}")
    if selected and not successful:
        raise RuntimeError("No videos could be observed; inspect report, do not claim success")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("daily", "pilot"), default="daily")
    args = parser.parse_args()
    try:
        run(args.mode)
    except RuntimeError as exc:
        print("Shorts hunter: " + str(exc), file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
