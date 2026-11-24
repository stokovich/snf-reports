"""Members who do not share their data in FIO: their daily in/out from the corp's coordination sheet.

The sheet (a Google Sheet shared by link; its id comes from env CORP_SHEET_ID, never from the code) has, per
player and base, the production recipes with their load and the cycles per day it works out
("V2.1 - Production Ledger Helper 1"), the outputs per day ("V2.1 Production Outputs") and the buildings of
every base ("Co-ord V2 - Player Bases"). From them:
  out - the sheet's own outputs per day,
  in  - cycles per day x the inputs of the recipe (FIO's recipe list; the sheet's key is BUILDING-outputs[-inputs]
        with the outputs in any order and the inputs possibly a subset),
  wf  - the workers the buildings require x the needs per 100 workers of the tier (as for FIO members).
These are the planned numbers the player entered (load, efficiency assumed by the sheet), not the live game.
"""
import csv
import io
import re
import urllib.request

TABS = {"helper": 816989300, "outputs": 1259933106, "bases": 368761835}
TIERS = [("Pioneers", "PIONEER"), ("Settlers", "SETTLER"), ("Technicians", "TECHNICIAN"),
         ("Engineers", "ENGINEER"), ("Scientists", "SCIENTIST")]


def fetch_tab(sheet_id, gid):
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&gid={gid}"
    with urllib.request.urlopen(url, timeout=120) as r:
        return list(csv.reader(io.StringIO(r.read().decode("utf-8"))))


def num(s):
    s = (s or "").replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def match_recipe(key, recipes, out_by_mat, cycles):
    """The FIO recipe a sheet key means. Tokens after the building: the first k are the outputs (any order), the
    rest a subset of the inputs. Several candidates - the one whose output x cycles is closest to the sheet's; with
    the same outputs, the one with the fewest inputs the key does not name: the sheet names the extra inputs
    (INC-C-HCP is 4 HCP, INC-C-HCP-MAI and INC-C-GRN-HCP-MAI are the recipes with maize and grain)."""
    parts = key.split("-")
    bld, toks = parts[0], parts[1:]
    cands = []
    for rec in recipes.get(bld, []):
        outs = {x["Ticker"] for x in rec["Outputs"]}
        ins = {x["Ticker"] for x in rec["Inputs"]}
        for k in range(1, len(toks) + 1):
            if set(toks[:k]) <= outs and set(toks[k:]) <= ins and (k == len(toks) or set(toks[:k]) == outs):
                cands.append(rec)
                break
    if len(cands) <= 1:
        return cands[0] if cands else None

    def err(rec):
        e = 0.0
        for x in rec["Outputs"]:
            want = out_by_mat.get(x["Ticker"])
            e += abs((want if want is not None else 0) - x["Amount"] * cycles)
        return round(e, 3)

    def unnamed(rec):
        return len({x["Ticker"] for x in rec["Inputs"]} - set(toks))
    return min(cands, key=lambda rec: (err(rec), unnamed(rec)))


def members_from_sheet(sheet_id, names, recipes_list, buildings, needs, display_name):
    """{name: {"sites": {base: {ticker: {in, out, wf}}}, "bases": n, "unmatched": [keys]}}"""
    tabs = {k: fetch_tab(sheet_id, g) for k, g in TABS.items()}
    recipes = {}
    for rec in recipes_list:
        recipes.setdefault(rec["BuildingTicker"], []).append(rec)
    want = {n.lower(): n for n in names}
    res = {n: {"sites": {}, "bases": 0, "unmatched": []} for n in names}

    def bucket(name, base):
        return res[name]["sites"].setdefault(base, {})

    def add(b, t, f, v):
        row = b.setdefault(t, {"in": 0.0, "out": 0.0, "wf": 0.0})
        row[f] += v

    # outputs per day, by (player, planet id)
    head, *rows = tabs["outputs"]
    outs = {}
    for r in rows:
        u, pid, mat, amt = (r + ["", "", "", ""])[:4]
        if u.strip().lower() in want and mat:
            outs.setdefault((want[u.strip().lower()], pid.strip()), {}).setdefault(mat.strip(), 0.0)
            outs[(want[u.strip().lower()], pid.strip())][mat.strip()] += num(amt)

    # the bases: planet name, natural id (last column), buildings by column header
    head, *rows = tabs["bases"]
    cols = [re.sub(r"^(Buildings|Active Experts)\s+", "", h).split()[0] if h.strip() else "" for h in head]
    names_by_pid = {}
    for r in rows:
        if not r or r[0].strip().lower() not in want:
            continue
        name = want[r[0].strip().lower()]
        pid = r[-1].strip()
        if not pid:
            continue   # the empty rows the sheet keeps for new bases
        base = display_name(r[1].strip() or pid)
        names_by_pid[(name, pid)] = base
        res[name]["bases"] += 1
        req = {tier: 0 for _, tier in TIERS}
        for i, c in enumerate(cols[4:], start=4):
            if c in buildings and i < len(r) and num(r[i]) > 0 and c not in ("RES", "MANU", "AGRI"):
                for field, tier in TIERS:
                    req[tier] += num(r[i]) * (buildings[c].get(field) or 0)
        b = bucket(name, base)
        for tier, n in req.items():
            if n <= 1:
                continue
            for ticker, per100 in needs.get(tier, {}).items():
                add(b, ticker, "wf", n * per100 / 100.0)

    # production: the sheet's outputs; inputs = cycles x recipe inputs
    for (name, pid), mats in outs.items():
        b = bucket(name, names_by_pid.get((name, pid), display_name(pid)))
        for t, v in mats.items():
            if v:
                add(b, t, "out", v)
    head, *rows = tabs["helper"]
    for r in rows:
        if len(r) < 13 or r[0].strip().lower() not in want:
            continue
        name = want[r[0].strip().lower()]
        key, pid, cycles = r[2].strip(), r[5].strip(), num(r[12])
        if not key or cycles <= 0 or key.split("-")[0] in ("EXT", "COL", "RIG"):
            continue
        rec = match_recipe(key, recipes, outs.get((name, pid), {}), cycles)
        if not rec:
            res[name]["unmatched"].append(key)
            continue
        b = bucket(name, names_by_pid.get((name, pid), display_name(pid)))
        for x in rec["Inputs"]:
            add(b, x["Ticker"], "in", x["Amount"] * cycles)
    return res
