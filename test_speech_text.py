import unittest

from speech_text import SpeechChunker, daemon_says, speechify_markdown


class SpeechTextTests(unittest.TestCase):
    def test_markdown_table_is_not_spoken_raw(self):
        text = """Here are options:

| Name | Value |
| --- | --- |
| Alpha | 10 |
| Beta | 20 |

Pick one."""
        spoken, removed = speechify_markdown(text)
        self.assertTrue(removed)
        self.assertIn("Here are options", spoken)
        self.assertIn("I put a table on the screen.", spoken)
        self.assertIn("Pick one", spoken)
        self.assertNotIn("|", spoken)
        self.assertNotIn("---", spoken)

    def test_links_and_bullets_are_cleaned(self):
        spoken, removed = speechify_markdown("- [OpenClaw](https://example.com) is **ready**.")
        self.assertFalse(removed)
        self.assertEqual(spoken, "OpenClaw is ready.")

    def test_chunker_waits_for_table_block(self):
        chunker = SpeechChunker()
        self.assertEqual(chunker.append("Here is a table:\n\n| A | B |\n"), [])
        self.assertEqual(chunker.append("| --- | --- |\n| one | two |\n"), ["Here is a table:"])
        out = chunker.append("\nDone.")
        self.assertEqual(len(out), 1)
        self.assertNotIn("|", out[0])
        self.assertIn("I put a table on the screen.", out[0])

    def test_table_notice_only_once(self):
        chunker = SpeechChunker()
        first = chunker.append("| A | B |\n| --- | --- |\n| one | two |\n\n")
        second = chunker.append("| C | D |\n| --- | --- |\n| three | four |\n\n")
        self.assertIn("I put a table on the screen.", " ".join(first))
        self.assertNotIn("I put a table on the screen.", " ".join(second))

    def test_daemon_says_rewrites_common_first_person(self):
        self.assertEqual(
            daemon_says("I'll take care of that."),
            "Daemon says he'll take care of that.",
        )
        self.assertEqual(
            daemon_says("I can ask Doug."),
            "Daemon says he can ask Doug.",
        )
        self.assertEqual(
            daemon_says("Daemon says he already did it."),
            "Daemon says he already did it.",
        )

    def test_chunker_can_wrap_spoken_chunks(self):
        chunker = SpeechChunker(third_person=True)
        out = chunker.append("I'll take care of that. It is queued. ")
        self.assertEqual(out, ["Daemon says he'll take care of that. It is queued."])


if __name__ == "__main__":
    unittest.main()
