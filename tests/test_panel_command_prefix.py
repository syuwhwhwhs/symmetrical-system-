import unittest

PREFIX = "."

def choose_prefix(text, configured_prefix):
    if text.startswith(configured_prefix):
        return configured_prefix
    if (text.startswith(PREFIX + "پرفیکس")
            or text == PREFIX + "panel"
            or text.startswith(PREFIX + "panel ")
            or text == PREFIX + "پنل"
            or text.startswith(PREFIX + "پنل ")):
        return PREFIX
    return None

class PanelPrefixTests(unittest.TestCase):
    def test_panel_english_with_custom_prefix(self):
        self.assertEqual(choose_prefix(".panel", "!"), ".")

    def test_panel_persian_with_custom_prefix(self):
        self.assertEqual(choose_prefix(".پنل", "!"), ".")

    def test_other_command_still_uses_custom_prefix(self):
        self.assertEqual(choose_prefix("!ping", "!"), "!")

    def test_unrelated_dot_message_is_not_command(self):
        self.assertIsNone(choose_prefix(".hello", "!"))

if __name__ == "__main__":
    unittest.main()
