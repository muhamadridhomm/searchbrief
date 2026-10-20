import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.images import ImageServiceError, generate_image, search_images
from app.main import ImageGenerateRequest, ImageSearchRequest, image_generate


class ImageTests(unittest.TestCase):
    def test_commons_result_exposes_rights_metadata(self):
        data = {"query": {"pages": [{"title": "File:Test.jpg", "imageinfo": [{"url": "https://example.org/test.jpg", "thumburl": "https://example.org/thumb.jpg", "descriptionurl": "https://commons.wikimedia.org/wiki/File:Test.jpg", "mime": "image/jpeg", "extmetadata": {"Artist": {"value": "<b>A. Creator</b>"}, "LicenseShortName": {"value": "CC BY-SA 4.0"}}}]}]}}
        result = search_images("test image", fetch=lambda _: data)
        self.assertEqual(result[0]["creator"], "A. Creator")
        self.assertEqual(result[0]["license"], "CC BY-SA 4.0")
        self.assertEqual(result[0]["kind"], "searched")

    def test_generation_uses_key_for_request_but_never_returns_it(self):
        def fake_post(body, key):
            self.assertEqual(key, "test-secret-key")
            self.assertEqual(body["contents"][0]["parts"][0]["text"], "An abstract illustration")
            return {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": "aGVsbG8="}}]}}]}
        result = generate_image("An abstract illustration", "test-secret-key", post=fake_post)
        self.assertEqual(result["kind"], "generated")
        self.assertNotIn("test-secret-key", str(result))

    def test_generation_errors_do_not_echo_key(self):
        with patch("app.main.generate_image", side_effect=ImageServiceError("Image service unavailable")):
            with self.assertRaises(HTTPException) as raised:
                image_generate(ImageGenerateRequest(prompt="An abstract illustration", api_key="test-secret-key"))
        self.assertNotIn("test-secret-key", str(raised.exception.detail))
        with self.assertRaises(ValidationError):
            ImageSearchRequest(query="x")
