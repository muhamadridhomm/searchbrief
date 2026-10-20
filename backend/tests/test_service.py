import json
import unittest

from app.service import InvalidModelOutput, _apply_known_claim_boundary, _is_known_ps5_overclaim, _validate_claim_reviews, _validate_output, apply_hashtags, audit_draft, build_claim_review_prompt, build_prompt, draft_format_issues, generate, review_draft_quality


COMPLIANT_DRAFT = (
    "Software documentation often falls behind the systems it describes, leaving readers to infer behavior from code. "
    "A useful documentation effort starts with the questions people need answered about interfaces, data flow, and change. "
    "Those questions can guide a careful review of repositories, tests, and existing notes before anyone writes a new summary.\n\n"
    "AI tools may help organize that review and propose descriptions, but the resulting claims still need human checks. "
    "A project can illustrate one possible approach without proving that the same method works for every codebase. "
    "The practical goal is documentation that states what the available evidence shows, names its gaps, and remains useful during maintenance. "
    "Readers should be able to trace important statements back to code or a source, rather than trusting fluent prose alone."
)


def valid_output():
    return {
        "angle": "AI assistance speeds analysis, but evidence still matters",
        "brief": {
            "reader": "General readers interested in AI and software",
            "problem": "What does AI-assisted reverse engineering mean for trust?",
            "value": "Distinguish assistance from autonomous discovery",
            "key_points": ["AI output needs checks", "Security impact is dual-use"],
        },
        "post_draft": COMPLIANT_DRAFT,
        "claim_reviews": [],
    }


class ServiceTests(unittest.TestCase):
    def test_separate_quality_reviewer_returns_focus_feedback_and_tightened_text(self):
        payload = {"topic": "AI-assisted reverse engineering", "reader": "General readers", "question": "Can AI help recover undocumented system logic?", "useful_outcome": "Treat AI explanations as hypotheses"}
        calls = []
        def fake_call(url, body):
            calls.append(body)
            self.assertIn("You are an independent editorial quality reviewer", body["messages"][0]["content"])
            self.assertIn("This is NOT a factual/source audit", body["messages"][1]["content"])
            return {"message": {"content": json.dumps({"status": "revise", "summary": "The conclusion drifts from the brief.", "issues": ["Ending introduces a new subject."], "paragraph_findings": [{"paragraph_index": 1, "category": "focus", "problem": "The point wanders.", "why_it_matters": "It weakens the through-line.", "suggested_revision": "A tighter paragraph."}], "revised_draft": "Tightened complete draft."})}}
        review = review_draft_quality(payload, "Existing draft.", model_call=fake_call)
        self.assertEqual(len(calls), 1)
        self.assertEqual(review["status"], "revise")
        self.assertEqual(review["suggested_draft"], "Tightened complete draft.")
        self.assertEqual(review["paragraph_findings"][0]["paragraph_index"], 1)
        self.assertEqual(review["paragraph_findings"][0]["suggested_revision"], "A tighter paragraph.")

    def test_editorial_review_retries_incomplete_output_and_accepts_paragraph_only_result(self):
        calls = []
        def fake_call(url, body):
            calls.append(body)
            if len(calls) == 1:
                return {"message": {"content": '{"status":"revise","summary":"Incomplete"}'}}
            return {"message": {"content": json.dumps({"status": "revise", "summary": "Paragraph two drifts.", "issues": ["Topic drift."], "paragraph_findings": [{"paragraph_index": 2, "category": "focus", "problem": "It changes subjects.", "why_it_matters": "The through-line breaks.", "suggested_revision": "Return to the reader's question."}]})}}
        review = review_draft_quality({}, "First paragraph.\n\nSecond paragraph.", model_call=fake_call)
        self.assertEqual(len(calls), 2)
        self.assertEqual(review["status"], "revise")
        self.assertEqual(review["suggested_draft"], "First paragraph.\n\nSecond paragraph.")
        self.assertEqual(review["paragraph_findings"][0]["paragraph_index"], 2)

    def test_editorial_review_does_not_pass_mixed_or_invalid_findings(self):
        response = {"status": "pass", "summary": "Looks good.", "issues": [], "paragraph_findings": [{"paragraph_index": 9, "category": "focus", "problem": "x", "why_it_matters": "y", "suggested_revision": "z"}]}
        review = review_draft_quality({}, "One paragraph.", model_call=lambda *_: {"message": {"content": json.dumps(response)}})
        self.assertEqual(review["status"], "needs_manual_review")
        self.assertEqual(review["paragraph_findings"], [])

    def test_editorial_review_flags_word_count_reported_by_model_when_it_conflicts_with_actual(self):
        calls = []
        response = {"status": "pass", "summary": "The draft is concise at 172 words.", "issues": [], "paragraph_findings": []}
        def fake_call(url, body):
            calls.append(body)
            return {"message": {"content": json.dumps(response)}}
        review = review_draft_quality({}, "Two words.", model_call=fake_call)
        self.assertEqual(len(calls), 2)
        self.assertEqual(review["status"], "needs_manual_review")
        self.assertIn("deterministic count (2 words)", review["summary"])
        self.assertIn("actual word count", calls[1]["messages"][1]["content"])

    def test_claim_audit_retries_incomplete_explanations(self):
        calls = []
        payload = {"evidence": [{"id": "source-1", "title": "Source", "summary": "The model supports code execution.", "url": "https://example.com"}]}
        def fake_call(url, body):
            calls.append(body)
            row = {"claim": "The model supports code execution.", "status": "supported", "reason": "It is stated in the note.", "evidence_excerpt": "The model supports code execution.", "source_ids": ["source-1"]}
            if len(calls) == 1:
                row.pop("reason")
            return {"message": {"content": json.dumps({"claim_reviews": [row]})}}
        result = audit_draft(payload, "The model supports code execution.", model_call=fake_call)
        self.assertEqual(len(calls), 2)
        self.assertIn("Never leave required fields out", calls[1]["messages"][1]["content"])
        self.assertEqual(result["claim_audit_status"], "complete")
        self.assertEqual(result["claim_reviews"][0]["status"], "supported")

    def test_generation_runs_quality_review_before_fact_audit(self):
        payload = {"topic": "AI-assisted reverse engineering", "reader": "General readers", "question": "Can AI help recover undocumented system logic?", "useful_outcome": "Treat AI explanations as hypotheses", "writer_notes": "", "claim_to_check": "", "evidence": [{"id": "study", "title": "Study", "summary": "Bounded source note.", "url": "https://example.com"}]}
        calls = []
        def fake_call(url, body):
            calls.append(body)
            if len(calls) == 1:
                return {"message": {"content": json.dumps(valid_output())}}
            if len(calls) == 2:
                return {"message": {"content": json.dumps({"status": "pass", "summary": "On brief and concise.", "issues": [], "paragraph_findings": [], "revised_draft": "ignored when passing"})}}
            return {"message": {"content": json.dumps({"claim_reviews": [{"claim": "A sentence", "status": "needs_review", "reason": "Inspect the source.", "evidence_excerpt": "", "source_ids": ["study"]}]})}}
        result = generate(payload, model_call=fake_call)
        self.assertEqual(result["draft_quality"]["status"], "passed")
        self.assertEqual(result["quality_reviewed_draft"], result["post_draft"])
        self.assertIn("independent editorial quality reviewer", calls[1]["messages"][0]["content"])
        self.assertIn("Audit every factual statement", calls[2]["messages"][1]["content"])

    def test_generation_keeps_draft_unchanged_until_user_applies_editorial_suggestion(self):
        payload = {"topic": "AI-assisted reverse engineering", "reader": "General readers", "question": "Can AI help recover undocumented system logic?", "useful_outcome": "Treat AI explanations as hypotheses", "writer_notes": "", "claim_to_check": "", "evidence": [], "audit_sources": False}
        calls = 0
        def fake_call(url, body):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"message": {"content": json.dumps(valid_output())}}
            return {"message": {"content": json.dumps({"status": "revise", "summary": "Paragraph 2 repeats the first point.", "issues": ["Repeated idea."], "paragraph_findings": [{"paragraph_index": 2, "category": "repetition", "problem": "Repeats the main point.", "why_it_matters": "The post stops progressing.", "suggested_revision": "A replacement grounded in the same evidence."}], "revised_draft": COMPLIANT_DRAFT})}}
        result = generate(payload, model_call=fake_call)
        self.assertEqual(result["post_draft"], COMPLIANT_DRAFT)
        self.assertEqual(result["draft_quality"]["status"], "suggestions_available")
        self.assertEqual(result["draft_quality"]["paragraph_findings"][0]["paragraph_index"], 2)

    def test_revision_prompt_uses_notes_and_audit_as_feedback_not_proof(self):
        payload = {
            "topic": "Reverse engineering with AI", "reader": "General readers",
            "question": "How can AI help recover system knowledge?", "useful_outcome": "Explain benefits and limits",
            "writer_notes": "Keep focus on code documentation.", "claim_to_check": "",
            "evidence": [{"id": "study", "title": "Study", "summary": "A bounded example.", "url": "https://example.com"}],
            "current_draft": "Old draft text.", "revision_notes": "The post missed my point.",
            "current_brief": "Reader question: How can AI help recover undocumented system logic?",
            "claim_reviews": [{"claim": "A broad claim", "status": "unsupported", "reason": "No evidence.",
                               "evidence_excerpt": "", "source_ids": ["study"], "checked_by_user": False,
                               "reviewer_note": "Narrow this claim.", "revision_action": "rewrite"}],
        }
        prompt = build_prompt(payload)
        self.assertIn("Old draft text.", prompt)
        self.assertIn("How can AI help recover undocumented system logic?", prompt)
        self.assertIn("The post missed my point.", prompt)
        self.assertIn("Narrow this claim.", prompt)
        self.assertIn("Requested action: rewrite", prompt)
        self.assertIn("Treat AI audit labels only as pointers, not proof", prompt)

    def test_hashtag_preferences_are_applied_without_inventing_claims(self):
        draft = "A grounded post."
        self.assertEqual(apply_hashtags(draft, {"hashtag_mode": "off"}), draft)
        custom = apply_hashtags(draft, {"hashtag_mode": "custom", "hashtag_count": 2, "custom_hashtags": "#AI, #ReverseEngineering, #Extra"})
        self.assertTrue(custom.endswith("#AI #ReverseEngineering"))
        automatic = apply_hashtags(draft, {"hashtag_mode": "auto", "hashtag_count": 2, "topic": "AI-assisted reverse engineering"})
        self.assertEqual(len(automatic.split("\n\n")[-1].split()), 2)
        fifteen = apply_hashtags(draft, {"hashtag_mode": "custom", "hashtag_count": 15, "custom_hashtags": ", ".join(f"#Topic{n}" for n in range(1, 17))})
        self.assertEqual(len(fifteen.split("\n\n")[-1].split()), 15)
    def test_source_audit_can_be_skipped_without_claiming_verification(self):
        calls = []
        def fake_call(url, body):
            calls.append(body)
            return {"message": {"content": json.dumps(valid_output())}}
        payload = {"topic": "A useful topic", "reader": "General readers", "question": "What matters?", "useful_outcome": "Understand the issue", "writer_notes": "", "claim_to_check": "", "evidence": [], "audit_sources": False}
        result = generate(payload, model_call=fake_call, quality_review_enabled=False)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["claim_audit_status"], "skipped")
        self.assertIn("chose not to run", result["notice"])

    def test_internal_evaluation_attribution_is_unsupported_without_evaluator_evidence(self):
        payload = {"claim_to_check": "These benchmarks are internal evaluations.", "evidence": [{"id": "model-card", "title": "Gemini 4 Argon model card", "summary": "The model was evaluated across coding and reasoning benchmarks."}]}
        output = {"claim_reviews": [{"claim": payload["claim_to_check"], "status": "supported", "reason": "The source lists benchmark results.", "evidence_excerpt": "evaluated across coding", "source_ids": ["model-card"]}]}
        result = _apply_known_claim_boundary(output, payload)
        row = result["claim_reviews"][0]
        self.assertEqual(row["status"], "unsupported")
        self.assertEqual(row["evidence_excerpt"], "")
        self.assertIn("do not identify who ran", row["reason"])

    def test_non_independent_replication_note_does_not_support_internal_evaluation_claim(self):
        claim = "Google states these benchmarks are internal evaluations."
        payload = {"claim_to_check": claim, "evidence": [{"id": "model-card", "title": "Gemini model card", "summary": "These are Google's reported evaluations, not independent replications."}]}
        output = {"claim_reviews": [{"claim": claim, "status": "supported", "reason": "The card reports results.", "evidence_excerpt": "reported evaluations", "source_ids": ["model-card"]}]}
        result = _apply_known_claim_boundary(output, payload)
        self.assertEqual(result["claim_reviews"][0]["status"], "unsupported")

    def test_explicit_internal_evaluation_note_can_support_internal_attribution(self):
        claim = "These benchmarks are internal evaluations."
        payload = {"claim_to_check": claim, "evidence": [{"id": "model-card", "title": "Gemini model card", "summary": "The listed benchmarks are internal evaluations."}]}
        output = {"claim_reviews": [{"claim": claim, "status": "supported", "reason": "The note says so.", "evidence_excerpt": "internal evaluations", "source_ids": ["model-card"]}]}
        result = _apply_known_claim_boundary(output, payload)
        self.assertEqual(result["claim_reviews"][0]["status"], "supported")

    def test_draft_format_retries_one_paragraph_and_uses_revised_text(self):
        payload = {"topic": "Software documentation", "reader": "Developers", "question": "What helps?", "useful_outcome": "Review documentation",
                   "writer_notes": "", "claim_to_check": "", "evidence": [], "audit_sources": False,
                   "target_words_min": 100, "target_words_max": 180, "paragraphs_min": 2, "paragraphs_max": 3,
                   "sentences_min": 2, "sentences_max": 4}
        calls = []
        def fake_call(url, body):
            calls.append(body)
            output = {**valid_output(), "post_draft": "One paragraph only."} if len(calls) == 1 else {"paragraphs": [paragraph.split(". ") for paragraph in COMPLIANT_DRAFT.split("\n\n")]}
            if len(calls) == 2:
                output["paragraphs"] = [[sentence if sentence.endswith(".") else sentence + "." for sentence in paragraph] for paragraph in output["paragraphs"]]
            return {"message": {"content": json.dumps(output)}}
        result = generate(payload, model_call=fake_call, quality_review_enabled=False)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["post_draft"], COMPLIANT_DRAFT)
        self.assertIn("Revise only the post draft", calls[1]["messages"][1]["content"])

    def test_draft_format_rejects_still_invalid_revision(self):
        payload = {"topic": "Software documentation", "reader": "Developers", "question": "What helps?", "useful_outcome": "Review documentation",
                   "writer_notes": "", "claim_to_check": "", "evidence": [], "audit_sources": False}
        calls = 0
        def fake_call(url, body):
            nonlocal calls
            calls += 1
            output = {**valid_output(), "post_draft": "Still one paragraph."} if calls == 1 else {"paragraphs": [["Still one paragraph."]]}
            return {"message": {"content": json.dumps(output)}}
        with self.assertRaisesRegex(InvalidModelOutput, "still misses"):
            generate(payload, model_call=fake_call, quality_review_enabled=False)

    def test_revision_format_retry_expands_short_candidate_and_keeps_claim_actions(self):
        payload = {
            "topic": "Software documentation", "reader": "Developers", "question": "What helps?", "useful_outcome": "Review documentation",
            "writer_notes": "", "claim_to_check": "", "evidence": [{"id": "doc", "title": "Documentation notes", "summary": "Keep claims tied to code evidence."}],
            "audit_sources": False, "previous_draft": "A different original version.", "revision_notes": "Rewrite all claims carefully.",
            "claim_reviews": [{"claim": "A broad claim", "revision_action": "rewrite", "reviewer_note": "Do not imply internal testing without evidence."}],
            "target_words_min": 140, "target_words_max": 180, "paragraphs_min": 2, "paragraphs_max": 3,
            "sentences_min": 2, "sentences_max": 5,
        }
        expanded = COMPLIANT_DRAFT.replace("and change.", "and changing requirements over time.").replace(
            "A useful documentation effort starts", "For readers, clear examples make the explanation easier to apply across teams. A useful documentation effort starts"
        )
        self.assertFalse(draft_format_issues(expanded, payload))
        calls = []
        def fake_call(url, body):
            calls.append(body)
            if len(calls) == 1:
                return {"message": {"content": json.dumps(valid_output())}}
            if len(calls) == 2:
                return {"message": {"content": json.dumps({"paragraphs": [["AI can help with reviews.", "People still need to verify claims."], ["Clear evidence is useful.", "Short notes can preserve context."]]})}}
            if len(calls) == 3:
                paragraphs = [[sentence.strip() + ("." if not sentence.strip().endswith(".") else "") for sentence in part.split(". ")] for part in expanded.split("\n\n")]
                return {"message": {"content": json.dumps({"paragraphs": paragraphs})}}
            self.fail("Unexpected extra model request")
        result = generate(payload, model_call=fake_call, quality_review_enabled=False)
        self.assertEqual(len(calls), 3)
        self.assertEqual(result["post_draft"], expanded)
        self.assertIn("at least", calls[2]["messages"][1]["content"])
        self.assertIn("Do not imply internal testing without evidence", calls[2]["messages"][1]["content"])
        self.assertIn("Rewrite all claims carefully", calls[2]["messages"][1]["content"])

    def test_revision_retries_if_first_model_response_copies_existing_draft(self):
        payload = {
            "topic": "Software documentation", "reader": "Developers", "question": "What helps?", "useful_outcome": "Review documentation",
            "writer_notes": "", "claim_to_check": "", "evidence": [], "audit_sources": False,
            "current_draft": "A sentence with an unsupported claim.", "revision_notes": "Rewrite all claims carefully.",
            "claim_reviews": [{"claim": "A sentence with an unsupported claim.", "revision_action": "rewrite", "reviewer_note": "Narrow this to the evidence."}],
            "target_words_min": 50, "target_words_max": 200, "paragraphs_min": 1, "paragraphs_max": 4,
            "sentences_min": 1, "sentences_max": 8,
        }
        calls = []
        def fake_call(url, body):
            calls.append(body)
            response = valid_output()
            response["post_draft"] = payload["current_draft"] if len(calls) == 1 else COMPLIANT_DRAFT
            return {"message": {"content": json.dumps(response)}}
        result = generate(payload, model_call=fake_call, quality_review_enabled=False)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["post_draft"], COMPLIANT_DRAFT)
        self.assertIn("genuinely revised complete post", calls[1]["messages"][1]["content"])
        self.assertIn("Narrow this to the evidence", calls[1]["messages"][1]["content"])

    def test_known_ps5_claim_is_contradicted_by_the_supplied_timeline(self):
        payload = {"claim_to_check": "AI discovered the PS5 jailbreak", "evidence": [{"id": "ps5-homebrew"}]}
        output = valid_output()
        output["claim_reviews"] = [{"claim": payload["claim_to_check"], "status": "supported", "reason": "model guess", "source_ids": []}]
        checked = _apply_known_claim_boundary(output, payload)
        self.assertEqual(checked["claim_reviews"][0]["status"], "contradicted")
        self.assertIn("already jailbroken", checked["claim_reviews"][0]["reason"])
        self.assertIn("already jailbroken", checked["claim_reviews"][0]["evidence_excerpt"])

    def test_ps5_homebrew_claim_is_not_misclassified_as_the_overclaim(self):
        self.assertFalse(_is_known_ps5_overclaim("Claude helped create a homebrew app for an already-jailbroken PS5"))

    def test_missing_fields_are_rejected(self):
        with self.assertRaises(InvalidModelOutput):
            _validate_output({"post_draft": "text"})

    def test_unknown_source_ids_cannot_appear_as_supported_citations(self):
        output = valid_output()
        output["claim_reviews"] = [{"claim": "Example", "status": "supported", "reason": "Looks right", "source_ids": ["made-up-source"]}]
        checked = _validate_output(output, {"real-source"})
        self.assertEqual(checked["claim_reviews"][0]["status"], "needs_review")
        self.assertEqual(checked["claim_reviews"][0]["source_ids"], [])

    def test_supported_claim_requires_known_source_and_excerpt(self):
        row = {"claim": "Fact", "status": "supported", "reason": "Direct support", "evidence_excerpt": "Evidence phrase", "source_ids": ["known"]}
        checked = _validate_claim_reviews({"claim_reviews": [row]}, {"known"})
        self.assertEqual(checked[0]["status"], "supported")

    def test_supported_claim_without_excerpt_needs_review(self):
        row = {"claim": "Fact", "status": "supported", "reason": "Direct support", "evidence_excerpt": "", "source_ids": ["known"]}
        checked = _validate_claim_reviews({"claim_reviews": [row]}, {"known"})
        self.assertEqual(checked[0]["status"], "needs_review")

    def test_claim_review_prompt_checks_full_draft_and_separates_false_from_unsupported(self):
        prompt = build_claim_review_prompt({"evidence": [], "claim_to_check": "requested"}, "The full draft says X.")
        self.assertIn("The full draft says X.", prompt)
        self.assertIn("This does not mean the claim is false", prompt)
        self.assertIn("scope inflation", prompt)

    def test_generate_parses_structured_ollama_response(self):
        payload = {
            "topic": "AI-assisted reverse engineering",
            "reader": "General readers",
            "question": "What changes for software trust?",
            "useful_outcome": "Understand the role of AI assistance",
            "writer_notes": "",
            "claim_to_check": "",
            "evidence": [{"id": "fps", "title": "FPS decompilation", "summary": "Creator's account", "url": "https://example.com"}],
        }
        calls = []
        def fake_call(url, body):
            calls.append(body)
            self.assertTrue(url.endswith("/api/chat"))
            self.assertIn(body["options"]["num_ctx"], {4096, 2048, 3072})
            self.assertFalse(body["think"])
            self.assertIn(body["options"]["num_predict"], {1400, 1200, 1600})
            if len(calls) == 1:
                return {"message": {"content": json.dumps(valid_output())}}
            self.assertIn("Complete draft:", body["messages"][1]["content"])
            return {"message": {"content": json.dumps({"claim_reviews": [{
                "claim": "AI can assist with reverse engineering", "status": "supported",
                "reason": "Source describes AI-assisted analysis", "evidence_excerpt": "AI-assisted decompilation",
                "source_ids": ["fps"],
            }]})}}
        result = generate(payload, model_call=fake_call, quality_review_enabled=False)
        self.assertIn("post_draft", result)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["claim_reviews"][0]["status"], "supported")
        self.assertEqual(result["claim_audit_status"], "complete")
        self.assertIn("not necessarily false", result["notice"])

    def test_draft_is_preserved_when_audit_output_is_invalid(self):
        payload = {"topic": "Topic", "reader": "Reader", "question": "Question", "useful_outcome": "Outcome",
                   "writer_notes": "", "claim_to_check": "", "audit_sources": True,
                   "evidence": [{"id": "src", "title": "Source", "summary": "Evidence note", "url": "https://example.com"}]}
        calls = 0
        def fake_call(url, body):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"message": {"content": json.dumps(valid_output())}}
            return {"message": {"content": "{}"}}
        result = generate(payload, model_call=fake_call, quality_review_enabled=False)
        self.assertEqual(result["post_draft"], valid_output()["post_draft"])
        self.assertEqual(result["claim_audit_status"], "unavailable")
        self.assertEqual(calls, 3)
        self.assertTrue(result["claim_reviews"])
        self.assertTrue(all(row["status"] == "needs_review" for row in result["claim_reviews"]))
        self.assertIn("no claim is verified", result["notice"])

    def test_audit_retry_can_recover_and_remain_complete(self):
        payload = {"topic": "Topic", "reader": "Reader", "question": "Question", "useful_outcome": "Outcome",
                   "writer_notes": "", "claim_to_check": "", "audit_sources": True,
                   "evidence": [{"id": "src", "title": "Source", "summary": "Evidence note", "url": "https://example.com"}]}
        calls = 0
        def fake_call(url, body):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"message": {"content": json.dumps(valid_output())}}
            if calls == 2:
                return {"message": {"content": "{}"}}
            return {"message": {"content": json.dumps({"claim_reviews": [{
                "claim": "A factual claim", "status": "needs_review", "reason": "Check the page",
                "evidence_excerpt": "", "source_ids": [],
            }]})}}
        result = generate(payload, model_call=fake_call, quality_review_enabled=False)
        self.assertEqual(calls, 3)
        self.assertEqual(result["claim_audit_status"], "complete")

    def test_empty_audit_is_not_reported_as_complete(self):
        payload = {"topic": "Topic", "reader": "Reader", "question": "Question", "useful_outcome": "Outcome",
                   "writer_notes": "", "claim_to_check": "", "audit_sources": True,
                   "evidence": [{"id": "src", "title": "Source", "summary": "Evidence note", "url": "https://example.com"}]}
        calls = 0
        def fake_call(url, body):
            nonlocal calls
            calls += 1
            response = valid_output() if calls == 1 else {"claim_reviews": []}
            return {"message": {"content": json.dumps(response)}}
        result = generate(payload, model_call=fake_call, quality_review_enabled=False)
        self.assertEqual(calls, 3)
        self.assertEqual(result["claim_audit_status"], "unavailable")
        self.assertTrue(result["claim_reviews"])

    def test_prompt_respects_arbitrary_user_topic(self):
        from app.service import build_prompt
        payload = {"topic": "Community gardening", "reader": "Neighbors", "question": "How can we begin?",
                   "useful_outcome": "Start a garden", "writer_notes": "", "claim_to_check": "", "evidence": []}
        prompt = build_prompt(payload)
        self.assertIn("Community gardening", prompt)
        self.assertNotIn("reverse engineering", prompt)

    def test_build_prompt_includes_writer_composition_controls(self):
        from app.service import build_prompt
        payload = {
            "topic": "Topic", "reader": "Reader", "question": "Question", "useful_outcome": "Outcome",
            "writer_notes": "", "claim_to_check": "", "evidence": [],
            "target_words_min": 100, "target_words_max": 150, "paragraphs_min": 3, "paragraphs_max": 5,
            "sentences_min": 2, "sentences_max": 3, "paragraph_style": "narrative",
            "sentence_style": "short_direct", "overall_tone": "reflective", "custom_style": "Use a warm opening",
            "add_imperfections": True, "imperfection_level": "light",
        }
        prompt = build_prompt(payload)
        self.assertIn("100–150 words", prompt)
        self.assertIn("3–5 distinct paragraphs", prompt)
        self.assertIn("Use a simple progression", prompt)
        self.assertIn("Use a warm opening", prompt)
        self.assertIn("Never alter facts", prompt)


if __name__ == "__main__":
    unittest.main()
