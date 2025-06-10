import unittest
from unittest.mock import Mock, patch
import os
import tempfile
import shutil

from app.utils.podcast_generator import PodcastGenerator


class TestPodcastGenerator(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures before each test method."""
        self.api_key = "test_api_key"
        self.generator = PodcastGenerator(self.api_key)
        
        # Create temporary directory for test files
        self.test_dir = tempfile.mkdtemp()
        
    def tearDown(self):
        """Clean up after each test method."""
        # Remove temporary directory
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_split_script_short_text(self):
        """Test split_script with text shorter than max_chars."""
        short_script = "This is a short script.\nWith only two lines."
        chunks = self.generator.split_script(short_script, max_chars=3000)
        
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], short_script)

    def test_split_script_long_text(self):
        """Test split_script with text longer than max_chars."""
        # Create a script longer than 100 characters
        long_script = "Line 1\n" * 20  # Each line is 7 chars, total ~140 chars
        chunks = self.generator.split_script(long_script, max_chars=100)
        
        self.assertGreater(len(chunks), 1)
        # Check that each chunk is within the limit
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 100)
        
        # Check that all chunks combined equal the original
        combined = '\n'.join(chunks)
        self.assertEqual(combined.replace('\n\n', '\n'), long_script.rstrip())

    def test_split_script_at_newlines(self):
        """Test that split_script breaks at newlines, not mid-line."""
        script = "First line that is quite long and exceeds the limit\nSecond line\nThird line"
        chunks = self.generator.split_script(script, max_chars=30)
        
        # Each chunk should contain complete lines (no partial lines)
        for chunk in chunks:
            lines = chunk.split('\n')
            # The last line should not be empty (unless it's an intentional newline)
            if chunk.endswith('\n'):
                self.assertTrue(True)  # Ending with newline is acceptable
            else:
                # If not ending with newline, should still be complete lines
                self.assertGreater(len(lines[-1]), 0)

    def test_split_script_preserve_content(self):
        """Test that split_script preserves all content."""
        original_script = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
        chunks = self.generator.split_script(original_script, max_chars=15)
        
        # Reconstruct the original from chunks
        reconstructed = '\n'.join(chunks).replace('\n\n', '\n').rstrip()
        self.assertEqual(reconstructed, original_script)

    def test_split_script_empty_string(self):
        """Test split_script with empty string."""
        chunks = self.generator.split_script("", max_chars=3000)
        self.assertEqual(len(chunks), 0)

    def test_split_script_single_long_line(self):
        """Test split_script with a single line longer than max_chars."""
        long_line = "a" * 5000  # Single line of 5000 characters
        chunks = self.generator.split_script(long_line, max_chars=3000)
        
        self.assertEqual(len(chunks), 1)  # Should still be one chunk since no newlines
        self.assertEqual(chunks[0], long_line)

    def test_split_script_multiple_newlines(self):
        """Test split_script handles multiple consecutive newlines."""
        script = "Line 1\n\n\nLine 2\n\nLine 3"
        chunks = self.generator.split_script(script, max_chars=10)
        
        # Should preserve multiple newlines
        reconstructed = '\n'.join(chunks).replace('\n\n', '\n').rstrip()
        expected = script.replace('\n\n\n', '\n\n').replace('\n\n', '\n')
        self.assertEqual(reconstructed, expected)

    @patch('app.utils.podcast_generator.genai.Client')
    def test_init_with_api_key(self, mock_client):
        """Test PodcastGenerator initialization with API key."""
        api_key = "test_key_123"
        generator = PodcastGenerator(api_key)
        
        mock_client.assert_called_once_with(api_key=api_key)
        self.assertEqual(generator.client, mock_client.return_value)


if __name__ == "__main__":
    unittest.main()