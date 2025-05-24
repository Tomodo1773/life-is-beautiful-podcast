import unittest

from app.utils.markdown_processor import split_markdown_by_h2


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


if __name__ == "__main__":
    unittest.main()
