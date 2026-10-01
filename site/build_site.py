"""Inline the five-season payload + league totals into the Never Lucky page.

    python build_site.py                      # writes site/never_lucky_five_seasons.html (git-ignored)
    python build_site.py --out site.html      # standalone page somewhere else
    python build_site.py --artifact body.html # also write the doctype-less body for publishing

The standalone file opens straight from disk; only the Google Fonts load from the web.
"""
import argparse
import json
from pathlib import Path

here = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--out", type=Path, default=here / "never_lucky_five_seasons.html")
ap.add_argument("--artifact", type=Path, default=None)
args = ap.parse_args()

tpl = (here / "nl_template.html").read_text(encoding="utf-8")
payload = (here / "payload.json").read_text(encoding="utf-8")
league = json.dumps(json.loads((here / "league.json").read_text(encoding="utf-8")), separators=(",", ":"))
safe = lambda s: s.replace("</", "<" + chr(92) + "/")  # never let data close the <script> early
body = tpl.replace("/*__PAYLOAD__*/null", safe(payload)).replace("/*__LEAGUE__*/null", safe(league))
if args.artifact:
    args.artifact.write_text(body, encoding="utf-8")
    print("artifact", args.artifact, args.artifact.stat().st_size)
standalone = ('<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
              '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
              + body.replace('<div class="scan"', '</head>\n<body>\n<div class="scan"', 1) + "\n</body>\n</html>\n")
args.out.write_text(standalone, encoding="utf-8")
print("standalone", args.out, args.out.stat().st_size)
