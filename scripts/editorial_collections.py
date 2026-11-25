#!/usr/bin/env python3
"""Editorial accumulation groups: verified, chief-approved, nonpublishing transitions.

The existing editorial routing is the *enforcement* mechanism:
  collecting       -> primary defer/hold; members linked_secondary/hold
  ready_for_editor -> primary linked_primary/long; members linked_secondary/hold

No special pool status, no bypass of reservations, and no fixed member count.
"""
import copy
import json
from pathlib import Path
import re
import sys

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from scripts import editorial_routing, site_news_pool

PATH = Path("data/editorial_collections.json")
STATES = {"collecting", "ready_for_editor"}
GROUP = re.compile(r"[a-z][a-z0-9_]{4,79}\Z")
POOL_ID = re.compile(r"n-[0-9a-f]{16}\Z")
COMMON = {"schema_version", "action", "worker", "approval"}


def empty():
    return {"schema_version": 1, "items": []}


def _member(value):
    if (type(value) is not dict or set(value) != {"sequence", "pool_id"} or
            type(value["sequence"]) is not int or value["sequence"] < 1 or
            type(value["pool_id"]) is not str or not POOL_ID.fullmatch(value["pool_id"])):
        raise ValueError("Collection member requires exact sequence and pool_id")


def _collection(value):
    if (type(value) is not dict or set(value) != {
            "group", "title", "state", "primary_sequence", "members", "note"}):
        raise ValueError("Invalid collection fields")
    if (type(value["group"]) is not str or not GROUP.fullmatch(value["group"]) or
            type(value["title"]) is not str or not 8 <= len(value["title"]) <= 220 or
            type(value["note"]) is not str or not 5 <= len(value["note"]) <= 900 or
            value["state"] not in STATES or
            type(value["primary_sequence"]) is not int or value["primary_sequence"] < 1 or
            type(value["members"]) is not list or not 1 <= len(value["members"]) <= 30):
        raise ValueError("Invalid editorial collection metadata")
    for member in value["members"]:
        _member(member)
    seqs = [x["sequence"] for x in value["members"]]
    ids = [x["pool_id"] for x in value["members"]]
    if (len(set(seqs)) != len(seqs) or len(set(ids)) != len(ids) or
            seqs != sorted(seqs) or value["primary_sequence"] not in seqs):
        raise ValueError("Duplicate, unsorted or missing primary collection members")


def validate_request(req):
    if (type(req) is not dict or not COMMON <= set(req) or
            req["schema_version"] != 1 or req["worker"] != "hpii-morning-triage" or
            req["approval"] != "explicit_chief_editor_chat_command"):
        raise ValueError("Collection requests require explicit chief-editor approval")
    if req["action"] == "collection_upsert":
        if set(req) != COMMON | {"collection"}:
            raise ValueError("Unexpected collection request fields")
        _collection(req["collection"])
    elif req["action"] == "collection_release_member":
        if set(req) != COMMON | {"group", "member", "decision"}:
            raise ValueError("Unexpected member-release fields")
        if (type(req["group"]) is not str or not GROUP.fullmatch(req["group"]) or
                req["decision"] not in {"full", "hot"}):
            raise ValueError("Invalid member release")
        _member(req["member"])
    else:
        raise ValueError("Unsupported collection action")
    return req


def validate_document(doc, pool, routes_doc):
    """Fail closed if a managed collection's persisted state and routes diverge."""
    site_news_pool.validate(pool)
    editorial_routing.validate_document(routes_doc, pool)
    if (type(doc) is not dict or set(doc) != {"schema_version", "items"} or
            doc["schema_version"] != 1 or type(doc["items"]) is not list or
            len(doc["items"]) > 200):
        raise ValueError("Invalid collections registry")
    by_seq = {x["sequence"]: x for x in pool["items"]}
    by_route = {x["sequence"]: x for x in routes_doc["items"]}
    groups = set()
    occupied = set()
    for col in doc["items"]:
        _collection(col)
        group = col["group"]
        if group in groups:
            raise ValueError("Duplicate collection group")
        groups.add(group)
        members = {m["sequence"]: m["pool_id"] for m in col["members"]}
        if occupied.intersection(members):
            raise ValueError("A story may not belong to two collections")
        occupied.update(members)
        # No additional route may silently join or leave an existing group.
        group_routes = {seq for seq, route in by_route.items() if route.get("group") == group}
        if group_routes != set(members):
            raise ValueError("Collection membership differs from editorial routing")
        for seq, rid in members.items():
            item, route = by_seq.get(seq), by_route.get(seq)
            if item is None or item["id"] != rid or route is None or route["pool_id"] != rid:
                raise ValueError("Collection pool ID or sequence changed")
            primary = seq == col["primary_sequence"]
            decision = ("defer" if col["state"] == "collecting" else "linked_primary") if primary else "linked_secondary"
            lane = "hold" if col["state"] == "collecting" or not primary else "long"
            if (route["decision"] != decision or route["lane"] != lane or
                    route.get("group_primary") != col["primary_sequence"]):
                raise ValueError("Collection state does not match locked editorial route")
            if col["state"] == "collecting" and item["status"] != "queued":
                raise ValueError("Collecting member has already been reserved or closed")
    return doc


def _apply(pool, routes_doc, doc, *, source):
    routes_doc["items"] = sorted(routes_doc["items"], key=lambda x: x["sequence"])
    routes_doc["source"] = source
    routes_doc["approved_date"] = site_news_pool.stamp()[:10]
    routes_doc["note"] = "Chief-approved collection transition; no publication."
    editorial_routing.validate_document(routes_doc, pool)
    validate_document(doc, pool, routes_doc)
    return pool, routes_doc, doc


def apply_request(pool, routes_doc, collections_doc, request, *, source):
    """Atomic *plan*; persistence is owned by triage_apply_requests.consume."""
    validate_request(request)
    validate_document(collections_doc, pool, routes_doc)
    newpool, newroutes, newcols = (
        copy.deepcopy(pool), copy.deepcopy(routes_doc), copy.deepcopy(collections_doc))
    by_seq = {x["sequence"]: x for x in newpool["items"]}
    routes = {x["sequence"]: x for x in newroutes["items"]}
    groups = {x["group"]: x for x in newcols["items"]}

    if request["action"] == "collection_upsert":
        col = copy.deepcopy(request["collection"])
        group = col["group"]
        old = groups.get(group)
        if old is not None:
            if old["primary_sequence"] != col["primary_sequence"]:
                raise ValueError("Changing collection primary requires separate review")
            old_members = {m["sequence"]: m["pool_id"] for m in old["members"]}
            incoming = {m["sequence"]: m["pool_id"] for m in col["members"]}
            if any(incoming.get(seq) != rid for seq, rid in old_members.items()):
                raise ValueError("Removing a collection member requires approved release")
            if old["state"] == "ready_for_editor" and incoming != old_members:
                raise ValueError("Cannot append after collection is ready for editor")
        for m in col["members"]:
            seq, rid = m["sequence"], m["pool_id"]
            item = by_seq.get(seq)
            current = routes.get(seq)
            if item is None or item["id"] != rid or item["status"] != "queued":
                raise ValueError("Collection contains unknown or reserved item")
            if (current is not None and
                    current.get("group") not in (None, group)):
                raise ValueError("Item is already reserved for another group")
            if current and current["decision"] == "hot" or item["priority"] == "high":
                raise ValueError("Hot stories must remain standalone")
        # An already registered collection must not be silently reattached elsewhere.
        if old is None and any(x.get("group") == group for x in newroutes["items"]
                               if x["sequence"] not in {m["sequence"] for m in col["members"]}):
            raise ValueError("Collection group already exists outside new membership")
        if old == col:
            return pool, routes_doc, collections_doc, {
                "applied": [], "unchanged": [x["sequence"] for x in col["members"]],
                "skipped": []}
        for m in col["members"]:
            seq, rid = m["sequence"], m["pool_id"]
            primary = seq == col["primary_sequence"]
            decision = ("defer" if col["state"] == "collecting" else "linked_primary") if primary else "linked_secondary"
            routes[seq] = {
                "sequence": seq, "pool_id": rid, "lane":
                    ("hold" if col["state"] == "collecting" or not primary else "long"),
                "decision": decision, "group": group, "group_primary": col["primary_sequence"]}
        groups[group] = col
        newcols["items"] = sorted(groups.values(), key=lambda x: x["group"])
        newroutes["items"] = list(routes.values())
        _apply(newpool, newroutes, newcols, source=source)
        return newpool, newroutes, newcols, {
            "applied": [x["sequence"] for x in col["members"]], "unchanged": [],
            "skipped": []}

    group = request["group"]
    col = groups.get(group)
    if col is None or col["state"] != "collecting":
        raise ValueError("Only collecting groups allow a member to leave")
    m = request["member"]
    seq, rid = m["sequence"], m["pool_id"]
    if seq == col["primary_sequence"]:
        raise ValueError("Cannot release the primary without choosing a replacement")
    if m not in col["members"] or by_seq.get(seq, {}).get("id") != rid:
        raise ValueError("Member does not match registered collection")
    if by_seq[seq]["status"] != "queued":
        raise ValueError("Cannot release a reserved or closed member")
    col["members"] = [x for x in col["members"] if x != m]
    decision = request["decision"]
    routes[seq] = {
        "sequence": seq, "pool_id": rid, "lane": "long", "decision": decision}
    if decision == "hot":
        by_seq[seq]["priority"] = "high"
    newroutes["items"] = list(routes.values())
    newcols["items"] = sorted(groups.values(), key=lambda x: x["group"])
    _apply(newpool, newroutes, newcols, source=source)
    return newpool, newroutes, newcols, {
        "applied": [seq], "unchanged": [], "skipped": []}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    pool = json.loads((root / "data/site_news_pool.json").read_text(encoding="utf-8"))
    routes = json.loads((root / editorial_routing.ROUTES).read_text(encoding="utf-8"))
    path = root / PATH
    doc = json.loads(path.read_text(encoding="utf-8")) if path.exists() else empty()
    validate_document(doc, pool, routes)
    print(json.dumps({"collections": len(doc["items"]), "states": {
        state: sum(x["state"] == state for x in doc["items"]) for state in STATES}}))


if __name__ == "__main__":
    main()
