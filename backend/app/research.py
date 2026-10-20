"""Retrieve topic-specific research records and technical artifacts."""

from __future__ import annotations

import json
import hashlib
import html
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .service import ModelUnavailable, OLLAMA_MODEL, OLLAMA_URL, _post_json

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
CROSSREF_API = "https://api.crossref.org/works"
GITHUB_SEARCH_API = "https://api.github.com/search/repositories"
OPENALEX_API = "https://api.openalex.org/works"
STACKEXCHANGE_API = "https://api.stackexchange.com/2.3/search/advanced"
USER_AGENT = "SearchBriefLocal/0.1 (local personal research app)"


class ResearchUnavailable(RuntimeError):
    pass


def fetch_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=12) as response:
            return json.load(response)
    except Exception as exc:
        raise ResearchUnavailable("Could not reach the public research source. Try again when online.") from exc


def plan_queries(topic: str, question: str, *, model_call: Callable[..., dict[str, Any]] = _post_json) -> tuple[list[str], str]:
    """Ask local Ollama for search phrases; fall back visibly if it is offline."""
    try:
        response = model_call(f"{OLLAMA_URL}/api/chat", {
            "model": OLLAMA_MODEL, "stream": False, "think": False,
            "format": {"type": "object", "properties": {"queries": {"type": "array", "items": {"type": "string"}}}, "required": ["queries"]},
            "options": {"num_ctx": 1024, "num_predict": 128, "temperature": 0.1},
            "messages": [
                {"role": "system", "content": "Suggest three short search queries that preserve the user's specific topic and reader question. They will be used to find research publications, software repositories, and background pages. Do not invent sources or claims. Return JSON only."},
                {"role": "user", "content": f"Topic: {topic}\nReader question: {question}"},
            ],
        })
        raw = json.loads(response["message"]["content"])
        queries = [value.strip()[:120] for value in raw.get("queries", []) if isinstance(value, str) and value.strip()]
        if queries:
            # Always include the exact topic so a small query-planning model cannot
            # accidentally steer every provider away from the user's subject.
            return _query_set(topic, question, queries, limit=5), "local AI"
    except (ModelUnavailable, KeyError, TypeError, ValueError, json.JSONDecodeError):
        pass
    return _query_set(topic, question, [], limit=3), "keyword fallback"


def search_pages(topic: str, question: str, *, queries: list[str] | None = None, fetch: Callable[[str], dict[str, Any]] = fetch_json) -> list[dict[str, Any]]:
    """Search Wikipedia; each note comes from its retrieved page extract."""
    queries = _query_set(topic, question, queries, limit=5)
    seen: set[int] = set()
    found: list[dict[str, Any]] = []
    topic_terms = _topic_terms(topic)
    for query in queries:
        if not query:
            continue
        url = WIKIPEDIA_API + "?" + urlencode({
            "action": "query", "generator": "search", "gsrsearch": query[:240],
            "gsrlimit": 6, "prop": "extracts", "explaintext": 1, "exintro": 1,
            "redirects": 1, "format": "json", "formatversion": 2,
        })
        data = fetch(url)
        pages = data.get("query", {}).get("pages", [])
        if not isinstance(pages, list):
            continue
        for page in pages:
            if not isinstance(page, dict):
                continue
            pageid, title, extract = page.get("pageid"), page.get("title"), page.get("extract")
            if not isinstance(pageid, int) or pageid in seen or not isinstance(title, str) or not isinstance(extract, str):
                continue
            clean = re.sub(r"\s+", " ", extract).strip()
            if len(clean) < 60:
                continue
            if topic_terms and len(topic_terms & _topic_terms(title + " " + clean[:500])) < min(2, len(topic_terms)):
                continue
            seen.add(pageid)
            found.append({
                "id": f"wikipedia-{pageid}", "title": title[:180],
                "summary": clean[:1200],
                "url": f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "provider": "Wikipedia",
                "evidence_type": "Background reference",
                "evidence_rank": 3,
                "credibility_note": "Useful for orientation; prefer primary research or official documentation for factual claims.",
            })
            if len(found) >= 6:
                return found
    return found


def _plain_abstract(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def _topic_terms(topic: str) -> set[str]:
    stop = {"the", "and", "for", "with", "from", "into", "about", "using", "how", "what", "why", "does", "help", "can", "could", "would", "this", "that", "yang", "dan", "untuk", "dengan", "tentang", "cara", "pada", "ai"}
    return {word for word in re.findall(r"[a-z0-9]+", topic.casefold()) if len(word) > 2 and word not in stop}


def _search_focus_text(question: str) -> str:
    """Keep reader/context labels out of provider relevance checks."""
    lines = [line.strip() for line in question.splitlines() if line.strip()]
    selected = [line.split(":", 1)[1].strip() for line in lines if line.startswith(("Reader question:", "Useful outcome:")) and ":" in line]
    return " ".join(selected) if selected else question


def _query_set(topic: str, question: str, planned: list[str] | None = None, *, limit: int = 5) -> list[str]:
    """Keep an exact-topic query in the fan-out; model suggestions are additive, never authoritative."""
    candidates = [topic, _search_focus_text(question), *(planned or [])]
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        cleaned = re.sub(r"\s+", " ", candidate).strip(" \n\t,.;")[:180]
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def _fanout(queries: list[str], search_one: Callable[[str], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Run a provider's query variations concurrently and tolerate individual failures."""
    def safe_search(query: str) -> list[dict[str, Any]] | None:
        try:
            return search_one(query)
        except ResearchUnavailable:
            return None
    with ThreadPoolExecutor(max_workers=min(5, max(1, len(queries)))) as pool:
        groups = list(pool.map(safe_search, queries))
    if groups and all(group is None for group in groups):
        raise ResearchUnavailable("All query variants failed for this public research provider.")
    return [item for group in groups if group for item in group]


def search_saved_sources(topic: str, question: str, queries: list[str], saved_sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank previously saved notes using locally planned terms; never auto-approve them."""
    topic_terms = _topic_terms(topic)
    other_terms = _topic_terms(_search_focus_text(question) + " " + " ".join(queries)) - topic_terms
    ranked = []
    for source in saved_sources:
        title_terms = _topic_terms(source.get("title", ""))
        note_terms = _topic_terms(source.get("summary", ""))
        topic_hits = topic_terms & (title_terms | note_terms)
        if topic_terms and len(topic_hits) < min(2, len(topic_terms)):
            continue
        score = 3 * len(topic_terms & title_terms) + len(topic_hits) + len(other_terms & (title_terms | note_terms))
        if score:
            ranked.append((score, {**source, "origin": "Saved on this device"}))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return _rank_sources([source for _, source in ranked[:12]], topic, question)


def search_publications(topic: str, question: str = "", queries: list[str] | None = None, *, fetch: Callable[[str], dict[str, Any]] = fetch_json) -> list[dict[str, Any]]:
    """Search title-matched Crossref works that have a retrieved abstract."""
    def search_one(query: str) -> list[dict[str, Any]]:
        url = CROSSREF_API + "?" + urlencode({
            "query.bibliographic": query, "filter": "has-abstract:true", "rows": 15,
            "select": "DOI,title,abstract,published,URL,container-title",
        })
        return fetch(url).get("message", {}).get("items", [])
    items = _fanout(_query_set(topic, question, queries, limit=5), search_one)
    terms = _topic_terms(topic)
    focus_terms = _topic_terms(_search_focus_text(question)) - terms
    found = []
    seen: set[str] = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        doi, titles, raw_abstract = item.get("DOI"), item.get("title"), item.get("abstract")
        if not isinstance(doi, str) or not isinstance(titles, list) or not titles or not isinstance(titles[0], str) or not isinstance(raw_abstract, str):
            continue
        if doi.casefold() in seen:
            continue
        title = _plain_abstract(titles[0])
        abstract = _plain_abstract(raw_abstract)
        title_terms = _topic_terms(title)
        matched = terms & title_terms
        if len(abstract) < 100 or (terms and len(matched) < min(2, len(terms))):
            continue
        if focus_terms and not (focus_terms & _topic_terms(title + " " + abstract)):
            continue
        containers = item.get("container-title") or []
        venue = containers[0] if isinstance(containers, list) and containers and isinstance(containers[0], str) else "Research publication"
        found.append({
            "id": "crossref-" + hashlib.sha256(doi.lower().encode()).hexdigest()[:16],
            "title": title[:180], "summary": abstract[:1200],
            "url": "https://doi.org/" + quote(doi, safe="/"),
            "retrieved_at": datetime.now(timezone.utc).isoformat(), "provider": "Crossref",
            "venue": venue[:120], "publication_date": str(item.get("published", {}).get("date-parts", [[""]])[0][0]),
            "relevance": len(matched), "evidence_type": "Research record", "evidence_rank": 1,
            "credibility_note": "A DOI and abstract were retrieved from a scholarly index; verify the venue, methods, and full paper. This does not prove peer review or correctness.",
        })
        seen.add(doi.casefold())
    found.sort(key=lambda source: source["relevance"], reverse=True)
    for source in found:
        source.pop("relevance")
    return found[:10]


def search_github_repositories(topic: str, question: str = "", queries: list[str] | None = None,
                               *, fetch: Callable[[str], dict[str, Any]] = fetch_json) -> list[dict[str, Any]]:
    """Search public GitHub repositories; popularity/activity are not correctness checks."""
    terms = _query_set(topic, question, queries, limit=5)
    topic_terms = _topic_terms(topic)
    found = []
    def search_one(term: str) -> list[dict[str, Any]]:
        query = f"{term[:150]} in:name,description,readme"
        data = fetch(GITHUB_SEARCH_API + "?" + urlencode({"q": query, "sort": "stars", "order": "desc", "per_page": 15}))
        return data.get("items", []) if isinstance(data.get("items", []), list) else []
    items = _fanout(terms, search_one)
    seen: set[str] = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        full_name, html_url = item.get("full_name"), item.get("html_url")
        if not isinstance(full_name, str) or not isinstance(html_url, str):
            continue
        if full_name.casefold() in seen:
            continue
        description = item.get("description") if isinstance(item.get("description"), str) else ""
        topics = item.get("topics") if isinstance(item.get("topics"), list) else []
        language = item.get("language") if isinstance(item.get("language"), str) else ""
        matched = topic_terms & _topic_terms(full_name + " " + description + " " + " ".join(str(value) for value in topics))
        if topic_terms and len(matched) < min(2, len(topic_terms)):
            continue
        stars = item.get("stargazers_count") if isinstance(item.get("stargazers_count"), int) else 0
        forks = item.get("forks_count") if isinstance(item.get("forks_count"), int) else 0
        updated = item.get("updated_at") if isinstance(item.get("updated_at"), str) else ""
        details = [part for part in (description, f"Language: {language}" if language else "", f"Topics: {', '.join(topics[:8])}" if topics else "", f"GitHub reports {stars} stars and {forks} forks; updated {updated[:10] or 'date unavailable'}. These are activity/popularity signals, not correctness checks.") if part]
        found.append({
            "id": "github-" + hashlib.sha256(full_name.casefold().encode()).hexdigest()[:16],
            "title": full_name[:180], "summary": " ".join(details)[:1200], "url": html_url,
            "retrieved_at": datetime.now(timezone.utc).isoformat(), "provider": "GitHub",
            "evidence_type": "Code repository", "evidence_rank": 1,
            "credibility_note": "A primary technical artifact; inspect its owner, README, license, maintenance, and code before relying on it.",
            "relevance": len(matched), "stars": stars, "updated_at": updated,
        })
        seen.add(full_name.casefold())
    found.sort(key=lambda source: (source["relevance"], source["stars"]), reverse=True)
    for source in found:
        source.pop("relevance")
    return found[:10]


def search_openalex(topic: str, question: str = "", queries: list[str] | None = None, *, fetch: Callable[[str], dict[str, Any]] = fetch_json) -> list[dict[str, Any]]:
    """Search OpenAlex scholarly works; indexed records still require paper-level review."""
    def search_one(query: str) -> list[dict[str, Any]]:
        url = OPENALEX_API + "?" + urlencode({"search": query, "per-page": 15, "select": "id,doi,title,publication_year,authorships,primary_location,biblio,abstract_inverted_index"})
        return fetch(url).get("results", [])
    items = _fanout(_query_set(topic, question, queries, limit=5), search_one)
    found = []
    terms = _topic_terms(topic)
    seen: set[str] = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        title = item.get("title") if isinstance(item.get("title"), str) else ""
        abstract = _abstract_from_inverted_index(item.get("abstract_inverted_index"))
        matched = terms & _topic_terms(title + " " + abstract)
        if len(abstract) < 100 or (terms and len(matched) < min(2, len(terms))):
            continue
        doi = item.get("doi") if isinstance(item.get("doi"), str) else ""
        url = doi if doi.startswith("https://doi.org/") else item.get("id", "")
        if not isinstance(url, str) or not url.startswith("https://"):
            continue
        if url.casefold() in seen:
            continue
        location = item.get("primary_location") if isinstance(item.get("primary_location"), dict) else {}
        source = location.get("source") if isinstance(location.get("source"), dict) else {}
        venue = source.get("display_name") if isinstance(source.get("display_name"), str) else ""
        found.append({"id": "openalex-" + hashlib.sha256(url.encode()).hexdigest()[:16], "title": title[:180], "summary": abstract[:1200], "url": url, "retrieved_at": datetime.now(timezone.utc).isoformat(), "provider": "OpenAlex", "venue": venue[:120], "publication_date": str(item.get("publication_year", "")), "evidence_type": "Scholarly work record", "credibility_note": "Scholarly-index metadata and abstract; inspect the paper, methods, venue, and publication status. Indexing is not proof of peer review or correctness."})
        seen.add(url.casefold())
    return found[:10]


def _abstract_from_inverted_index(index: Any) -> str:
    if not isinstance(index, dict):
        return ""
    words: dict[int, str] = {}
    for token, positions in index.items():
        if isinstance(token, str) and isinstance(positions, list):
            for position in positions:
                if isinstance(position, int) and 0 <= position < 20000:
                    words[position] = token
    return " ".join(words[position] for position in sorted(words))


def search_stackexchange(topic: str, question: str = "", queries: list[str] | None = None, *, fetch: Callable[[str], dict[str, Any]] = fetch_json) -> list[dict[str, Any]]:
    """Search Stack Exchange technical Q&A as community evidence, not authoritative proof."""
    def search_one(query: str) -> list[dict[str, Any]]:
        url = STACKEXCHANGE_API + "?" + urlencode({"site": "stackoverflow", "q": query, "sort": "relevance", "order": "desc", "pagesize": 15, "filter": "withbody"})
        return fetch(url).get("items", [])
    items = _fanout(_query_set(topic, question, queries, limit=5), search_one)
    terms = _topic_terms(topic)
    found = []
    seen: set[str] = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        title, link = item.get("title"), item.get("link")
        if not isinstance(title, str) or not isinstance(link, str):
            continue
        if link.casefold() in seen:
            continue
        body = re.sub(r"<[^>]+>", " ", html.unescape(item.get("body", ""))) if isinstance(item.get("body"), str) else ""
        matched = terms & _topic_terms(title + " " + body)
        if terms and len(matched) < min(2, len(terms)):
            continue
        score = item.get("score") if isinstance(item.get("score"), int) else 0
        answers = item.get("answer_count") if isinstance(item.get("answer_count"), int) else 0
        found.append({"id": f"stackexchange-{item.get('question_id', hashlib.sha256(link.encode()).hexdigest()[:12])}", "title": title[:180], "summary": re.sub(r"\s+", " ", body).strip()[:1200] or f"Community question with {answers} answers and score {score}.", "url": link, "retrieved_at": datetime.now(timezone.utc).isoformat(), "provider": "Stack Exchange", "evidence_type": "Technical Q&A", "credibility_note": "Community answers can offer implementation experience or leads; verify factual claims against documentation, code, or research.", "community_score": score, "answer_count": answers})
        seen.add(link.casefold())
    return found[:10]


def _rank_sources(sources: list[dict[str, Any]], topic: str, question: str) -> list[dict[str, Any]]:
    """Score topical fit separately from evidence type; weakly matched results are excluded."""
    topic_terms = _topic_terms(topic)
    focus_terms = _topic_terms(_search_focus_text(question)) - topic_terms
    for source in sources:
        title_terms = _topic_terms(source.get("title", ""))
        content_terms = _topic_terms(source.get("summary", ""))
        all_terms = title_terms | content_terms
        topic_hits = topic_terms & all_terms
        focus_hits = focus_terms & all_terms
        topic_coverage = len(topic_hits) / len(topic_terms) if topic_terms else 0
        focus_coverage = len(focus_hits) / len(focus_terms) if focus_terms else topic_coverage
        title_coverage = len(topic_terms & title_terms) / len(topic_terms) if topic_terms else 0
        relevance = 65 * topic_coverage + 25 * focus_coverage + 10 * title_coverage
        source["topic_match_score"] = round(100 * topic_coverage)
        source["focus_match_score"] = round(100 * focus_coverage)
        source["relevance_score"] = round(relevance)
        source["relevance_label"] = "Topic fit; not a trust score"
        provider = source.get("provider")
        if provider == "Wikipedia":
            source.setdefault("evidence_type", "Background reference")
            source.setdefault("evidence_rank", 3)
            source.setdefault("credibility_note", "Use for orientation, not as a substitute for primary evidence.")
        elif provider == "Crossref":
            source.setdefault("evidence_type", "Research record")
            source.setdefault("evidence_rank", 1)
            source.setdefault("credibility_note", "Verify the venue, methods, and full paper; index metadata alone does not prove correctness.")
        elif provider == "GitHub":
            source.setdefault("evidence_type", "Code repository")
            source.setdefault("evidence_rank", 1)
            source.setdefault("credibility_note", "Inspect owner, README, license, maintenance, and code before relying on it.")
        elif provider == "OpenAlex":
            source.setdefault("evidence_type", "Scholarly work record")
            source.setdefault("evidence_rank", 1)
            source.setdefault("credibility_note", "Inspect the paper, methods, venue, and publication status; indexing alone is not proof.")
        elif provider == "Stack Exchange":
            source.setdefault("evidence_type", "Technical Q&A")
            source.setdefault("evidence_rank", 3)
            source.setdefault("credibility_note", "Community answers can be useful leads; verify against primary documentation or evidence.")
        elif provider == "Reddit":
            source.setdefault("evidence_type", "Community discussion")
            source.setdefault("evidence_rank", 4)
            source.setdefault("credibility_note", "Anecdotal discussion; use for perspectives or leads, not factual confirmation.")
        elif provider == "User provided":
            source.setdefault("evidence_type", "User-provided notes")
            source.setdefault("evidence_rank", 2)
            source.setdefault("credibility_note", "Check the original material and attribution yourself.")
        source["provenance_signal"] = max(20, 100 - 18 * (source.get("evidence_rank", 4) - 1))
        source["ranking_score"] = source["relevance_score"]
        source["match_quality"] = "strong" if source["relevance_score"] >= 55 and (len(topic_hits) >= 2 or len(topic_terms) <= 1) else "partial" if source["relevance_score"] >= 30 else "weak"
        source["ranking_note"] = "Ranked by topic and reader-question fit. Evidence type is shown separately; neither measure proves truth."
    return sorted((source for source in sources if source["match_quality"] != "weak"), key=lambda source: (source.get("relevance_score", 0), source.get("provenance_signal", 0)), reverse=True)


def research_sources(topic: str, question: str, *, queries: list[str] | None = None,
                     publication_search: Callable[..., list[dict[str, Any]]] = search_publications,
                     encyclopedia_search: Callable[..., list[dict[str, Any]]] = search_pages,
                     repository_search: Callable[..., list[dict[str, Any]]] = search_github_repositories,
                     openalex_search: Callable[..., list[dict[str, Any]]] = search_openalex,
                     community_search: Callable[..., list[dict[str, Any]]] = search_stackexchange) -> tuple[list[dict[str, Any]], str]:
    """Search several independent provider types; rank by relevance and provenance cues."""
    errors = []
    try:
        papers = publication_search(topic, question, queries=queries)
    except ResearchUnavailable as exc:
        papers = []
        errors.append(str(exc))
    try:
        pages = encyclopedia_search(topic, question, queries=queries)
    except ResearchUnavailable as exc:
        pages = []
        errors.append(str(exc))
    try:
        repositories = repository_search(topic, question, queries=queries)
    except ResearchUnavailable as exc:
        repositories = []
        errors.append(str(exc))
    try:
        openalex = openalex_search(topic, question, queries=queries)
    except ResearchUnavailable as exc:
        openalex = []
        errors.append(str(exc))
    try:
        community = community_search(topic, question, queries=queries)
    except ResearchUnavailable as exc:
        community = []
        errors.append(str(exc))
    sources = _rank_sources(papers + repositories + openalex + community + pages, topic, question)[:30]
    if not sources and errors:
        raise ResearchUnavailable("Public research providers are unavailable. Try again when online.")
    providers = " + ".join(name for name, results in (("Crossref", papers), ("OpenAlex", openalex), ("GitHub", repositories), ("Stack Exchange", community), ("Wikipedia", pages)) if results)
    return sources, providers


def recheck_publication(source_id: str, source_url: str, original_summary: str, *, fetch: Callable[[str], dict[str, Any]] = fetch_json) -> dict[str, Any]:
    """Re-fetch one Crossref DOI and compare its abstract with the saved note."""
    from urllib.parse import unquote, urlparse
    parsed = urlparse(source_url)
    if parsed.scheme != "https" or parsed.netloc != "doi.org" or not parsed.path.startswith("/"):
        raise ValueError("Only a DOI source link can be rechecked here.")
    doi = unquote(parsed.path[1:])
    if not re.fullmatch(r"10\.\d{4,9}/[^\s?#]+", doi) or source_id != "crossref-" + hashlib.sha256(doi.lower().encode()).hexdigest()[:16]:
        raise ValueError("The source ID does not match its DOI link.")
    data = fetch(CROSSREF_API + "/" + quote(doi, safe=""))
    current = _plain_abstract(data.get("message", {}).get("abstract", ""))[:1200]
    if not current:
        return {"status": "unavailable", "message": "The publication abstract is unavailable. Open the DOI page to review it.", "excerpt": ""}
    matched = current == _plain_abstract(original_summary)
    return {"status": "matched" if matched else "changed",
            "message": "The saved abstract still matches Crossref metadata; this does not independently verify its claims." if matched else "The publication abstract differs from the saved note. Review the DOI page before approval.",
            "excerpt": current, "retrieved_at": datetime.now(timezone.utc).isoformat()}


def recheck_page(source_id: str, original_summary: str, *, fetch: Callable[[str], dict[str, Any]] = fetch_json) -> dict[str, Any]:
    """Compare a saved note against the page's current extract; no truth guarantee."""
    match = re.fullmatch(r"wikipedia-(\d+)", source_id)
    if not match:
        raise ValueError("This source cannot be rechecked by the Wikipedia connector.")
    url = WIKIPEDIA_API + "?" + urlencode({
        "action": "query", "pageids": match.group(1), "prop": "extracts",
        "explaintext": 1, "exintro": 1, "format": "json", "formatversion": 2,
    })
    pages = fetch(url).get("query", {}).get("pages", [])
    page = pages[0] if isinstance(pages, list) and pages else {}
    current = re.sub(r"\s+", " ", page.get("extract", "")).strip() if isinstance(page, dict) else ""
    if not current:
        return {"status": "unavailable", "message": "The page extract is unavailable. Open the source to review it.", "excerpt": ""}
    old = re.sub(r"\s+", " ", original_summary).strip()
    matched = bool(old) and old == current[:len(old)]
    return {
        "status": "matched" if matched else "changed",
        "message": "The saved note still matches the current page extract. This does not prove the underlying claim is true." if matched else "The page extract differs from the saved note. Review the live page before approval.",
        "excerpt": current[:1200],
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }
