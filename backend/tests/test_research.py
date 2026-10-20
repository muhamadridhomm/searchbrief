import unittest

from app.research import ResearchUnavailable, _fanout, _rank_sources, plan_queries, recheck_page, recheck_publication, research_sources, search_github_repositories, search_openalex, search_pages, search_publications, search_saved_sources, search_stackexchange


class ResearchTests(unittest.TestCase):
    def test_saved_sources_are_ranked_by_topic_without_approval(self):
        sources = [
            {"id": "relevant", "title": "AI reverse engineering", "summary": "Software analysis and binary inspection", "url": "https://example.com/one"},
            {"id": "unrelated", "title": "Community gardening", "summary": "Planting and soil preparation", "url": "https://example.com/two"},
        ]
        result = search_saved_sources("AI reverse engineering", "software analysis", ["reverse engineering"], sources)
        self.assertEqual([item["id"] for item in result], ["relevant"])
        self.assertEqual(result[0]["origin"], "Saved on this device")
        self.assertNotIn("approved", result[0])
    def test_ai_queries_are_used_without_treating_them_as_sources(self):
        def fake_model(url, body):
            self.assertIn("/api/chat", url)
            return {"message": {"content": '{"queries": ["reverse engineering", "software decompilation"]}'}}
        queries, planner = plan_queries("Reverse engineering", "What changes?", model_call=fake_model)
        self.assertEqual(queries[0], "Reverse engineering")
        self.assertIn("software decompilation", queries)
        self.assertEqual(planner, "local AI")

    def test_github_repositories_are_topic_matched_and_labeled_as_artifacts(self):
        def fake_fetch(url):
            self.assertIn("api.github.com/search/repositories", url)
            return {"items": [
                {"full_name": "example/ai-reverse-engineering", "html_url": "https://github.com/example/ai-reverse-engineering", "description": "AI-assisted reverse engineering of legacy software", "topics": ["reverse-engineering"], "language": "Python", "stargazers_count": 12, "forks_count": 2, "updated_at": "2026-10-01T00:00:00Z"},
                {"full_name": "example/gardening", "html_url": "https://github.com/example/gardening", "description": "Urban garden tools", "topics": ["plants"], "stargazers_count": 500, "forks_count": 70},
            ]}
        result = search_github_repositories("AI-assisted reverse engineering", "legacy software", fetch=fake_fetch)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["provider"], "GitHub")
        self.assertEqual(result[0]["evidence_type"], "Code repository")
        self.assertIn("not correctness checks", result[0]["summary"])

    def test_sources_only_use_retrieved_pages_and_exact_urls(self):
        calls = []
        def fake_fetch(url):
            calls.append(url)
            return {"query": {"pages": [
                {"pageid": 42, "title": "Reverse engineering", "extract": "Reverse engineering is the process of analyzing a system to identify its components and relationships."},
                {"pageid": 43, "title": "Empty", "extract": "short"},
            ]}}
        sources = search_pages("Reverse engineering", "What changes?", fetch=fake_fetch)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["url"], "https://en.wikipedia.org/wiki/Reverse_engineering")
        self.assertIn("analyzing a system", sources[0]["summary"])
        self.assertEqual(len(calls), 2)

    def test_recheck_flags_changed_extract_and_rejects_other_source_ids(self):
        def fake_fetch(url):
            return {"query": {"pages": [{"extract": "A newly revised article contains different text with enough context to read."}]}}
        result = recheck_page("wikipedia-42", "An old note about this article.", fetch=fake_fetch)
        self.assertEqual(result["status"], "changed")
        with self.assertRaises(ValueError):
            recheck_page("https://example.com/private", "note", fetch=fake_fetch)

    def test_topic_matched_publications_precede_encyclopedia(self):
        def fake_fetch(url):
            self.assertIn("query.bibliographic=AI-assisted+reverse+engineering", url)
            return {"message": {"items": [
                {"DOI": "10.1234/specific", "title": ["AI-assisted reverse engineering of software"],
                 "abstract": "<jats:p>This study examines AI-assisted reverse engineering with a bounded software case study and discusses verification of the results.</jats:p>",
                 "published": {"date-parts": [[2025, 2, 1]]}, "container-title": ["Research Journal"]},
                {"DOI": "10.1234/unrelated", "title": ["Gardening and urban soil"],
                 "abstract": "<p>This unrelated paper has a long abstract about planting crops and maintaining healthy soil for urban garden projects.</p>"},
            ]}}
        papers = search_publications("AI-assisted reverse engineering", fetch=fake_fetch)
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["provider"], "Crossref")
        self.assertEqual(papers[0]["url"], "https://doi.org/10.1234/specific")
        combined, provider = research_sources("AI-assisted reverse engineering", "Why?", publication_search=lambda *args, **kwargs: papers,
                                              encyclopedia_search=lambda topic, question, queries: [{"id": "wikipedia-1", "provider": "Wikipedia"}],
                                              repository_search=lambda topic, question, queries=None: [],
                                              openalex_search=lambda *args, **kwargs: [], community_search=lambda *args, **kwargs: [])
        self.assertEqual(combined[0]["provider"], "Crossref")
        self.assertEqual(provider, "Crossref + Wikipedia")

    def test_openalex_abstract_and_technical_q_and_a_are_found_and_ranked(self):
        abstract = "AI-assisted reverse engineering studies software analysis, extracting program behavior and evaluating human verification of recovered logic."
        def fake_openalex(url):
            self.assertIn("api.openalex.org/works", url)
            return {"results": [{"id": "https://openalex.org/W1", "title": "AI reverse engineering", "doi": "https://doi.org/10.1234/example", "publication_year": 2025, "abstract_inverted_index": {word: [index] for index, word in enumerate(abstract.split())}}]}
        works = search_openalex("AI reverse engineering", fetch=fake_openalex)
        self.assertEqual(works[0]["provider"], "OpenAlex")
        def fake_stack(url):
            self.assertIn("api.stackexchange.com", url)
            return {"items": [{"question_id": 7, "title": "How does AI reverse engineering analyze software?", "link": "https://stackoverflow.com/questions/7/example", "body": "<p>What methods support reverse engineering software analysis?</p>", "score": 9, "answer_count": 2}]}
        discussions = search_stackexchange("AI reverse engineering", fetch=fake_stack)
        self.assertEqual(discussions[0]["provider"], "Stack Exchange")
        ranked = research_sources("AI reverse engineering", "software analysis", publication_search=lambda *args, **kwargs: [], encyclopedia_search=lambda *args, **kwargs: [], repository_search=lambda *args, **kwargs: [], openalex_search=lambda *args, **kwargs: works, community_search=lambda *args, **kwargs: discussions)
        self.assertGreater(ranked[0][0]["ranking_score"], 0)
        self.assertIn("proves truth", ranked[0][0]["ranking_note"])

    def test_query_planner_keeps_exact_topic_and_ranker_drops_weak_noise(self):
        def fake_model(url, body):
            return {"message": {"content": '{"queries":["unrelated broad AI trends","reverse engineering tools"]}'}}
        queries, _ = plan_queries("Gemini 4 Argon", "What capabilities are documented?", model_call=fake_model)
        self.assertEqual(queries[0], "Gemini 4 Argon")
        ranked = _rank_sources([
            {"id": "right", "title": "Gemini 4 Argon model card", "summary": "Gemini 4 Argon capability details and evaluation limits", "provider": "Google"},
            {"id": "noise", "title": "AI trends in workplace hiring", "summary": "A discussion of hiring and workforce planning", "provider": "Crossref"},
        ], "Gemini 4 Argon", "What capabilities are documented?")
        self.assertEqual([source["id"] for source in ranked], ["right"])
        self.assertEqual(ranked[0]["match_quality"], "strong")

    def test_provider_query_fanout_tolerates_one_failed_variation_but_reports_total_failure(self):
        def search(query):
            if query.endswith("bad"):
                raise ResearchUnavailable("offline")
            return [{"title": query}]
        self.assertEqual(_fanout(["good", "bad"], search), [{"title": "good"}])
        with self.assertRaises(ResearchUnavailable):
            _fanout(["bad", "also bad"], search)

    def test_crossref_recheck_matches_doi_and_detects_changes(self):
        paper = search_publications("AI reverse engineering", fetch=lambda url: {"message": {"items": [{
            "DOI": "10.1234/specific", "title": ["AI reverse engineering"],
            "abstract": "<p>An abstract with enough detail about AI reverse engineering and a bounded case study that readers can examine carefully.</p>"
        }]}})[0]
        result = recheck_publication(paper["id"], paper["url"], paper["summary"],
                                     fetch=lambda url: {"message": {"abstract": "<p>Changed abstract text.</p>"}})
        self.assertEqual(result["status"], "changed")
        with self.assertRaises(ValueError):
            recheck_publication(paper["id"], "https://example.com/private", paper["summary"], fetch=lambda url: {})
