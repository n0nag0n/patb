import unittest

from patb.frontmatter import FrontmatterError, dump, parse


class FrontmatterTest(unittest.TestCase):
    def test_roundtrip(self):
        meta = {
            "key": "email.usps",
            "kind": "policy",
            "aliases": ["usps", "informed delivery"],
            "tags": ["silent-delete"],
            "importance": 1.0,
            "approval": "none",
        }
        body = "Trash USPS. Do not mention it.\n"
        text = dump(meta, body)
        got, got_body = parse(text)
        self.assertEqual(got["key"], "email.usps")
        self.assertEqual(got["aliases"], ["usps", "informed delivery"])
        self.assertEqual(got["tags"], ["silent-delete"])
        self.assertEqual(got_body, body)

    def test_unclosed(self):
        with self.assertRaises(FrontmatterError):
            parse("---\nkey: x\n")

    def test_bool_and_list(self):
        text = "---\nkey: a\nkind: policy\naliases: [one, two]\n---\nHi\n"
        meta, body = parse(text)
        self.assertEqual(meta["aliases"], ["one", "two"])
        self.assertEqual(body, "Hi\n")


if __name__ == "__main__":
    unittest.main()
