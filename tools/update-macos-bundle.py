"""Copy this checkout into an app bundle py2app already built (macOS CI).

py2app is the slow part of a macOS build and none of it depends on our own
sources: it packages the interpreter, pyobjc, pywebview and the boot stub,
which only change when a dependency does. ``build-macos.sh`` therefore restores
the ``Kotassium.app`` the previous run produced (cached on ``setup-macos.py``,
``requirements-macos-build.txt`` and ``setup.sh``) and calls this to bring it up
to this commit - our modules, the page, the assets, the icon and the version
stamp - before the bundle is re-signed.

Where py2app *put* the modules it packaged is not something this needs to know,
and it is not something worth guessing: it keeps ``desktop.py`` loose at
``Contents/Resources/`` and compiles the ``includes`` into the bundle, so they
are not files that can simply be overwritten. Instead:

  * ``Contents/Resources/app/`` is written with this build's modules, and
    ``desktop.py`` puts that directory first on ``sys.path`` - so the copies
    py2app compiled in are shadowed rather than relocated;
  * the loose ``desktop.py``, which py2app's boot script runs by path, is
    replaced in place;
  * ``web/``, ``assets/`` and the icon are replaced whole, because the commit
    is the truth about them;
  * ``Info.plist`` is stamped with this run's version.

``desktop.py``'s ``--selftest`` reports the directory ``serve_web`` was imported
from, and CI fails the build when a reused bundle does not report ``app/`` -
shadowing is only a fast path if it is the path actually taken.

It refuses rather than guesses: no loose ``desktop.py`` means a layout this does
not understand, so it exits 3 and ``build-macos.sh`` rebuilds with py2app. Every
file it writes is compared byte for byte against the checkout afterwards.
"""

import argparse
import ast
import os
import plistlib
import shutil
import sys

REFUSE = 3
"""Exit code meaning "not a bundle I recognise"; build-macos.sh rebuilds."""

MAX_DEPTH = 4


def refuse(reason):
    print("cannot reuse the cached bundle: %s" % reason, file=sys.stderr)
    return REFUSE


def bundle_modules(root):
    """The module files py2app was told to bundle, from setup-macos.py."""
    path = os.path.join(root, "setup-macos.py")
    try:
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), path)
    except (OSError, SyntaxError) as error:
        raise SystemExit("cannot read %s: %s" % (path, error))

    app, includes = [], []

    def names(node):
        return [item.value for item in node.elts if isinstance(item, ast.Constant)]

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id == "APP" and isinstance(node.value, ast.List):
                app = names(node.value)
            if target.id == "OPTIONS" and isinstance(node.value, ast.Dict):
                for key, value in zip(node.value.keys, node.value.values):
                    if isinstance(key, ast.Constant) and key.value == "includes" \
                            and isinstance(value, ast.List):
                        includes = names(value)
    if not app:
        raise SystemExit("setup-macos.py has no APP list")
    # APP entries are script paths ("desktop.py"); includes are module names.
    return [name if name.endswith(".py") else "%s.py" % name for name in app + includes]


def find_file(resources, name):
    """The bundle's own copy of one file, wherever py2app left it."""
    for root, dirs, files in os.walk(resources):
        if root[len(resources):].count(os.sep) >= MAX_DEPTH:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "app")]
        if name in files:
            return os.path.join(root, name)
    return None


def same(left, right):
    with open(left, "rb") as a, open(right, "rb") as b:
        return a.read() == b.read()


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

    wanted = bundle_modules(root)
    for name in wanted:
        if not os.path.isfile(os.path.join(root, name)):
            return refuse("the checkout has no %s" % name)

    script = find_file(resources, wanted[0])
    if not script:
        return refuse("no %s for py2app's boot script to run" % wanted[0])

    fresh = os.path.join(resources, "app")
    if os.path.isdir(fresh):
        shutil.rmtree(fresh)
    os.makedirs(fresh)
    for name in wanted:
        shutil.copy2(os.path.join(root, name), os.path.join(fresh, name))
        if not same(os.path.join(root, name), os.path.join(fresh, name)):
            return refuse("%s did not copy cleanly" % name)
    # The boot script runs this one by path, so it has to be replaced where it
    # is as well as being importable from app/.
    shutil.copy2(os.path.join(root, wanted[0]), script)
    if not same(os.path.join(root, wanted[0]), script):
        return refuse("%s did not copy cleanly" % wanted[0])

    for tree in ("web", "assets"):
        source = os.path.join(root, tree)
        if not os.path.isdir(source):
            return refuse("the checkout has no %s/ directory" % tree)
        target = os.path.join(resources, tree)
        if os.path.isdir(target):
            shutil.rmtree(target)
        shutil.copytree(source, target)

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

    print("reused the bundle: %d modules shadowing py2app's copies, web/, assets/%s" % (
        len(wanted), ", version %s" % args.version if args.version else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
