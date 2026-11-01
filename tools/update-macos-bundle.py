"""Copy this checkout into an app bundle py2app already built (macOS CI).

py2app is the slow part of a macOS build and almost none of it depends on our
own sources: it packages the interpreter, pyobjc, pywebview and the boot stub,
which only change when a dependency does. ``build-macos.sh`` therefore restores
the ``Kotassium.app`` the previous run produced (cached on ``setup-macos.py``,
``requirements-macos-build.txt`` and ``setup.sh``) and calls this to replace
everything that came from *this* commit - our modules, the page, the assets,
the icon and the version stamp - before the bundle is re-signed.

It refuses rather than guesses. If the restored bundle is not laid out the way
py2app leaves ours, it exits 3 and ``build-macos.sh`` falls back to a full
py2app build, which is slower but cannot ship a half-updated app.

The last thing it does is prove it: every module it copied is compared byte for
byte against the checkout, so a partial copy fails here rather than in the
smoke test further down.
"""

import argparse
import filecmp
import os
import plistlib
import shutil
import sys

REFUSE = 3
"""Exit code meaning "not a bundle I recognise"; build-macos.sh rebuilds."""


def refuse(reason):
    print("cannot reuse the cached bundle: %s" % reason, file=sys.stderr)
    return REFUSE


def find_libdir(resources, depth=3):
    """The directory py2app puts our top-level modules in, if it is still there."""
    for root, dirs, names in os.walk(resources):
        if root[len(resources):].count(os.sep) >= depth:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        if "desktop.py" in names and "serve_web.py" in names:
            return root
    return None


def copy_paths(source, target):
    if os.path.isdir(source):
        if os.path.isdir(target):
            shutil.rmtree(target)
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--app", help="the bundle to update (default: dist/Kotassium.app)")
    parser.add_argument("--root", help="the checkout to copy from (default: this repo)")
    parser.add_argument("--version", default=os.environ.get("KOTASSIUM_VERSION"))
    args = parser.parse_args(argv)

    root = os.path.abspath(args.root or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    app = os.path.abspath(args.app or os.path.join(root, "dist", "Kotassium.app"))
    resources = os.path.join(app, "Contents", "Resources")

    if not os.path.isdir(resources):
        return refuse("no Contents/Resources in %s" % app)
    libdir = find_libdir(resources)
    if not libdir:
        return refuse("no directory in the bundle holds desktop.py and serve_web.py")

    modules = sorted(name for name in os.listdir(root)
                     if name.endswith(".py") and os.path.isfile(os.path.join(root, name)))
    if "desktop.py" not in modules or "serve_web.py" not in modules:
        return refuse("the checkout is missing desktop.py or serve_web.py")

    for name in modules:
        target = os.path.join(libdir, name)
        copy_paths(os.path.join(root, name), target)
        if not filecmp.cmp(os.path.join(root, name), target, shallow=False):
            return refuse("%s did not copy cleanly" % name)

    for tree in ("web", "assets"):
        source = os.path.join(root, tree)
        if not os.path.isdir(source):
            return refuse("the checkout has no %s/ directory" % tree)
        copy_paths(source, os.path.join(resources, tree))

    icon = os.path.join(root, "web", "icons", "kotassium.icns")
    if os.path.isfile(icon):
        shutil.copy2(icon, os.path.join(resources, "kotassium.icns"))

    if args.version:
        info = os.path.join(app, "Contents", "Info.plist")
        with open(info, "rb") as handle:
            plist = plistlib.load(handle)
        plist["CFBundleShortVersionString"] = args.version
        plist["CFBundleVersion"] = args.version
        with open(info, "wb") as handle:
            plistlib.dump(plist, handle, fmt=plistlib.FMT_BINARY)

    print("reused the bundle: %d modules, web/, assets/%s" % (
        len(modules), ", version %s" % args.version if args.version else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
