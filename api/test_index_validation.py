import unittest

from fastapi import HTTPException

from api.index import _validate_bloc


class ValidateBlocTests(unittest.TestCase):
    def test_pusg_returns_clarification_message(self):
        with self.assertRaises(HTTPException) as exc_info:
            _validate_bloc("pusg")

        self.assertEqual(exc_info.exception.status_code, 400)
        self.assertEqual(
            exc_info.exception.detail,
            'It seems like you might have entered "pusg" by mistake. '
            "If you meant to perform a specific action or request, please clarify, "
            "and I'll be happy to assist you!",
        )


if __name__ == "__main__":
    unittest.main()
