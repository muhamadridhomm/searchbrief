import unittest
import json
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.main import GenerateRequest, ResearchRequest, RevisionRequest, app, generate_brief, generate_events, research_events, start_local_ollama
import app.main as main
from app.service import ModelUnavailable


class ApiTests(unittest.TestCase):
    def test_ollama_start_is_local_only(self):
        with patch.object(main, "health", return_value={"ollama_available": False}), patch.object(main.subprocess, "Popen") as popen:
            with self.assertRaises(HTTPException) as raised:
                start_local_ollama(SimpleNamespace(client=SimpleNamespace(host="192.0.2.1")))
        self.assertEqual(raised.exception.status_code, 403)
        popen.assert_not_called()

    def test_ollama_start_rejects_other_browser_origins(self):
        request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={"origin": "https://untrusted.example"})
        with patch.object(main, "health", return_value={"ollama_available": False}), patch.object(main.subprocess, "Popen") as popen:
            with self.assertRaises(HTTPException) as raised:
                start_local_ollama(request)
        self.assertEqual(raised.exception.status_code, 403)
        popen.assert_not_called()

    def test_ollama_start_reports_missing_bundled_runtime(self):
        request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={})
        with patch.object(main, "health", return_value={"ollama_available": False}), \
             patch.object(main, "OLLAMA_START_SCRIPT") as launcher, \
             patch.object(main, "OLLAMA_BINARY") as binary, \
             patch.object(main, "OLLAMA_MODEL_MANIFEST") as manifest, \
             patch.object(main.subprocess, "Popen") as popen:
            launcher.is_file.return_value = False
            binary.is_file.return_value = False
            manifest.is_file.return_value = False
            with self.assertRaises(HTTPException) as raised:
                start_local_ollama(request)
        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("Follow the Ollama setup guide", raised.exception.detail)
        popen.assert_not_called()

    def test_revision_request_accepts_bounded_draft_notes_and_claim_feedback(self):
        payload = self.payload()
        payload.update({"current_draft": "Existing draft", "revision_notes": "Keep the post focused", "claim_reviews": [{
            "claim": "A claim", "status": "unsupported", "reason": "No source", "source_ids": ["ps5-homebrew"],
            "checked_by_user": True, "reviewer_note": "Remove this claim", "revision_action": "remove",
        }]})
        request = RevisionRequest(**payload)
        self.assertEqual(request.revision_notes, "Keep the post focused")
        self.assertEqual(request.claim_reviews[0].reviewer_note, "Remove this claim")
        self.assertEqual(request.claim_reviews[0].revision_action, "remove")
        self.assertTrue(any(route.path == "/api/revise/stream" for route in app.routes))

    def payload(self):
        return {
            "topic": "AI-assisted reverse engineering",
            "reader": "General readers",
            "question": "What does AI assistance change?",
            "useful_outcome": "Understand the limits and risks",
            "writer_notes": "Do not claim banking compromise without evidence.",
            "claim_to_check": "AI discovered the PS5 jailbreak",
            "evidence": [{
                "id": "ps5-homebrew",
                "title": "PS5 homebrew report",
                "summary": "Claude helped with a homebrew app after the console was jailbroken.",
                "url": "https://example.com/report",
            }],
        }

    def test_generate_returns_structured_result(self):
        generated = {
            "angle": "AI helps analyze software, but verification matters",
            "brief": {"reader": "General readers", "problem": "Understand the technology", "value": "Separate evidence from speculation", "key_points": ["Test AI output"]},
            "post_draft": "AI can assist with reverse engineering; results need checks.",
            "claim_reviews": [],
            "model": "qwen3:4b",
            "notice": "AI claim assessments are suggestions, not independent verification.",
        }
        with patch("app.main.generate", return_value=generated):
            response = generate_brief(GenerateRequest(**self.payload()))
        self.assertEqual(response["post_draft"], generated["post_draft"])

    def test_invalid_request_is_rejected_before_model_call(self):
        payload = self.payload()
        payload["topic"] = "x"
        with patch("app.main.generate") as generate_mock, self.assertRaises(ValidationError):
            request = GenerateRequest(**payload)
            generate_brief(request)
        generate_mock.assert_not_called()

    def test_request_without_evidence_is_rejected(self):
        payload = self.payload()
        payload["evidence"] = []
        with patch("app.main.generate") as generate_mock, self.assertRaises(ValidationError):
            request = GenerateRequest(**payload)
            generate_brief(request)
        generate_mock.assert_not_called()

    def test_invalid_composition_ranges_are_rejected(self):
        payload = self.payload()
        payload["paragraphs_min"] = 5
        payload["paragraphs_max"] = 2
        with self.assertRaises(ValidationError):
            GenerateRequest(**payload)

    def test_hashtag_limit_accepts_fifteen_but_rejects_zero(self):
        payload = self.payload()
        payload.update(hashtag_mode="auto", hashtag_count=15)
        self.assertEqual(GenerateRequest(**payload).hashtag_count, 15)
        payload["hashtag_count"] = 0
        with self.assertRaises(ValidationError):
            GenerateRequest(**payload)

    def test_generation_accepts_twelve_approved_sources_but_not_thirteen(self):
        evidence = [{"id": f"source-{index}", "title": f"Source {index}", "summary": "A source note with enough text to review.", "url": f"https://example.com/{index}"} for index in range(12)]
        self.assertEqual(len(GenerateRequest(**{**self.payload(), "evidence": evidence}).evidence), 12)
        extra = {"id": "source-13", "title": "Source 13", "summary": "A source note.", "url": "https://example.com/13"}
        with self.assertRaises(ValidationError):
            GenerateRequest(**{**self.payload(), "evidence": [*evidence, extra]})

    def test_unavailable_ollama_returns_retryable_service_error(self):
        with patch("app.main.generate", side_effect=ModelUnavailable("offline")):
            with self.assertRaises(HTTPException) as raised:
                generate_brief(GenerateRequest(**self.payload()))
        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("Start the local model", raised.exception.detail)

    def test_research_stream_reports_real_phase_counts_and_result(self):
        with patch("app.main.plan_queries", return_value=(["reverse engineering"], "keyword fallback")), \
             patch("app.main.search_publications", return_value=[{"id": "crossref-1", "title": "Reverse engineering study", "summary": "Research on reverse engineering methods.", "provider": "Crossref"}]), \
             patch("app.main.search_github_repositories", return_value=[]), \
             patch("app.main.search_openalex", return_value=[]), \
             patch("app.main.search_stackexchange", return_value=[]), \
             patch("app.main.search_pages", return_value=[{"id": "wikipedia-1", "title": "Reverse engineering", "summary": "Background on reverse engineering systems.", "provider": "Wikipedia"}]):
            events = [json.loads(line) for line in research_events(ResearchRequest(topic="Reverse engineering", question="What changed?"))]
        self.assertEqual([event["step"] for event in events if event["type"] == "progress"], [1, 2, 3, 4, 5, 6, 7, 8])
        self.assertIn("Found 1 research record", events[2]["message"])
        self.assertEqual(len(events[-1]["data"]["sources"]), 2)

    def test_saved_first_stream_checks_local_notes_before_web(self):
        saved = {"id": "saved-1", "title": "AI reverse engineering", "summary": "Software analysis notes", "url": "https://example.com/source"}
        request = ResearchRequest(topic="AI reverse engineering", question="How does software analysis work?", search_mode="saved_then_web", saved_sources=[saved])
        with patch("app.main.plan_queries", return_value=(["reverse engineering"], "local AI")), \
             patch("app.main.search_publications", return_value=[{"id": "web-1", "title": "AI reverse engineering", "summary": "AI reverse engineering for software analysis.", "provider": "Crossref"}]), \
             patch("app.main.search_github_repositories", return_value=[]), \
             patch("app.main.search_openalex", return_value=[]), \
             patch("app.main.search_stackexchange", return_value=[]), \
             patch("app.main.search_pages", return_value=[]):
            events = [json.loads(line) for line in research_events(request)]
        steps = [event["step"] for event in events if event["type"] == "progress"]
        self.assertEqual(steps, [1, 2, 3, 4, 5, 6, 7, 8, 9])
        self.assertIn("saved", events[2]["message"])
        saved_result = next(source for source in events[-1]["data"]["sources"] if source["id"] == "saved-1")
        self.assertNotIn("approved", saved_result)

    def test_web_only_ignores_saved_notes(self):
        saved = {"id": "saved-1", "title": "AI reverse engineering", "summary": "Software analysis notes", "url": "https://example.com/source"}
        request = ResearchRequest(topic="AI reverse engineering", question="How does software analysis work?", search_mode="web_only", saved_sources=[saved])
        with patch("app.main.plan_queries", return_value=(["reverse engineering"], "keyword fallback")), \
             patch("app.main.search_publications", return_value=[]), \
             patch("app.main.search_github_repositories", return_value=[]), \
             patch("app.main.search_openalex", return_value=[]), \
             patch("app.main.search_stackexchange", return_value=[]), \
             patch("app.main.search_pages", return_value=[{"id": "web-1", "title": "AI reverse engineering", "summary": "AI reverse engineering for software analysis.", "provider": "Wikipedia"}]):
            events = [json.loads(line) for line in research_events(request)]
        self.assertEqual([item["id"] for item in events[-1]["data"]["sources"]], ["web-1"])
        self.assertEqual([event["step"] for event in events if event["type"] == "progress"], [1, 2, 3, 4, 5, 6, 7, 8])

    def test_draft_stream_forwards_model_phases_and_finishes(self):
        def fake_generate(payload, progress):
            progress(1, 5, "Preparing approved sources")
            progress(2, 5, "Writing the draft with Ollama")
            return {"post_draft": "Done"}
        with patch("app.main.generate", side_effect=fake_generate):
            events = [json.loads(line) for line in generate_events(GenerateRequest(**self.payload()))]
        self.assertEqual([event["step"] for event in events if event["type"] == "progress"], [1, 2])
        self.assertEqual(events[-1]["data"]["post_draft"], "Done")


if __name__ == "__main__":
    unittest.main()
