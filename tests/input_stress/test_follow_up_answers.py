"""Odd answers to follow-up questions and odd provider replies on Check symptoms (#379).

Every reply here comes from the scripted stand-in the patient screen tests use. Nothing is a real provider's
question and nothing says anything about clinical accuracy. These cases passed when first run. They are kept
so the next change to the screen is checked against the same inputs.
"""
import copy
import unittest

from tests.patient_ui import test_patient_ui as base

TEXT = {"state": "awaiting_clarification", "question": {"id": "q-text", "kind": "text", "prompt": "Invented text question",
                                                        "options": []}}
# typed amount -> what reaches the runtime, or None when the answer is refused on the screen
AMOUNTS = (("3", 3), (" 3 ", 3), ("+3", 3), ("03", 3), ("3.0", 3.0), (".5", 0.5), ("५", 5), ("３", 3), ("", None), (" ", None),
           ("three", None), ("3 days", None), ("1,5", None), ("-3", None), ("nan", None), ("inf", None), ("1e309", None),
           ("1e5", None), ("1_0", None), ("0x10", None), ("²", None), ("3​", None), ("1" * 32, None))
REPLIES = (None, {}, {"state": "bogus"}, {"state": "completed"}, {"state": "urgent"}, {"state": "awaiting_clarification"},
           {"state": "completed", "guidance": 5, "urgency": "x", "possible_causes": "abc"},
           {"state": "awaiting_clarification", "question": {"id": "q", "kind": "single", "prompt": "p", "options": []}},
           {"state": "awaiting_clarification", "question": {"id": "q", "kind": "telepathy", "prompt": "p",
                                                            "options": [{"id": "a", "label": "A"}]}},
           {"state": "awaiting_clarification", "question": {
               "id": "q", "kind": "single", "prompt": "<script>window.x=1</script>" * 20,
               "options": [{"id": "a", "label": "<b>A</b>"}, {"id": "a", "label": "again"}]}},
           RuntimeError("invented failure"), TimeoutError("invented timeout"))


@unittest.skipUnless(base.HAS_STREAMLIT, "Streamlit is needed to run the screen")
class FollowUpAnswerTests(unittest.TestCase):
    setUp = base.ScreenTests.setUp
    provider = base.ScreenTests.provider
    open = base.ScreenTests.open
    press = base.ScreenTests.press
    shown = staticmethod(base.ScreenTests.shown)
    begin = base.ScreenTests.begin
    fields = base.ScreenTests.fields

    def _asked(self, question):
        provider = self.provider(question, base.STOP)
        return provider, self.press(self.begin(self.open()), "I agree. Send it for assessment")

    def test_a_typed_amount_is_used_as_typed_or_refused_before_any_provider_turn(self):
        for typed, expected in AMOUNTS:
            with self.subTest(typed=typed):
                provider, app = self._asked(base.AMOUNT)
                self.fields(app, "text_input")[0].input(typed)
                self.fields(app, "radio", "-unit")[0].set_value("unit-weeks")
                app = self.press(app, "Send answer")
                if expected is None:
                    self.assertIn(self.screen.BAD_ANSWER, self.shown(app))
                    self.assertEqual(1, len(provider.calls))  # nothing more was sent
                    self.assertEqual(1, len(self.fields(app, "text_input")))  # the question is still there to answer
                else:
                    answer = provider.calls[1]["interview"]["answers"][0]["answer"]
                    self.assertEqual({"value": expected, "unit_id": "unit-weeks"}, answer)
                    self.assertIs(type(expected), type(answer["value"]))

    def test_a_written_answer_is_kept_to_its_limit(self):
        for length, accepted in ((0, False), (1, True), (1499, True), (1500, True), (1501, False), (4000, False)):
            with self.subTest(length=length):
                provider, app = self._asked(TEXT)
                area = [field for field in app.text_area if str(field.key).startswith("pt-answer-")][0]
                area.input("x" * length if length else "   ")
                app = self.press(app, "Send answer")
                self.assertEqual(2 if accepted else 1, len(provider.calls))
                self.assertEqual(not accepted, self.screen.BAD_ANSWER in self.shown(app))

    def test_a_reply_the_screen_cannot_use_never_breaks_it_and_always_leaves_a_way_on(self):
        for number, reply in enumerate(REPLIES):
            with self.subTest(reply=number):
                self.provider(reply if isinstance(reply, Exception) else copy.deepcopy(reply), base.DONE)
                app = self.press(self.begin(self.open()), "I agree. Send it for assessment")
                text, labels = self.shown(app), [button.label for button in app.button]
                self.assertNotIn("<script>window.x", text.replace("&lt;script&gt;window.x", ""))
                self.assertIn(base.STATEMENT, text)  # the person's own words are still shown
                self.assertIn("Change my description", labels)
                self.assertIn("Start over", labels)
                for absent in ("Possible causes", "Where to go"):
                    self.assertNotIn(absent, text)


if __name__ == "__main__":
    unittest.main()
