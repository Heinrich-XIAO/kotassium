#!/usr/bin/env python3
"""Print the next auto-release version.

Every push to main ships a release, so the version has to be derived from
what is already published: take the newest vX.Y.Z tag and bump the patch.
Tags that are not plain X.Y.Z (release candidates, build numbers) are
ignored so they cannot poison the bump.

    python3 .github/next_version.py            # uses the local git tags
    python3 .github/next_version.py v2.3.2 ... # uses the given tags
"""
import os
import re
import subprocess
import sys

TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def next_version(tags):
    """The next version after the highest plain vX.Y.Z in tags."""
    best = None
    for tag in tags:
        m = TAG_RE.match(str(tag).strip())
        if not m:
            continue
        v = tuple(int(x) for x in m.groups())
        if best is None or v > best:
            best = v
    if best is None:
        return "0.0.1"
    return "%d.%d.%d" % (best[0], best[1], best[2] + 1)


def local_tags():
    """Local v* tags, newest first."""
    out = subprocess.run(["git", "tag", "--list", "v*", "--sort=-v:refname"],
                         capture_output=True, text=True, check=True).stdout
    return out.split()


def main(argv):
    tags = argv[1:] or local_tags()
    print(next_version(tags))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
