"""Copy this checkout into an app bundle py2app already built (macOS CI).

py2app is the slow part of a macOS build and almost none of it depends on our
own sources: it packages the interpreter, pyobjc, pywebview and the boot stub,
which only change when a dependency does. ``build-macos.sh`` therefore restores
the ``Kotassium.app`` the previous run produced (cached on ``setup-macos.py``,
``requirements-macos-build.txt`` and ``setup.sh``) and calls this to replace
everything that came from *this* commit - our modules, the page, the assets,
the icon and the version stamp - before the bundle is re-signed.

The modules to replace are read out of ``setup-macos.py`` rather than guessed:
its ``APP`` and ``includes`` are exactly what py2app was told to bundle, so a
module added there is a module this looks for. ``py2app`` scatters them - the
app script lands at ``Contents/Resources/``, the includes under
``lib/python3.x/``, and in some versions they are inside a zip - so each one is
located by name, wherever it is.

It refuses rather than guesses. A module in the manifest that the bundle does
not contain means the cache predates that module, and a bundle laid out in a
way this does not recognise means the fast path is not safe: both exit 3 and
``build-macos.sh`` falls back to a full py2app build, which is slower but
cannot ship a half-updated app.

The last thing it does is prove it: every module it wrote is compared byte for
byte against the checkout, so a partial copy fails here rather than in the
smoke test further down.
"""

import argparse
import ast
import os
import plistlib
import shutil
import sys
import zipfile

REFUSE = 3
"""Exit code meaning "not a bundle I recognise"; build-macos.sh rebuilds."""

MAX_DEPTH = 5


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


def locate(resources, wanted):
    """Map each wanted module to ("dir", path) or ("zip", path, member)."""
    found = {}
    for root, dirs, names in os.walk(resources):
        if root[len(resources):].count(os.sep) >= MAX_DEPTH:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in names:
            if name in wanted and name not in found:
                found[name] = ("dir", os.path.join(root, name))
        for name in names:
            if not name.endswith(".zip") or all(entry in found for entry in wanted):
                continue
            path = os.path.join(root, name)
            try:
                with zipfile.ZipFile(path) as archive:
                    entries = set(archive.namelist())
            except Exception:
                continue
            for entry in wanted:
                if entry in entries and entry not in found:
                    found[entry] = ("zip", path, entry)
    return found


def replace_in_zip(path, members):
    """Rewrite the members we own, leaving every other entry untouched."""
    replaced = path + ".new"
    stale = {os.path.splitext(name)[0] + ".pyc" for name in members}
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(replaced, "w") as target:
        for item in source.infolist():
            if item.filename in members:
                target.writestr(item, members[item.filename])
            elif item.filename in stale:
                # zipimport prefers bytecode whose header matches; a compiled
                # copy of the old source must go with the source it came from.
                continue
            else:
                target.writestr(item, source.read(item.filename))
    os.replace(replaced, path)

    with zipfile.ZipFile(path) as archive:
        return all(archive.read(name) == data for name, data in members.items())


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
    sources = {name: open(os.path.join(root, name), "rb").read() for name in wanted}

    located = locate(resources, set(wanted))
    missing = [name for name in wanted if name not in located]
    if missing:
        return refuse("the bundle has no %s" % ", ".join(sorted(missing)))

    by_dir, by_zip = {}, {}
    for name, where in located.items():
        if where[0] == "dir":
            by_dir.setdefault(os.path.dirname(where[1]), []).append(name)
        else:
            by_zip.setdefault(where[1], {})[where[2]] = sources[name]

    for directory, names in by_dir.items():
        for name in names:
            shutil.copy2(os.path.join(root, name), os.path.join(directory, name))
            with open(os.path.join(root, name), "rb") as wanted_file:
                with open(os.path.join(directory, name), "rb") as copied:
                    if wanted_file.read() != copied.read():
                        return refuse("%s did not copy cleanly" % name)
    for archive, members in by_zip.items():
        if not replace_in_zip(archive, members):
            return refuse("%s did not take the new sources" % os.path.basename(archive))

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

    print("reused the bundle: %d modules (%s), web/, assets/%s" % (
        len(wanted),
        "zipped" if by_zip else "loose",
        ", version %s" % args.version if args.version else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
