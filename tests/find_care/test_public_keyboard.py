"""Keyboard edits on the public Find care lookup (#379). Invented text only.

In a browser, Enter, Tab or a click away keeps the text in City or Service but does not search, and results
are drawn only for the press of the button itself. So after a hit, any edit left the screen with no result
and no message, and a first search by Enter showed no change at all. Setting a field's value and running
the script, as these tests do, is what the browser sends for those keys.
"""
import unittest

from tests.find_care import test_find_care as base

NOTE = ("No results are shown for the city and service above. Select **Search public sources** to search. "
        "Pressing Enter or leaving a field does not search.")


@unittest.skipUnless(base.HAS_STREAMLIT, "Streamlit is needed to run the screen")
class PublicKeyboardTests(unittest.TestCase):
    setUp = base.ScreenTests.setUp
    _app = base.ScreenTests._app
    _step = base.ScreenTests._step
    _text = staticmethod(base.ScreenTests._text)

    def _public(self):
        return self._step(self._app().radio(key="lookup_source").set_value("Public facility evidence"))

    @staticmethod
    def _field(app, label):
        return next(field for field in app.text_input if field.label == label)

    def _search(self, app):
        return self._step(next(button for button in app.button if button.label == "Search public sources").click())

    def _notes(self, app):
        return [note.value for note in app.info]

    def test_an_edit_after_a_hit_says_nothing_is_shown_and_which_button_searches(self):
        app = self._public()
        self.assertEqual([], self._notes(app))  # the opening form has asked for nothing yet
        self._field(app, "Service").set_value("dialysis")
        app = self._search(app)
        self.assertEqual(2, len(app.get("link_button")))
        self.assertEqual([], self._notes(app))
        for label, typed in (("Service", "maintenance haemodialysis"), ("City", "Atlantis"), ("City", "Pune ")):
            with self.subTest(label=label, typed=typed):
                app = self._step(self._field(app, label).set_value(typed))  # Enter, Tab or a click away
                self.assertEqual([NOTE], self._notes(app))
                self.assertFalse(app.get("link_button"))  # no earlier facility or link is left standing
                self.assertNotIn("KEM Hospital, Pune", self._text(app))
                self.assertNotIn("Jehangir Hospital", self._text(app))
        # The press answers for what is typed now, and the note gives way to the result.
        self._field(app, "City").set_value("Pune")
        self._field(app, "Service").set_value("dialysis")
        app = self._search(app)
        self.assertEqual(2, len(app.get("link_button")))
        self.assertEqual([], self._notes(app))

    def test_a_first_search_by_enter_is_answered_with_the_button_to_press(self):
        app = self._public()
        app = self._step(self._field(app, "Service").set_value("dialysis"))
        self.assertEqual([NOTE], self._notes(app))
        self.assertFalse(app.get("link_button"))
        # A miss and a blank field keep their own messages, and the note is not added to them.
        self._field(app, "City").set_value("Atlantis")
        app = self._search(app)
        self.assertEqual(1, len(app.info))
        self.assertIn("no reviewed public claim", app.info[0].value)
        self._field(app, "City").set_value("")
        app = self._search(app)
        self.assertEqual([], self._notes(app))
        self.assertEqual(1, len(app.warning))

    def test_the_form_opens_clean_again_after_another_mode(self):
        app = self._public()
        app = self._search(app)
        self.assertEqual(1, len(app.get("link_button")))
        app = self._step(app.radio(key="lookup_source").set_value("Simulated scenarios"))
        app = self._step(app.radio(key="lookup_source").set_value("Public facility evidence"))
        self.assertEqual([], self._notes(app))
        self.assertFalse(app.get("link_button"))


if __name__ == "__main__":
    unittest.main()
