import unittest

from app.utils.markdown_processor import split_markdown_advanced, split_markdown_by_h2


class TestMarkdownProcessor(unittest.TestCase):
    def test_split_markdown_no_h2(self):
        """Test splitting markdown with no h2 headers."""
        markdown = "This is a test markdown with no h2 headers."
        chunks = split_markdown_by_h2(markdown)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["index"], "START")
        self.assertEqual(chunks[0]["content"], markdown)

    def test_split_markdown_one_h2(self):
        """Test splitting markdown with one h2 header."""
        markdown = "Intro text\n\n## Header\n\nContent after header."
        chunks = split_markdown_by_h2(markdown)

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["index"], "START")
        self.assertEqual(chunks[0]["content"], "Intro text\n\n")
        self.assertEqual(chunks[1]["index"], "END")
        self.assertEqual(chunks[1]["content"], "## Header\n\nContent after header.")

    def test_split_markdown_multiple_h2(self):
        """Test splitting markdown with multiple h2 headers."""
        markdown = "Intro text\n\n## Header 1\n\nContent 1\n\n## Header 2\n\nContent 2\n\n## Header 3\n\nContent 3"
        chunks = split_markdown_by_h2(markdown)

        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0]["index"], "START")
        self.assertEqual(chunks[0]["content"], "Intro text\n\n## Header 1\n\nContent 1\n\n")
        self.assertEqual(chunks[1]["index"], "1")
        self.assertEqual(chunks[1]["content"], "## Header 2\n\nContent 2\n\n")
        self.assertEqual(chunks[2]["index"], "END")
        self.assertEqual(chunks[2]["content"], "## Header 3\n\nContent 3")

    def test_split_markdown_no_intro(self):
        """Test splitting markdown with no intro text before first h2."""
        markdown = "## Header 1\n\nContent 1\n\n## Header 2\n\nContent 2"
        chunks = split_markdown_by_h2(markdown)

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["index"], "START")
        self.assertEqual(chunks[0]["content"], "## Header 1\n\nContent 1\n\n")
        self.assertEqual(chunks[1]["index"], "END")
        self.assertEqual(chunks[1]["content"], "## Header 2\n\nContent 2")

    def test_split_markdown_advanced_zakkubaran_and_articles(self):
        markdown = (
            "# 今週のざっくばらん\n"
            "\n"
            "## トピック1\n"
            "内容1\n"
            "\n"
            "## トピック2\n"
            "内容2\n"
            "\n"
            "# 私の目に止まった記事\n"
            "[リンク1](https://example.com/1)\n"
            "コメント1\n"
            "[リンク2](https://example.com/2)\n"
            "コメント2\n"
        )
        chunks = split_markdown_advanced(markdown)
        self.assertEqual(len(chunks), 4)
        self.assertEqual(chunks[0]["index"], "START")
        self.assertIn("トピック1", chunks[0]["content"])
        self.assertEqual(chunks[1]["index"], "END")
        self.assertIn("トピック2", chunks[1]["content"])
        self.assertEqual(chunks[2]["index"], "ARTICLE_0")
        self.assertIn("リンク1", chunks[2]["content"])
        self.assertIn("コメント1", chunks[2]["content"])
        self.assertEqual(chunks[3]["index"], "ARTICLE_1")
        self.assertIn("リンク2", chunks[3]["content"])
        self.assertIn("コメント2", chunks[3]["content"])

    def test_split_markdown_advanced_fallback(self):
        markdown = "# タイトル\n\n本文だけでh2も記事セクションもないよ"
        chunks = split_markdown_advanced(markdown)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["index"], "START")
        self.assertIn("本文だけ", chunks[0]["content"])


if __name__ == "__main__":
    unittest.main()
