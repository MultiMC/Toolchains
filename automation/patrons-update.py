#!/usr/bin/env python3
"""Make a new patrons.txt (the Launcher's Patreon credits) as a release.

    patrons-update.py [--config FILE]

Asks Patreon's API (v2; v1, which TeamCity's patronupdater.py used, is gone since
2026-10-08) for the campaign's members, and lists the active patrons entitled to the tier
in tokens.cfg ([Config] reward), sorted by name, followed by a line counting the active
patrons without a tier ("And N others who wish to remain anonymous."). patrons.json has
the credited patrons with their image and Patreon URLs. Then deploy.py and publish.py put
patrons.txt live, like any release (hopper runs all three on PATRONS_SCHEDULE).

The token file is PATRONS_CONFIG/tokens.cfg ([Keys] clientid, clientsecret, refreshtoken,
accesstoken), on one machine only (empty PATRONS_CONFIG, as for files2: refused). Every
run first refreshes the token: Patreon then issues a new refresh token and the old one
stops working, so the new pair is saved (atomically, the previous file kept as
tokens.cfg.prev) before anything else is asked. One run at a time.

The result is checked before it can be released: patrons.txt must not be empty, and not
less than half as long as the one in the files tree. Otherwise nothing is released and
the old list stays live.

The release goes into RELEASES_DIR/patrons-<time>/ (patrons.txt, patrons.json,
manifest.json). Standard output gets one line, the release directory.
"""

import argparse
import configparser
import json
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import common

log = common.logger("patrons")

API = "https://www.patreon.com/api/oauth2"
USER_AGENT = "MultiMC patrons-update"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", help="settings file overriding defaults.env")
    args = parser.parse_args()
    common.stop_on_sigterm()

    settings = common.load_settings(args.config)
    if not settings["PATRONS_CONFIG"]:
        common.die("PATRONS_CONFIG is empty: the Patreon credits aren't made with these settings")
    tokens = Path(settings["PATRONS_CONFIG"]) / "tokens.cfg"
    if not tokens.is_file():
        common.die("no Patreon token file at %s" % tokens)
    previous = Path(settings["FILES_ROOT"]) / "patrons.txt"

    with common.locked(str(tokens) + ".lock", "the Patreon token is in use by another run"):
        out = Path(settings["RELEASES_DIR"]) / ("patrons-%s" % time.strftime("%Y%m%d-%H%M%S"))
        out.mkdir(parents=True)
        print(out, flush=True)
        log("release directory %s" % out)

        config = configparser.RawConfigParser()
        config.read(tokens)
        access_token = refresh_token(config, tokens)
        credited, anonymous = patrons(access_token, config["Config"]["reward"])
        write_lists(out, credited, anonymous)

        problem = check(out / "patrons.txt", previous)
        manifest = {"kind": "patrons", "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "files": ["patrons.txt"], "releasable": problem is None, "problem": problem,
                    "credited": len(credited), "anonymous": anonymous}
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    if problem:
        common.die(problem)
    log("releasable: %d credited, %d anonymous" % (len(credited), anonymous))


def request(url, data=None, token=None):
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = urllib.parse.urlencode(data).encode() if data else None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        common.die("Patreon answered %d to %s: %s" % (e.code, url.split("?")[0], detail))
    except urllib.error.URLError as e:
        common.die("can't reach Patreon: %s" % e.reason)


def refresh_token(config, tokens):
    """Refresh the token and save the new pair before anything else; returns the access token."""
    keys = config["Keys"]
    log("refreshing the Patreon token")
    answer = request(API + "/token", data={"grant_type": "refresh_token", "refresh_token": keys["refreshtoken"],
                                           "client_id": keys["clientid"], "client_secret": keys["clientsecret"]})
    keys["accesstoken"], keys["refreshtoken"] = answer["access_token"], answer["refresh_token"]
    shutil.copy2(tokens, str(tokens) + ".prev")
    new = Path(str(tokens) + ".new")
    with open(os.open(new, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        config.write(f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(new, tokens)
    log("new token saved")
    return answer["access_token"]


def patrons(token, tier):
    """(credited patrons, number of anonymous patrons): active patrons entitled to `tier`, and
    active patrons without any tier. Free followers aren't patrons and aren't counted."""
    campaigns = request(API + "/v2/campaigns", token=token)["data"]
    if len(campaigns) != 1:
        common.die("expected one campaign, Patreon lists %d" % len(campaigns))
    url = (API + "/v2/campaigns/%s/members?" % campaigns[0]["id"] + urllib.parse.urlencode({
        "include": "currently_entitled_tiers,user",
        "fields[member]": "full_name,patron_status",
        "fields[user]": "full_name,thumb_url,url",
        "page[count]": "1000",
    }))
    credited, anonymous = [], 0
    while url:
        page = request(url, token=token)
        users = {u["id"]: u["attributes"] for u in page.get("included", []) if u["type"] == "user"}
        for member in page["data"]:
            if member["attributes"].get("patron_status") != "active_patron":
                continue
            tiers = {t["id"] for t in member["relationships"]["currently_entitled_tiers"]["data"]}
            if tier in tiers:
                user = users.get(member["relationships"]["user"]["data"]["id"], {})
                credited.append({"name": user.get("full_name") or member["attributes"]["full_name"],
                                 "thumb_url": user.get("thumb_url") or "", "url": user.get("url") or ""})
            elif not tiers:
                anonymous += 1
        url = page.get("links", {}).get("next")
    credited.sort(key=lambda p: p["name"].lower())
    return credited, anonymous


def write_lists(out, credited, anonymous):
    """patrons.txt (one name per line, then the anonymous count) and patrons.json, in the
    formats patronupdater.py wrote."""
    lines = [p["name"] for p in credited]
    if anonymous > 1:
        lines.append("And %d others who wish to remain anonymous." % anonymous)
    elif anonymous == 1:
        lines.append("And one other who wishes to remain anonymous.")
    (out / "patrons.txt").write_text("\n".join(lines), encoding="utf-8")

    entries = [{"name": p["name"],
                "image_url": p["thumb_url"] if p["thumb_url"].startswith("http") else "https:" + p["thumb_url"],
                "patreon_url": p["url"]} for p in credited]
    (out / "patrons.json").write_text(json.dumps(entries, separators=(",", ":")), encoding="utf-8")


def check(patrons_txt, previous):
    """None if patrons.txt can be released; otherwise what's wrong with it."""
    lines = [line for line in patrons_txt.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return "the new patrons.txt is empty; not releasing it"
    if previous.is_file():
        before = [line for line in previous.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(lines) * 2 < len(before):
            return ("the new patrons.txt has %d lines, the current one %d: less than half; not releasing it"
                    % (len(lines), len(before)))
    return None


if __name__ == "__main__":
    main()
