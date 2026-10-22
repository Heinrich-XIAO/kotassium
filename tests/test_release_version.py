import importlib.util
import os
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(_ROOT, ".github", "next_version.py")

_spec = importlib.util.spec_from_file_location("next_version", _SCRIPT)
next_version = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(next_version)


class NextVersionTests(unittest.TestCase):
    """The auto-release version is the patch bump of the newest published
    tag. A wrong bump publishes a version the desktop app will not offer as
    an update (the updater compares the tag with the baked version), or one
    that collides with an existing tag."""

    def test_bumps_the_patch(self):
        self.assertEqual(next_version.next_version(["v2.3.2"]), "2.3.3")

    def test_uses_the_newest_tag_not_the_last_one(self):
        self.assertEqual(next_version.next_version(["v2.3.2", "v2.9.0", "v2.4.1"]), "2.9.1")

    def test_ignores_tags_that_are_not_plain_versions(self):
        tags = ["v2.4.0-rc1", "v2.3.9", "v2.4"]
        self.assertEqual(next_version.next_version(tags), "2.3.10")

    def test_ignores_prerelease_tags_entirely(self):
        self.assertEqual(next_version.next_version(["v3.0.0-beta.1"]), "0.0.1")

    def test_starts_at_zero_when_there_are_no_tags(self):
        self.assertEqual(next_version.next_version([]), "0.0.1")
        self.assertEqual(next_version.next_version(["not-a-tag"]), "0.0.1")

    def test_keeps_the_major_and_minor(self):
        self.assertEqual(next_version.next_version(["v10.4.9"]), "10.4.10")

    def test_result_is_always_three_numeric_parts(self):
        for tags in ([], ["v1.0.0"], ["v0.9.99"], ["v2.3.2", "v2.3.3"]):
            v = next_version.next_version(tags)
            parts = v.split(".")
            self.assertEqual(len(parts), 3)
            self.assertTrue(all(p.isdigit() for p in parts))


class LocalTagsTests(unittest.TestCase):
    def test_local_tags_are_version_sorted(self):
        tags = next_version.local_tags()
        if not tags:
            self.skipTest("no tags in this checkout")
        # newest first
        self.assertEqual(tags[0], max(tags, key=_version_key))


def _version_key(tag):
    import re
    m = re.match(r"^v(\d+)\.(\d+)\.(\d+)$", tag)
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


if __name__ == "__main__":
    unittest.main()
