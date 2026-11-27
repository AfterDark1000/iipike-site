#!/usr/bin/env python3
"""Deterministic, non-publishing artist dispatcher. No model, image or API keys."""
import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
STEM = re.compile(r"([a-z0-9]+(?:-[a-z0-9]+)*)-r([1-9]\d*)-v([1-5])")
ROOT = "editorial_inbox/"
DISPATCH = ROOT + "auto_artist_dispatch/"
LIMIT = 5
RETRY_DELAY = timedelta(hours=2)
RETRY_SUFFIX = '-retry-1'

def read(path):
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"Expected object: {path}")
    return obj

def stamp(s):
    if not isinstance(s, str):
        raise ValueError("Missing timestamp")
    v = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if v.tzinfo is None:
        raise ValueError("Timestamp without timezone")
    return v.astimezone(timezone.utc)

def iso(t):
    return t.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")

def blob(path):
    raw = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()

def records(folder):
    return {p.stem: (read(p), blob(p)) for p in sorted(folder.glob("*.json"))}

def tree_sha(root, path):
    p = subprocess.run(["git", "rev-parse", "--verify", "HEAD:"+path],
                       cwd=root, capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else None

def build(root, published, holds, now, parallel):
    inbox = root / ROOT
    drafts = records(inbox/"auto_drafts")
    texts = records(inbox/"auto_decisions")
    covers = records(inbox/"auto_covers")
    reviews = records(inbox/"auto_cover_decisions")
    handoffs = records(inbox/"auto_handoffs")
    claims = records(inbox/"auto_artist_dispatch"/"claims")
    failures = records(inbox/"auto_artist_dispatch"/"failures")
    legacy = records(inbox/"auto_covers"/"attempts")
    quota = {}
    for key, (obj, _) in covers.items():
        if not STEM.fullmatch(key):
            raise ValueError("Invalid candidate filename: "+key)
        quota[key] = stamp(obj["created_at"])
    for key, (obj, _) in claims.items():
        is_retry = key.endswith(RETRY_SUFFIX)
        stem = key[:-len(RETRY_SUFFIX)] if is_retry else key
        if (not STEM.fullmatch(stem) or obj.get("stem") != stem or
                obj.get("schema_version") != 1 or obj.get("state") != "generation_reserved" or
                (is_retry and obj.get("attempt") != 2) or
                (not is_retry and obj.get("attempt", 1) != 1)):
            raise ValueError("Invalid artist claim: "+key)
        t = stamp(obj["reserved_at"])
        quota_key = "retry:"+stem if is_retry else stem
        quota[quota_key] = max(t, quota.get(quota_key, t))
    # Failure receipts never erase historical claims or quota. They only
    # authorize a single separately-reserved retry when the image did not start.
    for key, (obj, _) in failures.items():
        original = claims.get(key)
        if (not STEM.fullmatch(key) or original is None or
                obj.get("schema_version") != 1 or obj.get("stem") != key or
                obj.get("state") != "generation_not_started" or
                obj.get("error") != "Image generation has not started" or
                obj.get("image_created") is not False or obj.get("attempt") != 1 or
                obj.get("claim_blob_sha") != original[1]):
            raise ValueError("Invalid artist failure receipt: "+key)
        if stamp(obj["reported_at"]) < stamp(original[0]["reserved_at"]):
            raise ValueError("Failure receipt predates reservation: "+key)
    # Old attempts may represent a genuinely separate generation; count them conservatively.
    for key, (obj, _) in legacy.items():
        quota["legacy:"+key] = stamp(obj["created_at"])
    hold_keys = set()
    for obj in holds:
        key = obj["stem"]
        if not STEM.fullmatch(key) or key in hold_keys:
            raise ValueError("Invalid or duplicate artist hold")
        hold_keys.add(key)
        if key not in covers and key not in claims:
            quota[key] = stamp(obj["recorded_at"])
    if any(t > now + timedelta(minutes=3) for t in quota.values()):
        raise ValueError("Future generation timestamp")
    used = sum(t > now-timedelta(hours=24) for t in quota.values())
    result = {"schema_version":1, "prepared_at":iso(now),
              "valid_until":iso(now+timedelta(minutes=90)), "status":"idle",
              "quota":{"used":used,"limit":LIMIT,"remaining":max(0,LIMIT-used)},
              "parallel_cover_review":parallel,"job":None,"waiting_for_manual_upload":[]}
    eligible = []
    for sid,(draft,dsha) in drafts.items():
        if not ID.fullmatch(sid) or len(sid)>72 or draft.get("article_id")!=sid:
            raise ValueError("Invalid draft identity "+sid)
        rev=draft.get("revision")
        if type(rev) is not int or rev<1 or draft.get("status")!="ready_for_review" or sid in published:
            continue
        prefix=f"{sid}-r{rev}"
        if any(k.startswith(prefix+"-v") for k in handoffs):
            continue
        t, tsha=texts.get(prefix,(None,None))
        if t is not None:
            if (t.get("action")!="approve_text" or t.get("status")!="text_approved_cover_pending" or
                t.get("article_id")!=sid or t.get("revision")!=rev or
                t.get("updated_at")!=draft.get("updated_at") or t.get("draft_blob_sha")!=dsha or
                t.get("decided_by")!="AfterDark1000"):
                continue
        elif not parallel:
            continue
        current=[(int(k.rsplit("-v",1)[1]),k) for k in covers if k.startswith(prefix+"-v")]
        ver=1
        previous=None
        if current:
            ver0,key=max(current)
            meta,msha=covers[key]
            dec,ds=reviews.get(key,(None,None))
            if (ver0>=5 or not dec or dec.get("action")!="revise_cover" or
                dec.get("status")!="cover_revision_requested" or dec.get("decided_by")!="AfterDark1000" or
                dec.get("article_id")!=sid or dec.get("text_revision")!=rev or
                dec.get("cover_version")!=ver0 or dec.get("source_draft_blob_sha")!=dsha or
                dec.get("text_updated_at")!=draft.get("updated_at") or
                dec.get("source_text_decision_blob_sha") not in (None,tsha) or
                dec.get("cover_metadata_blob_sha")!=msha or
                meta.get("source_draft_blob_sha")!=dsha or
                meta.get("text_revision")!=rev or meta.get("article_id")!=sid or
                dec.get("cover_blob_sha")!=meta.get("image_blob_sha") or
                not isinstance(dec.get("note"),str) or not dec["note"].strip()):
                continue
            image=inbox/"auto_covers"/(key+".webp")
            if not image.is_file() or blob(image)!=meta.get("image_blob_sha"):
                continue
            ver=ver0+1
            previous={"stem":key,"decision_sha":ds,"metadata_sha":msha,
                      "image_sha":meta["image_blob_sha"],"note":dec["note"],
                      "headline":meta.get("headline"),"concept":meta.get("concept"),
                      "artist_notes":meta.get("artist_notes")}
        key=f"{prefix}-v{ver}"
        if key in covers or (inbox/"auto_covers"/(key+".webp")).exists() or key in reviews:
            continue
        retry = False
        failure_sha = None
        original_sha = None
        if key in hold_keys or key+RETRY_SUFFIX in claims:
            result["waiting_for_manual_upload"].append({"stem":key,"title":draft.get("content",{}).get("title"),"state":"reserved_or_prior_attempt"})
            continue
        if key in claims:
            failure, failure_sha = failures.get(key, (None, None))
            original, original_sha = claims[key]
            # No inferred failures, no retry of a changed text or decision,
            # and no repeated automatic retries after the second reservation.
            if (failure is None or failure.get("source_draft_blob_sha") != dsha or
                    failure.get("source_text_decision_blob_sha") != tsha or
                    original.get("source_draft_blob_sha") != dsha or
                    stamp(failure["reported_at"])+RETRY_DELAY > now):
                result["waiting_for_manual_upload"].append({"stem":key,"title":draft.get("content",{}).get("title"),"state":"reserved_or_prior_attempt"})
                continue
            retry = True
        content=draft.get("content",{})
        if not isinstance(content,dict) or not all(isinstance(content.get(k),str) and content[k].strip() for k in ("title","article_markdown")):
            continue
        if not isinstance(draft.get("cover_brief"),dict) or type(draft.get("pool_sequence")) is not int:
            continue
        job={"stem":key,"article_id":sid,"revision":rev,"version":ver,
             "draft_sha":dsha,"text_updated_at":draft["updated_at"],
             "text_decision_sha":tsha,"pool_sequence":draft["pool_sequence"],
             "title":content["title"],"article_markdown":content["article_markdown"],
             "source_url":content.get("source_url"),"cover_brief":draft["cover_brief"],
             "previous":previous}
        if retry:
            job.update({"attempt":2,"retry_of_claim_sha":original_sha,
                        "retry_failure_sha":failure_sha})
        eligible.append((0 if previous else 1,draft["pool_sequence"],sid,job))
    if used>=LIMIT:
        result["status"]="quota_full"
    elif eligible:
        result["status"]="ready"
        result["job"]=min(eligible,key=lambda v:v[:3])[3]
        job = result["job"]
        result["job"]["claim_path"]=DISPATCH+"claims/"+job["stem"]+(
            RETRY_SUFFIX if job.get("attempt") == 2 else "")+".json"
        recent=sorted(covers.items(),key=lambda kv:stamp(kv[1][0]["created_at"]),reverse=True)[:8]
        result["recent_artwork"]=[{"stem":k,"image_path":v[0].get("image_path"),
            "headline":v[0].get("headline"),"concept":v[0].get("concept"),
            "artist_notes":v[0].get("artist_notes")} for k,v in recent]
        result["guard"]={"covers_tree":tree_sha(root,ROOT+"auto_covers"),
                         "claims_tree":tree_sha(root,DISPATCH+"claims"),
                         "failures_tree":tree_sha(root,DISPATCH+"failures")}
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--intake",type=Path,required=True)
    p.add_argument("--main",type=Path,required=True)
    p.add_argument("--parallel",action="store_true")
    a=p.parse_args()
    news=json.loads((a.main/"news.json").read_text(encoding="utf-8"))
    policy=read(a.main/"data/auto_artist_holds.json")
    if policy.get("schema_version")!=1 or not isinstance(policy.get("holds"),list):
        raise ValueError("Invalid artist hold configuration")
    ticket=build(a.intake,{x["id"] for x in news},policy["holds"],datetime.now(timezone.utc),a.parallel)
    if ticket["job"]:
        base = "docs/artist_plugin/"
        paths = [base+"README.md", base+"skills/hpii-cover/SKILL.md",
                 *[base+"skills/hpii-cover/references/"+name for name in (
                     "HPII_Cover_Standard.md", "artistic-toolkit.md", "composition-toolkit.md",
                     "style-diversity-regression.md")],
                 base+"skills/hpii-auto-cover/SKILL.md"]
        files = [{"path":name, "sha":blob(a.main/name)} for name in paths]
        ticket["art_standard"] = {
            "fingerprint":hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest(),
            "files":files,
        }
    target=a.intake/DISPATCH/"current.json"
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(ticket,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":ticket["status"],"quota":ticket["quota"],
        "next":ticket["job"]["stem"] if ticket["job"] else None,
        "manual":ticket["waiting_for_manual_upload"]},ensure_ascii=False))
if __name__=="__main__":
    main()
