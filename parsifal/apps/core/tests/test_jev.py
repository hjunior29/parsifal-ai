from unittest import mock

from django.test import SimpleTestCase, override_settings

import requests

from parsifal.apps.core import jev


def response(status, body=None, headers=None, text=""):
    fake = mock.Mock(status_code=status, headers=headers or {}, text=text, reason="Reason")
    if body is None:
        fake.json.side_effect = ValueError
    else:
        fake.json.return_value = body
    return fake


ANSWER = {"model": "jev-1.13.0", "answers": {"q": {"type": "noul", "noul": 0.9}}, "usage": {"input_tokens": 10}}


@override_settings(JEV_API_URL="https://jev.example/")
class TestJevClient(SimpleTestCase):
    def setUp(self):
        self.sleep = mock.Mock()

    def test_evaluate_sends_the_request(self):
        with mock.patch.object(requests, "request", return_value=response(200, ANSWER)) as request:
            result = jev.evaluate("secret", model="jev-1.13.0", state="text", questions={"q": {}}, sleep=self.sleep)
        self.assertEqual(ANSWER, result)
        request.assert_called_once_with(
            "POST",
            "https://jev.example/v1/systemone",
            headers={"Authorization": "Bearer secret"},
            json={"model": "jev-1.13.0", "state": "text", "questions": {"q": {}}},
            timeout=jev.TIMEOUT,
        )

    def test_retries_rate_limits_and_honours_retry_after(self):
        replies = [response(429, {}, headers={"Retry-After": "3"}), response(529, {}), response(200, ANSWER)]
        with mock.patch.object(requests, "request", side_effect=replies) as request:
            jev.evaluate("secret", model="m", state="s", questions={}, sleep=self.sleep)
        self.assertEqual(3, request.call_count)
        self.assertEqual([mock.call(3.0), mock.call(2)], self.sleep.call_args_list)

    def test_gives_up_after_the_last_retry(self):
        with mock.patch.object(requests, "request", return_value=response(429, {"message": "slow down"})) as request:
            with self.assertRaises(jev.JevError) as caught:
                jev.evaluate("secret", model="m", state="s", questions={}, sleep=self.sleep)
        self.assertEqual(len(jev.RETRY_DELAYS) + 1, request.call_count)
        self.assertEqual((429, False), (caught.exception.status, caught.exception.fatal))
        self.assertIn("slow down", str(caught.exception))

    def test_network_errors_are_retried_then_reported(self):
        with mock.patch.object(requests, "request", side_effect=requests.ConnectionError("boom")):
            with self.assertRaisesMessage(jev.JevError, "Could not reach Jev (ConnectionError)."):
                jev.list_models("secret", sleep=self.sleep)
        self.assertEqual(len(jev.RETRY_DELAYS), self.sleep.call_count)

    def test_rejected_key_is_fatal_and_never_echoed(self):
        with mock.patch.object(requests, "request", return_value=response(401, {"message": "bad key"})):
            with self.assertRaises(jev.JevError) as caught:
                jev.evaluate("secret", model="m", state="s", questions={}, sleep=self.sleep)
        self.assertTrue(caught.exception.fatal)
        self.assertNotIn("secret", str(caught.exception))
        self.sleep.assert_not_called()

    def test_client_errors_and_malformed_answers(self):
        with mock.patch.object(requests, "request", return_value=response(400, {"error": "max_tokens_exceeded"})):
            with self.assertRaisesMessage(jev.JevError, "Jev answered 400: max_tokens_exceeded"):
                jev.evaluate("k", model="m", state="s", questions={}, sleep=self.sleep)
        with mock.patch.object(requests, "request", return_value=response(200, None, text="<html>")):
            with self.assertRaisesMessage(jev.JevError, "not JSON"):
                jev.evaluate("k", model="m", state="s", questions={}, sleep=self.sleep)
        with mock.patch.object(requests, "request", return_value=response(200, {"model": "m"})):
            with self.assertRaisesMessage(jev.JevError, "without answers"):
                jev.evaluate("k", model="m", state="s", questions={}, sleep=self.sleep)

    def test_list_models_returns_model_cards(self):
        cards = [
            {"name": "jev-1.13.0", "description": "Stable", "release_date": "2026-08-01"},
            {"name": "jev-1.14.0", "description": "Newest", "release_date": "2026-10-14"},
        ]
        with mock.patch.object(requests, "request", return_value=response(200, cards)):
            self.assertEqual(cards, jev.list_models("k", sleep=self.sleep))

    def test_list_models_accepts_other_shapes(self):
        shapes = (
            {"data": [{"id": "jev-1.13.0"}, {"id": "jev-1.14.0"}]},
            {"models": [{"name": "jev-1.13.0"}, "jev-1.14.0"]},
            ["jev-1.13.0", "jev-1.14.0", 7, {"description": "no name"}],
        )
        for body in shapes:
            with self.subTest(body=body), mock.patch.object(requests, "request", return_value=response(200, body)):
                models = jev.list_models("k", sleep=self.sleep)
                self.assertEqual(["jev-1.13.0", "jev-1.14.0"], [model["name"] for model in models])
                self.assertEqual({"name", "description", "release_date"}, set(models[0]))

    def test_quick_lookups_try_once_with_a_short_timeout(self):
        with mock.patch.object(requests, "request", side_effect=requests.ConnectionError("down")) as request:
            with self.assertRaises(jev.JevError):
                jev.list_models("k", sleep=self.sleep, quick=True)
        self.assertEqual(1, request.call_count)
        self.assertEqual(jev.QUICK_TIMEOUT, request.call_args.kwargs["timeout"])
        self.sleep.assert_not_called()


@override_settings(JEV_API_URL="https://jev.example/", JEV_REQUESTS_PER_MINUTE=600)
class TestJevPacing(SimpleTestCase):
    """At 600 requests per minute, requests with one key leave at least 0.1 s apart."""

    def setUp(self):
        self.clock = [100.0]
        self.waits = []
        patcher = mock.patch.object(jev, "_now", side_effect=lambda: self.clock[0])
        patcher.start()
        self.addCleanup(patcher.stop)
        jev._turns.clear()
        self.addCleanup(jev._turns.clear)

    def sleep(self, seconds):
        self.waits.append(round(seconds, 6))
        self.clock[0] += seconds

    def test_requests_with_one_key_are_spaced(self):
        with mock.patch.object(requests, "request", return_value=response(200, ANSWER)):
            for _ in range(3):
                jev.evaluate("secret", model="m", state="s", questions={}, sleep=self.sleep)
            self.assertEqual([0.1, 0.1], self.waits)  # back to back: each waits for its turn
            self.waits.clear()
            jev.evaluate("another key", model="m", state="s", questions={}, sleep=self.sleep)
            self.assertEqual([], self.waits)  # each key has its own turns
            self.clock[0] += 5
            jev.evaluate("secret", model="m", state="s", questions={}, sleep=self.sleep)
            self.assertEqual([], self.waits)  # its turn has passed
        self.assertNotIn("secret", repr(jev._turns))

    def test_a_rate_limit_holds_every_request_with_the_key(self):
        replies = [response(429, {}, headers={"Retry-After": "3"}), response(200, ANSWER)]
        with mock.patch.object(requests, "request", side_effect=replies):
            jev.evaluate("secret", model="m", state="s", questions={}, sleep=self.sleep)
        self.assertEqual([3.0], self.waits)  # Retry-After, then the retry left at once
        self.waits.clear()
        jev._hold("secret", 3)  # what another thread meets while a 429 is being waited out
        jev._wait_turn("secret", self.sleep)
        self.assertEqual([3.0], self.waits)

    def test_quick_lookups_and_zero_skip_the_spacing(self):
        with mock.patch.object(requests, "request", return_value=response(200, [])):
            for _ in range(2):
                jev.list_models("secret", sleep=self.sleep, quick=True)
        self.assertEqual([], self.waits)
        with (
            override_settings(JEV_REQUESTS_PER_MINUTE=0),
            mock.patch.object(requests, "request", return_value=response(200, ANSWER)),
        ):
            for _ in range(3):
                jev.evaluate("secret", model="m", state="s", questions={}, sleep=self.sleep)
        self.assertEqual([], self.waits)
