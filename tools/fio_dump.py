"""Сваля суровите данни на групата SNF от FIO в папка (за проучване на структурата).

python fio_dump.py <папка> ; ключът - от env FIO_KEY, групата - FIO_GROUP (по подразбиране 84306218).
"""
import json
import os
import sys
import urllib.request
import urllib.error

API = "https://rest.fnar.net"


def get(path, key):
    req = urllib.request.Request(API + path, headers={"Authorization": key, "accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        return e.code, None


def main():
    out = sys.argv[1]
    key = os.environ["FIO_KEY"]
    group = os.environ.get("FIO_GROUP", "84306218")
    os.makedirs(out, exist_ok=True)
    st, grp = get(f"/auth/group/{group}", key)
    print("group", st)
    json.dump(grp, open(os.path.join(out, "group.json"), "w", encoding="utf-8"), indent=1)
    users = [u.get("GroupUserName") for u in (grp or {}).get("GroupUsers", [])]
    print("members", users)
    for u in users:
        for ep in ("production", "workforce", "sites", "storage"):
            st, data = get(f"/{ep}/{u}", key)
            print(u, ep, st, (len(data) if isinstance(data, list) else type(data).__name__))
            if data is not None:
                json.dump(data, open(os.path.join(out, f"{u}_{ep}.json"), "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
