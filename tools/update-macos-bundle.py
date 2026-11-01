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
import zipfile

REFUSE = 3
"""Exit code meaning "not a bundle I recognise"; build-macos.sh rebuilds."""


def refuse(reason):
    print("cannot reuse the cached bundle: %s" % reason, file=sys.stderr)
    return REFUSE


MODULES = ("desktop.py", "serve_web.py")


def find_module_home(resources, depth=4):
    """Where py2app left our top-level modules: ("dir", path) or ("zip", path).

    It depends on the py2app version and its zipfile option, which this repo has
    set both ways over time, so both shapes are accepted. Nothing is assumed
    about where the modules are beyond the fact that the bundle put them
    somewhere findable.
    """
    loose = []
    compacted = []
    for root, dirs, names in os.walk(resources):
        if root[len(resources):].count(os.sep) >= depth:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        if all(name in names for name in MODULES):
            return "dir", root
        loose.extend(os.path.join(root, name) for name in names if name.endswith(".py"))
        for name in names:
            if name.endswith(".zip"):
                path = os.path.join(root, name)
                try:
                    with zipfile.ZipFile(path) as archive:
                        entries = set(archive.namelist())
                except Exception:
                    continue
                if all(name in entries for name in MODULES):
                    return "zip", path
                if any(name.endswith(".py") for name in entries):
                    compacted.append(path)

    print("the bundle's python files are at:", file=sys.stderr)
    for path in loose[:10]:
        print("  " + path, file=sys.stderr)
    for path in compacted[:10]:
        print("  " + path + " (zip, no desktop.py)", file=sys.stderr)
    return None, None


def replace_in_zip(path, files):
    """Rewrite the members we own, leaving every other entry untouched.

    A stale ``__pycache__``-style entry next to a replaced source would be
    preferred by zipimport when its header matches, so those go with it.
    """
    replaced = path + ".new"
    stale = {os.path.splitext(name)[0] + ".pyc" for name in files}
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(replaced, "w") as target:
        for item in source.infolist():
            if item.filename in files:
                target.writestr(item, files[item.filename])
            elif item.filename in stale:
                continue
            else:
                target.writestr(item, source.read(item.filename))
    os.replace(replaced, path)

    with zipfile.ZipFile(path) as archive:
        for name, data in files.items():
            if archive.read(name) != data:
                return False
    return True


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
    kind, home = find_module_home(resources)
    if not kind:
        return refuse("no directory or archive in the bundle holds our modules")

    modules = sorted(name for name in os.listdir(root)
                     if name.endswith(".py") and os.path.isfile(os.path.join(root, name)))
    if not all(name in modules for name in MODULES):
        return refuse("the checkout is missing desktop.py or serve_web.py")

    if kind == "dir":
        for name in modules:
            target = os.path.join(home, name)
            copy_paths(os.path.join(root, name), target)
            if not filecmp.cmp(os.path.join(root, name), target, shallow=False):
                return refuse("%s did not copy cleanly" % name)
    elif not replace_in_zip(home, {
            name: open(os.path.join(root, name), "rb").read() for name in modules}):
        return refuse("the module archive did not take the new sources")

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

    print("reused the bundle: %d modules in a %s, web/, assets/%s" % (
        len(modules), "directory" if kind == "dir" else "zip",
        ", version %s" % args.version if args.version else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
