"""SNF reports: the daily in/out of every member of the group, from FIO.

Per member and per base (site), per material, per day:
  out - what the production lines make,
  in  - what the production lines use,
  wf  - what the workforce consumes,
  net = out - in - wf  (> 0 surplus, < 0 deficit).

Production follows Refined PrUn (src/core/burn.ts): per line, the queued orders (not started) -
only the recurring ones when the member has any recurring order - and every order counts as
amount * capacity / (sum of the durations of those orders, in days).

Workforce: the needs FIO gives (UnitsPerInterval per day, tiers with population > 1 and capacity > 0,
as RP). A member who does not share workforce with the group (FIO answers 401) gets it calculated:
the workers the buildings of the base require x the needs per 100 workers of the tier.

python fio_report.py <out.json>
env: FIO_KEY (required), FIO_GROUP (default 84306218)
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://rest.fnar.net"
TIERS = [("Pioneers", "PIONEER"), ("Settlers", "SETTLER"), ("Technicians", "TECHNICIAN"),
         ("Engineers", "ENGINEER"), ("Scientists", "SCIENTIST")]
DAY_MS = 86400000.0


def get(path, key=None, tries=3):
    headers = {"accept": "application/json"}
    if key:
        headers["Authorization"] = key
    for i in range(tries):
        try:
            req = urllib.request.Request(API + path, headers=headers)
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.status, json.loads(r.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                return e.code, None
            err = e.code
        except (urllib.error.URLError, TimeoutError) as e:
            err = str(e)
        time.sleep(3 * (i + 1))
    return err, None


def add(bucket, ticker, field, value):
    row = bucket.setdefault(ticker, {"in": 0.0, "out": 0.0, "wf": 0.0})
    row[field] += value


def production_burn(lines, sites):
    """{site_id: {ticker: {in, out}}} from FIO production lines."""
    any_recurring = any(o.get("Recurring") for l in lines for o in (l.get("Orders") or []))
    res = {}
    for line in lines:
        orders = [o for o in (line.get("Orders") or []) if not o.get("StartedEpochMs")]
        if any_recurring:
            orders = [o for o in orders if o.get("Recurring")]
        if not orders:
            continue
        total_days = sum((o.get("DurationMs") or float("inf")) for o in orders) / DAY_MS
        cap = line.get("Capacity") or 0
        b = res.setdefault(line["SiteId"], {})
        for o in orders:
            for x in o.get("Outputs") or []:
                add(b, x["MaterialTicker"], "out", x["MaterialAmount"] * cap / total_days)
            for x in o.get("Inputs") or []:
                add(b, x["MaterialTicker"], "in", x["MaterialAmount"] * cap / total_days)
    return res


def workforce_real(wf_sites):
    res = {}
    for s in wf_sites:
        b = res.setdefault(s["SiteId"], {})
        for t in s.get("Workforces") or []:
            if (t.get("Population") or 0) <= 1 or (t.get("Capacity") or 0) == 0:
                continue
            for n in t.get("WorkforceNeeds") or []:
                add(b, n["MaterialTicker"], "wf", n.get("UnitsPerInterval") or 0.0)
    return res


def workforce_calc(sites, buildings, needs):
    """The workers the buildings require x needs per 100 workers per day."""
    res = {}
    for s in sites:
        req = {tier: 0 for _, tier in TIERS}
        for bl in s.get("Buildings") or []:
            spec = buildings.get(bl.get("BuildingTicker"))
            if not spec:
                continue
            for field, tier in TIERS:
                req[tier] += spec.get(field) or 0
        b = res.setdefault(s["SiteId"], {})
        for tier, n in req.items():
            if n <= 1:
                continue
            for ticker, per100 in needs.get(tier, {}).items():
                add(b, ticker, "wf", n * per100 / 100.0)
    return res


def main():
    out_path = sys.argv[1]
    key = os.environ["FIO_KEY"]
    group = os.environ.get("FIO_GROUP", "84306218")

    st, grp = get(f"/auth/group/{group}", key)
    if st != 200 or not grp:
        sys.exit(f"group {group}: FIO answered {st}")
    _, bl = get("/building/allbuildings")
    _, mats = get("/material/allmaterials")
    buildings = {b["Ticker"]: b for b in (bl or [])}
    materials = {m["Ticker"]: {"name": m.get("Name"), "cat": m.get("CategoryName")} for m in (mats or [])}

    members, raw = [], {}
    for u in grp.get("GroupUsers") or []:
        name = u.get("GroupUserName")
        r = {}
        for ep in ("sites", "production", "workforce"):
            r[ep + "_status"], r[ep] = get(f"/{ep}/{name}", key)
        raw[name] = r

    # the needs per 100 workers of every tier, from whatever workforce the group shares; luxury = not essential
    needs, luxury = {}, set()
    for r in raw.values():
        for s in r.get("workforce") or []:
            for t in s.get("Workforces") or []:
                for n in t.get("WorkforceNeeds") or []:
                    needs.setdefault(t["WorkforceTypeName"], {})[n["MaterialTicker"]] = n.get("UnitsPerOneHundred") or 0.0
                    if not n.get("Essential"):
                        luxury.add(n["MaterialTicker"])

    data = {}
    for name, r in raw.items():
        sites = r.get("sites") or []
        # FIO keeps the production lines and the workforce of bases the member no longer has (records
        # from 2022-2025 next to a /sites from today) - with a /sites, only its bases count
        if sites:
            live = {s["SiteId"] for s in sites}
            dropped = {rec.get("PlanetName") for ep in ("production", "workforce")
                       for rec in (r.get(ep) or []) if rec["SiteId"] not in live}
            for ep in ("production", "workforce"):
                if r.get(ep) is not None:
                    r[ep] = [rec for rec in r[ep] if rec["SiteId"] in live]
            r["dropped"] = sorted(x for x in dropped if x)
        # FIO's /sites can miss bases the production lines and the workforce still have - their names
        # come with those records too
        site_name = {}
        for rec in (r.get("production") or []) + (r.get("workforce") or []):
            site_name.setdefault(rec["SiteId"], rec.get("PlanetName") or rec.get("PlanetNaturalId"))
        for s in sites:
            site_name[s["SiteId"]] = s.get("PlanetName") or s.get("PlanetIdentifier")
        prod = production_burn(r.get("production") or [], sites) if r.get("production") is not None else {}
        if r.get("workforce") is not None:
            wf, wf_src = workforce_real(r["workforce"]), "fio"
        elif sites and needs:
            wf, wf_src = workforce_calc(sites, buildings, needs), "calculated"
        else:
            wf, wf_src = {}, "none"
        per_site = {}
        for src in (prod, wf):
            for sid, b in src.items():
                ps = per_site.setdefault(site_name.get(sid, sid), {})
                for t, v in b.items():
                    for f, x in v.items():
                        if x:
                            add(ps, t, f, x)
        total = {}
        for ps in per_site.values():
            for t, v in ps.items():
                for f, x in v.items():
                    add(total, t, f, x)
        members.append({
            "name": name,
            "production": "fio" if r.get("production") is not None else f"no access ({r.get('production_status')})",
            "workforce": wf_src if wf_src != "none" else f"no access ({r.get('workforce_status')})",
            "bases": len(site_name),
            "old_bases_dropped": r.get("dropped") or [],
            "updated": max([l.get("Timestamp") or "" for l in (r.get("production") or [])] or [""]) or None,
        })
        data[name] = {"total": total, "sites": per_site}

    for d in data.values():
        for bucket in [d["total"]] + list(d["sites"].values()):
            for v in bucket.values():
                for f in ("in", "out", "wf"):
                    v[f] = round(v[f], 3)
                v["net"] = round(v["out"] - v["in"] - v["wf"], 3)

    used = sorted({t for d in data.values() for t in d["total"]})
    out = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "group": group,
        "members": members,
        "materials": {t: dict(materials.get(t, {}), luxury=t in luxury) for t in used},
        "data": data,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{out_path}: {len(members)} members, {len(used)} materials")


if __name__ == "__main__":
    main()
