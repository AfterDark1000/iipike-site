#!/usr/bin/env python3
"""Review-gated reconstruction of user-owned archival HPII articles.

Input: authenticated original titles, historically recorded publication dates,
original Dzen page body, verified article cover. Never invent a source URL.
Only validated items are made into proposed content/approved/<slug>.json files.
This script does not publish HTML, edit Dzen or send any social posts.
"""
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
CAND=ROOT/"research/batch3_candidates.json"
PROBE=ROOT/"research/batch3_probe_results.json"
COVERS=ROOT/"research/batch3_cover_report.json"
DEST=ROOT/"content/approved"
REPORT=ROOT/"research/batch3_preparation_report.json"

RELATED = {
 "ai-site-training-opt-out":["datagpt-source-numbers"],
 "chatgpt-bug-bounty-172k":["ai-browser-assistants-vulnerabilities","ai-firefox-security-flaws"],
 "grok-bot-analysts-70-hours":["agensh-1024-autonomous-agents","musk-grok-bot-cost"],
 "microsoft-ai-consciousness-warning":["anthropic-ipo-biosecurity-warning"],
 "ai-hacker-admin-access":["ai-browser-assistants-vulnerabilities","claude-code-malware-cursor"],
 "ai-browser-assistants-vulnerabilities":["ai-firefox-security-flaws","claude-code-malware-cursor"],
 "mac-audio-transcription-speed":["block-voice-without-text","elevenlabs-als-voice-restoration"],
 "chatgpt-violence-chat-interrupt":["openai-agent-monitoring-four-levels"],
 "claude-code-malware-cursor":["chatgpt-bug-bounty-172k","ai-firefox-security-flaws"],
 "gemini-edit-pdf-sheets":["datagpt-source-numbers"],
 "ai-firefox-security-flaws":["ai-browser-assistants-vulnerabilities"],
 "openai-agent-monitoring-four-levels":["openai-agent-disabled-monitoring","ibm-agent-identity-stop"],
 "mistral-trillion-parameters":["liquid-ai-1gb-models"],
 "russian-claude-passport-ban":["chatgpt-violence-chat-interrupt"],
 "elevenlabs-als-voice-restoration":["block-voice-without-text"],
 "google-robotics-teamwork":["agensh-1024-autonomous-agents"],
 "datagpt-source-numbers":["gemini-edit-pdf-sheets"],
 "akamai-ai-code-sandbox":["ibm-agent-identity-stop","openai-agent-monitoring-four-levels"],
 "swiss-ai-without-us-cloud":["liquid-ai-1gb-models","nvidia-local-assistant-4gb"],
 "ibm-agent-identity-stop":["akamai-ai-code-sandbox","openai-agent-monitoring-four-levels"],
 "liquid-ai-1gb-models":["swiss-ai-without-us-cloud","nvidia-local-assistant-4gb"],
 "alibaba-agent-unapproved-transfer":["openai-agent-disabled-monitoring","claude-paywall-bypass"],
 "anthropic-ipo-biosecurity-warning":["microsoft-ai-consciousness-warning"],
 "openai-scientific-puzzles":["google-ai-orbit"],
 "claude-paywall-bypass":["alibaba-agent-unapproved-transfer","ai-agents-cent-spending-limit"],
 "ai-hackers-anthropic-12h":["claude-code-malware-cursor"],
 "agensh-1024-autonomous-agents":["grok-bot-analysts-70-hours","google-robotics-teamwork"],
 "ai-agents-friends-lonely":["agensh-1024-autonomous-agents"],
 "russian-courts-ai-hallucinations":["datagpt-source-numbers"],
 "block-voice-without-text":["mac-audio-transcription-speed","elevenlabs-als-voice-restoration"],
}
# Related-story candidates reviewed by topic for this historical batch.
RELATED.update({
  "ai-market-intel-alphabet-losses": [
    "openai-power-grid-georgia-1000mw",
    null
  ],
  "openai-power-grid-georgia-1000mw": [
    "ai-market-intel-alphabet-losses"
  ],
  "openai-gpt6-astra-household-benchmark": [
    "chatgpt-service-now-support"
  ],
  "openai-abu-dhabi-regulation-ai": [
    "oracle-chatgpt-accounting"
  ],
  "telus-ai-calls-cancellations": [
    "nvidia-ai-meeting-secretary",
    "chatgpt-service-now-support"
  ],
  "chainalysis-hacked": [
    "malware-ai-scores-victims",
    "south-korea-ai-data-theft"
  ],
  "malware-ai-scores-victims": [
    "chainalysis-hacked",
    "south-korea-ai-data-theft"
  ],
  "claude-mouse-brain-injection": [
    "claude-35k-antibodies",
    "openai-gpt6-biologists-restricted"
  ],
  "openai-gpt6-biologists-restricted": [
    "claude-35k-antibodies",
    "claude-mouse-brain-injection"
  ],
  "ai-680-tokens-second": [
    "nvidia-local-assistant-4gb"
  ],
  "claude-code-pentagon-systems": [
    "ai-hacker-admin-access"
  ],
  "pika-15s-video-7s-compute": [
    "kling40-api-video-price",
    "runway-app-studio-no-code-video"
  ],
  "elevenlabs-sfxv3-ai-sound-design": [
    "indian-voice-model-elevenlabs"
  ],
  "nvidia-ai-meeting-secretary": [
    "telus-ai-calls-cancellations",
    "rime-prism-voice-guardrails"
  ],
  "indian-voice-model-elevenlabs": [
    "elevenlabs-sfxv3-ai-sound-design"
  ],
  "runway-ai-advertising-agent": [
    "runway-app-studio-no-code-video"
  ],
  "nate-soares-retirement-apocalypse": [
    "microsoft-ai-consciousness-warning"
  ],
  "chatgpt-service-now-support": [
    "oracle-chatgpt-accounting"
  ],
  "microsoft-copilot-twenty-models": [
    "microsoft-mai-image-editor"
  ],
  "rime-prism-voice-guardrails": [
    "nvidia-ai-meeting-secretary"
  ],
  "microsoft-mai-image-editor": [
    "gemini4-carbon-ranking"
  ],
  "gemini4-carbon-ranking": [
    "microsoft-mai-image-editor"
  ],
  "kling40-api-video-price": [
    "pika-15s-video-7s-compute"
  ],
  "runway-app-studio-no-code-video": [
    "runway-ai-advertising-agent",
    "pika-15s-video-7s-compute"
  ],
  "south-korea-ai-data-theft": [
    "chainalysis-hacked",
    "malware-ai-scores-victims"
  ],
  "oracle-chatgpt-accounting": [
    "chatgpt-service-now-support",
    "openai-abu-dhabi-regulation-ai"
  ],
  "claude-35k-antibodies": [
    "openai-gpt6-biologists-restricted",
    "claude-mouse-brain-injection"
  ],
  "apple-iwork-ai-agents": [
    "microsoft-copilot-twenty-models"
  ],
  "google-genie4-worlds": [
    "pika-15s-video-7s-compute"
  ],
  "netherlands-civil-service-ai-cuts": [
    "openai-abu-dhabi-regulation-ai"
  ]
})

RELATED.pop("ai-market-intel-alphabet-losses", None)
RELATED["china-ai-stock-bubble-480b"] = ["openai-power-grid-georgia-1000mw"]


def build():
    batch=json.loads(CAND.read_text(encoding="utf-8"))["candidates"]
    probe={r["slug"]:r for r in json.loads(PROBE.read_text(encoding="utf-8"))["results"]}
    covers={r["slug"]:r for r in json.loads(COVERS.read_text(encoding="utf-8"))["entries"]}
    archive=json.loads((ROOT/"data/editorial_full_catalog_snapshot.json").read_text(encoding="utf-8"))["entries"]
    archive_by_id={r["dzen_id"]:r for r in archive}
    already=json.loads((ROOT/"news.json").read_text(encoding="utf-8"))
    ids={r["id"]:r.get("dzen_id") for r in already}
    ids.update({r["slug"]:r["dzen_id"] for r in batch})
    output=[]
    for item in batch:
        slug=item["slug"]
        try:
            trusted=archive_by_id[item["dzen_id"]]
            if (trusted.get("title")!=item["title"] or trusted.get("dzen_url")!=item["dzen_url"]
                or trusted.get("published_at_utc")!=item["published_at_utc"]
                or trusted.get("url_evidence")!="recorded_in_editorial_archive"
                or trusted.get("title_evidence")!="recorded"):
                raise ValueError("Historical provenance mismatch")
            p=probe.get(slug)
            if not p or p.get("http_status")!=200 or p.get("dom",{}).get("og_title")!=item["title"]:
                raise ValueError("Original public Dzen page/title not independently observed")
            text=p["dom"].get("main") or ""
            excerpt=(item.get("excerpt") or "").strip()
            pos=-1
            for n in (120,90,70,50,35,24):
                if len(excerpt)<n:continue
                pos=text.find(excerpt[:n])
                if pos>=0:break
            if pos<0 or pos>1800:raise ValueError("Original body intro cannot be matched to catalog excerpt")
            stop=text.find("\nПодпишитесь на канал,",pos)
            if stop<pos:raise ValueError("Original article end cannot be identified")
            body=text[pos:stop].strip()
            if len(body)<650:raise ValueError(f"Body too short for safe import: {len(body)} chars")
            blocks=[x.strip() for x in body.split("\n\n") if x.strip()]
            if not 2<=len(blocks)<=70:raise ValueError("Invalid paragraph structure")
            if any("Подпишитесь на канал" in x or "Расскажу кратко" in x for x in blocks):
                raise ValueError("Dzen interface noise not removed")
            heads={x["text"] for x in p["dom"].get("headings",[]) if x.get("tag") in ("H2","H3")}
            paragraphs=[{"type":"lead" if i==0 else "h2" if block in heads else "p","text":block} for i,block in enumerate(blocks)]
            report=covers.get(slug)
            if not report or report.get("status")!="downloaded":
                raise ValueError("Original image not recovered")
            cover=report.get("cover")
            if not isinstance(cover,str) or not (ROOT/cover).is_file():
                raise ValueError("Verified cover file missing")
            pub=dt.datetime.fromisoformat(item["published_at_utc"].replace("Z","+00:00"))
            day=pub.astimezone(ZoneInfo("Asia/Yekaterinburg")).date().isoformat()
            raw_summary=excerpt[:280].rsplit(" ",1)[0].strip()
            if len(raw_summary)<50:raise ValueError("Original summary too short")
            rel_ids=[]
            for rel_slug in RELATED.get(slug,[]):
                related_id=ids.get(rel_slug)
                if related_id and related_id!=item["dzen_id"] and related_id not in rel_ids:
                    rel_ids.append(related_id)
            record={
                "slug":slug,"status":"approved",
                "rubric":item["rubric"],"approved_by":"Редакция ХПИИ — перенос авторского архива",
                "approved_at":"2026-11-04",
                "title":item["title"],"summary":raw_summary,
                "published":day,
                "published_at_utc":pub.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "section":"ИСТОРИЧЕСКИЙ АРХИВ",
                "source_url":item["dzen_url"],"source_title":"ХПИИ — исходная публикация в Дзене",
                "cover":cover,
                "dzen_id":item["dzen_id"],"dzen_url":item["dzen_url"],
                "related_dzen_ids":rel_ids,
                "paragraphs":paragraphs
            }
            DEST.mkdir(parents=True,exist_ok=True)
            dst=DEST/(slug+".json")
            if dst.exists(): raise ValueError("Never overwrite a pre-existing approved article")
            dst.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
            output.append({"slug":slug,"status":"ready","cover":cover,"chars":len(body),"paragraphs":len(paragraphs),"date":day})
        except (ValueError,KeyError,TypeError,AttributeError,IndexError) as ex:
            output.append({"slug":slug,"status":"needs_editorial_review","reason":str(ex)})
    REPORT.write_text(json.dumps({
        "note":"Read-only source recovery; no GitHub Pages / Dzen publication performed. Article texts are copies of user-owned Dzen publications, not independently fact-checked new reporting.",
        "requested":len(batch),"ready":sum(r["status"]=="ready" for r in output),
        "not_ready":sum(r["status"]!="ready" for r in output),
        "entries":output
    },ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    for row in output:print(row["status"],row["slug"],row.get("reason",""),flush=True)

if __name__=="__main__":build()
