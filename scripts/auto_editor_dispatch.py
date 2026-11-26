#!/usr/bin/env python3
"""One read-only auto-editor assignment. Never reserves, approves, or publishes."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.auto_editor_workbench import (POOL, REQUESTS, RECEIPTS, DRAFTS,
    claim_ordinary, draft_template, validate_draft, valid_request, request_order)
from scripts.site_news_pool import validate, utc_time
from scripts.editorial_routing import load_routes
from scripts.check_auto_copyeditor_feedback import pending

INBOX = "editorial_inbox/"
TARGET = INBOX + "auto_editor_dispatch/current.json"
GUARDS = ("auto_drafts", "auto_decisions", "auto_copyedits", "auto_copyedit_responses")
RULES = ("docs/AUTO_EDITOR_INSTRUCTIONS.md", "docs/AUTO_EDITOR_STAGE2.md",
         "docs/AUTO_COPYEDITOR_FEEDBACK.md", "editorial_inbox/CHATGPT_EDITOR_INSTRUCTIONS.md")
MAIN_GUARDS = ("data/site_news_pool.json", "data/editorial_routing.json",
               "data/auto_editor/requests", "data/auto_editor/receipts", "news.json")
def read(path):
    return json.loads(path.read_text(encoding="utf-8"))
def docs(root, path):
    return {p.name: read(p) for p in sorted((root/path).glob("*.json"))}
def blob(path):
    raw = path.read_bytes()
    return hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
def gitsha(root, path):
    p = subprocess.run(["git","-C",str(root),"rev-parse","--verify","HEAD:"+path],
                       capture_output=True,text=True)
    return p.stdout.strip() if p.returncode == 0 else None
def select(pool, routes, receipts, drafts, decisions, flags, requests, published, now):
    """Priority: exact human revise, current fact flag, own unfinished, then FIFO preview."""
    byid = {x["id"]:x for x in pool["items"]}
    own = {}
    recent = 0
    for name, rec in receipts.items():
        if rec.get("status") != "reserved" or rec.get("worker") != "hpii-auto-editor":
            continue
        if now-dt.timedelta(hours=24) < utc_time(rec["claimed_at"]) <= now:
            recent += 1
        item = byid.get(rec["pool_id"])
        ident = rec["article_id"]
        if (item and item["status"] == "in_review"
                and item["sequence"] == rec["pool_sequence"]
                and item["review_started_at"] == rec["claimed_at"]
                and item["note"] == "AUTO_EDITOR claim="+name+"; article_id="+ident
                and ident not in published):
            own[ident] = (rec,item)
    human, corrections, unfinished = [], [], []
    waiting = 0
    for ident,(rec,item) in own.items():
        entry = drafts.get(ident)
        if not entry:
            unfinished.append((rec["pool_sequence"],{"kind":"resume","receipt":rec,
                "candidate":item,"draft":draft_template(rec),"draft_sha":None}))
            continue
        draft, sha = entry
        validate_draft(draft,rec)
        name = f"{ident}-r{draft['revision']}.json"
        decision = decisions.get(name)
        job = {"receipt":rec,"candidate":item,"draft":draft,"draft_sha":sha,
               "decision_name":name,"decision_sha":decision[1] if decision else None}
        if decision:
            obj = decision[0]
            if (obj.get("draft_blob_sha") != sha or obj.get("revision") != draft["revision"]
                    or obj.get("updated_at") != draft["updated_at"]):
                # Never overwrite a revision with an ambiguous human decision.
                continue
            if obj.get("action") == "revise":
                human.append((obj["decided_at"],rec["pool_sequence"],
                              {**job,"kind":"revise","decision":obj}))
            continue
        if draft["status"] == "ready_for_review":
            waiting += 1
            for flag in flags:
                if flag["article_id"] == ident and flag["source_draft_blob_sha"] == sha:
                    corrections.append((rec["pool_sequence"],flag["copyedit"],
                                        {**job,"kind":"copyedit","feedback":flag}))
        elif draft["status"] == "drafting":
            unfinished.append((rec["pool_sequence"],{**job,"kind":"resume"}))
        # blocked has a recorded reason and awaits a human or external answer.
    counts = {"reserved_24h":recent,"waiting_review":waiting,"limit":5}
    if human: return "ready",min(human,key=lambda x:x[:2])[2],counts
    if corrections: return "ready",min(corrections,key=lambda x:x[:2])[2],counts
    if unfinished: return "ready",min(unfinished,key=lambda x:x[0])[1],counts
    if requests: return "ready",{"kind":"await_receipt","request":requests[0]},counts
    if recent >= 5: return "quota_full",None,counts
    if waiting >= 5: return "review_window_full",None,counts
    name = "dispatch-"+now.strftime("%Y%m%d-%H%M%S")+".json"
    used = {r["article_id"] for r in receipts.values() if r.get("status")=="reserved"}
    used |= set(published) | set(drafts)
    _, preview = claim_ordinary(pool,name,now=now.isoformat(),used_ids=used,
                                routing=routes,strict_routes=True)
    if not preview: return "idle",None,counts
    return "ready",{"kind":"new","request":name,
        "candidate":byid[preview["pool_id"]],"preview":preview,
        "route":routes[preview["pool_id"]]},counts

def build(main,intake,now):
    pool=read(main/POOL); validate(pool)
    routes=load_routes(pool,root=main)
    receipts=docs(main,RECEIPTS)
    draft_docs={p.stem:(read(p),blob(p)) for p in (intake/DRAFTS).glob("*.json")}
    decisions={p.name:(read(p),blob(p)) for p in (intake/INBOX/"auto_decisions").glob("*.json")}
    flags=pending("origin/editorial-intake")
    requests=[]
    for path in request_order(main):
        if path.name not in receipts:
            valid_request(path)
            requests.append(path.name)
    published={x["id"] for x in read(main/"news.json")}
    published |= {p.stem for p in (intake/INBOX/"stories").glob("*.json")}
    status,job,counts=select(pool,routes,receipts,draft_docs,decisions,flags,requests,published,now)
    return {"schema_version":1,"prepared_at":now.isoformat(),
            "valid_until":(now+dt.timedelta(minutes=90)).isoformat(),
            "status":status,"counts":counts,"job":job,
            "main_guard":{p:gitsha(main,p) for p in MAIN_GUARDS},
            "intake_guard":{INBOX+p:gitsha(intake,INBOX+p) for p in GUARDS},
            "rules":{p:gitsha(main,p) for p in RULES}}
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--main",type=Path,required=True);p.add_argument("--intake",type=Path,required=True)
    p.add_argument("--write",action="store_true")
    a=p.parse_args()
    result=build(a.main,a.intake,dt.datetime.now(dt.timezone.utc))
    if a.write:
        dest=a.intake/TARGET
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":result["status"],"counts":result["counts"],
                      "kind":(result["job"] or {}).get("kind"),
                      "sequence":((result["job"] or {}).get("candidate") or {}).get("sequence")},ensure_ascii=False))
if __name__=="__main__":
    main()
