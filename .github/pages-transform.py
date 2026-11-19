#!/usr/bin/env python3
# Staging-only serve-time transform for the GitHub Pages artifact.
#
# WHY: the committed HTML is the pristine production (--prod) build -- real www.* canonical,
# no robots noindex, an indexable robots.txt + sitemap. Served unchanged on the *-stage.github.io
# preview domain it would get indexed. This step transforms ONLY the built _site artifact in CI
# (never the committed HTML), so the stage mirror stays out of search indexes regardless of which
# build mode produced the commit.
#
# Mode is ALWAYS explicit (transform | verify); a bare invocation is a usage error -- the
# transform must never run by accident. Invoked via its shebang (chmod +x), never `python3 <this>`.
# stdlib only.

import argparse
import os
import re
import sys
from pathlib import Path

# The one directive that actually keeps a page out of the index (robots.txt Disallow cannot).
# nofollow matches the generator's own --stage convention (do not crawl the stage link graph).
ROBOTS_CONTENT = "noindex,nofollow"
ROBOTS_META = '<meta name="robots" content="%s">' % ROBOTS_CONTENT

# A <meta name="robots" ...> whose content is captured in group 2 (name before content, which is
# how the generator emits it, e.g. the --prod `max-image-preview:large`).
_RE_ROBOTS = re.compile(
    r'(<meta\b[^>]*\bname="robots"[^>]*\bcontent=")([^"]*)(")', re.IGNORECASE)
# The opening <head ...> tag (attributes allowed); insertion seam when no robots meta exists.
_RE_HEAD = re.compile(r'(<head\b[^>]*>)', re.IGNORECASE)
_RE_HTML = re.compile(r'(<html\b[^>]*>)', re.IGNORECASE)
# The origin (scheme://host) of the content URL in an og:image / twitter:image meta. property/name
# precede content (generator order); only the origin is rewritten, the path is kept.
_RE_CARD_ORIGIN = re.compile(
    r'(<meta\b[^>]*?(?:property="og:image"|name="twitter:image")[^>]*?content=")'
    r'https?://[^/"]+', re.IGNORECASE)


def stage_host(explicit):
    """The host the artifact is served at: the <name>.github.io Pages repo name."""
    if explicit:
        return explicit
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        return repo.split("/", 1)[1]
    raise SystemExit(
        "pages-transform: cannot determine stage host -- set GITHUB_REPOSITORY "
        "(owner/<name>.github.io) or pass --stage-host")


def set_robots_noindex(html):
    """Force exactly one robots meta of ROBOTS_CONTENT. Replace any existing robots meta(s);
    if none, insert after <head> (fallback: after <html>, else prepend). Idempotent."""
    new, n = _RE_ROBOTS.subn(lambda m: m.group(1) + ROBOTS_CONTENT + m.group(3), html)
    if n:
        return new
    inject = "\\1\n" + ROBOTS_META
    new, n = _RE_HEAD.subn(inject, html, count=1)
    if n:
        return new
    new, n = _RE_HTML.subn(inject, html, count=1)
    if n:
        return new
    return ROBOTS_META + "\n" + html


def rewrite_card_hosts(html, host):
    """Point og:image / twitter:image at the stage origin so the card media resolves on the
    served domain (the --prod build bakes www.* there, which 404s). Path kept. Idempotent."""
    return _RE_CARD_ORIGIN.sub(lambda m: m.group(1) + "https://" + host, html)


def iter_html(root):
    return sorted(p for p in root.rglob("*.html") if p.is_file())


def cmd_transform(args):
    root = Path(args.dir)
    if not root.is_dir():
        raise SystemExit("pages-transform: not a directory: %s" % root)
    host = stage_host(args.stage_host)
    changed = 0
    for path in iter_html(root):
        original = path.read_text(encoding="utf-8")
        out = rewrite_card_hosts(set_robots_noindex(original), host)
        if out != original:
            path.write_text(out, encoding="utf-8")
            changed += 1
    print("pages-transform: transformed %d file(s); stage host %s" % (changed, host))
    return 0


def cmd_verify(args):
    root = Path(args.dir)
    if not root.is_dir():
        raise SystemExit("pages-transform: not a directory: %s" % root)
    failures = []
    total = 0
    for path in iter_html(root):
        total += 1
        m = _RE_ROBOTS.search(path.read_text(encoding="utf-8"))
        if not m or "noindex" not in m.group(2).lower():
            failures.append("missing noindex robots meta: %s" % path.relative_to(root))
    robots = root / "robots.txt"
    if not robots.is_file():
        failures.append("missing robots.txt")
    elif "Disallow: /" not in robots.read_text(encoding="utf-8"):
        failures.append("robots.txt does not Disallow: /")
    if failures:
        for f in failures:
            print("pages-transform: FAIL: %s" % f, file=sys.stderr)
        print("pages-transform: verify FAILED (%d issue(s), %d html checked)"
              % (len(failures), total), file=sys.stderr)
        return 1
    print("pages-transform: verify OK (%d html noindexed, robots.txt Disallow: /)" % total)
    return 0


def main(argv):
    parser = argparse.ArgumentParser(
        prog="pages-transform", description="Staging-only serve-time transform of the _site artifact.")
    sub = parser.add_subparsers(dest="mode", required=True)
    t = sub.add_parser("transform", help="inject noindex + rewrite card hosts in <dir>/**/*.html")
    t.add_argument("dir", help="the built site artifact directory (e.g. _site)")
    t.add_argument("--stage-host", default=None,
                   help="override the served host (default: from GITHUB_REPOSITORY)")
    t.set_defaults(func=cmd_transform)
    v = sub.add_parser("verify", help="assert every page is noindexed and robots.txt Disallow: /")
    v.add_argument("dir", help="the built site artifact directory (e.g. _site)")
    v.set_defaults(func=cmd_verify)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
