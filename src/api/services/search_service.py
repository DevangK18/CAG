"""
Smart search service — unified search across reports, entities, findings, glossary.

Phase C implementation per §4 of 02_backend_implementation_plan.md.

Orchestrates 5 search channels:
- Reports: rapidfuzz lexical matching
- Ministries: entity graph with type='ministry'
- Entities: entity graph with type != 'ministry'
- Findings: semantic search via retrieval_service
- Glossary: in-memory substring matching
"""

import asyncio
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple

from rapidfuzz import fuzz

from ..models import (
    GroupedSearchResults,
    SearchResultReport,
    SearchResultMinistry,
    SearchResultEntity,
    SearchResultFinding,
    SearchResultGlossary,
)

logger = logging.getLogger(__name__)

# Thread pool for running sync code (findings channel uses sync retrieval)
_executor = ThreadPoolExecutor(max_workers=2)


@dataclass
class ChannelScore:
    """Track top score for a channel."""
    channel: str
    score: float


class SearchService:
    """
    Unified search service for home page smart search.

    Fans out to 5 channels in parallel and merges results.
    """

    def __init__(
        self,
        registry,  # ReportRegistry instance
        entity_service,  # EntityService instance (can be None)
        retrieval_service,  # RetrievalService instance
        glossary_index: Dict[str, List[Dict[str, str]]],  # term_lower -> entries
        config=None,  # RAGConfig for search settings
    ):
        """
        Initialize search service.

        Args:
            registry: ReportRegistry with all reports
            entity_service: EntityService for entity/ministry search (can be None)
            retrieval_service: RetrievalService for findings semantic search
            glossary_index: Pre-built glossary index (term_lower -> entries)
            config: Optional RAGConfig for search settings
        """
        self.registry = registry
        self.entity_service = entity_service
        self.retrieval_service = retrieval_service
        self.glossary_index = glossary_index or {}
        self.config = config

        # Get search config settings
        if config and hasattr(config, 'search'):
            self.fuzzy_threshold = config.search.fuzzy_match_threshold
            self.findings_min_length = config.search.findings_min_query_length
        else:
            self.fuzzy_threshold = 60  # default rapidfuzz cutoff
            self.findings_min_length = 3  # minimum query length for findings

        # Pre-build report search corpus
        self._report_corpus = self._build_report_corpus()

        # Phase E: Manual LRU caches for entity/glossary searches (§15)
        # Using dicts with manual eviction when size > maxsize
        self._ministry_cache: Dict[Tuple[str, int], Tuple[List[dict], Optional[float]]] = {}
        self._entity_cache: Dict[Tuple[str, int], Tuple[List[dict], Optional[float]]] = {}
        self._glossary_cache: Dict[Tuple[str, int], Tuple[List[dict], Optional[float]]] = {}
        self._cache_maxsize = 256

        logger.info(
            f"SearchService initialized: {len(self._report_corpus)} reports, "
            f"{len(self.glossary_index)} glossary terms"
        )

    def _build_report_corpus(self) -> List[Dict[str, Any]]:
        """
        Build searchable corpus from registry for rapidfuzz matching.

        Each entry: {report_id, search_text, report_info}
        search_text = title + ministry + audit_year + report_no
        """
        corpus = []

        if not self.registry:
            return corpus

        # Access reports from registry
        reports = getattr(self.registry, 'reports', {})

        for report_id, report_info in reports.items():
            # Build concatenated search text
            parts = [
                getattr(report_info, 'report_title', '') or '',
                getattr(report_info, 'ministry', '') or '',
                getattr(report_info, 'audit_year', '') or '',
                getattr(report_info, 'report_no', '') or '',
            ]
            search_text = ' '.join(p for p in parts if p)

            corpus.append({
                'report_id': report_id,
                'search_text': search_text,
                'report_info': report_info,
            })

        return corpus

    async def search(
        self,
        query: str,
        channel: str = "all",
        limit_per_channel: int = 5,
    ) -> GroupedSearchResults:
        """
        Main search method — fans out to all channels in parallel.

        Args:
            query: User's search query
            channel: Which channel(s) to search ('all' or specific channel name)
            limit_per_channel: Max results per channel

        Returns:
            GroupedSearchResults with all channel results and top_hit info
        """
        query = query.strip()

        # Initialize empty results
        results = {
            'reports': [],
            'ministries': [],
            'entities': [],
            'findings': [],
            'glossary': [],
        }

        # Track top scores per channel for top_hit determination
        channel_scores: List[ChannelScore] = []

        # Define which channels to run
        channels_to_run = (
            ['reports', 'ministries', 'entities', 'findings', 'glossary']
            if channel == 'all'
            else [channel] if channel in results else []
        )

        if not channels_to_run:
            return GroupedSearchResults(
                reports=[],
                ministries=[],
                entities=[],
                findings=[],
                glossary=[],
                top_hit_channel=None,
                top_hit_score=None,
            )

        # Build coroutine list for parallel execution
        coros = []
        coro_channels = []

        for ch in channels_to_run:
            if ch == 'reports':
                coros.append(self._search_reports(query, limit_per_channel))
                coro_channels.append('reports')
            elif ch == 'ministries':
                coros.append(self._search_ministries(query, limit_per_channel))
                coro_channels.append('ministries')
            elif ch == 'entities':
                coros.append(self._search_entities(query, limit_per_channel))
                coro_channels.append('entities')
            elif ch == 'findings':
                coros.append(self._search_findings(query, limit_per_channel))
                coro_channels.append('findings')
            elif ch == 'glossary':
                coros.append(self._search_glossary(query, limit_per_channel))
                coro_channels.append('glossary')

        # Run all channels in parallel with return_exceptions=True
        channel_results = await asyncio.gather(*coros, return_exceptions=True)

        # Process results, filtering out exceptions
        for i, (ch, result) in enumerate(zip(coro_channels, channel_results)):
            if isinstance(result, Exception):
                logger.warning(f"Search channel '{ch}' failed: {result}")
                continue

            channel_items, top_score = result
            results[ch] = channel_items

            if top_score is not None and top_score > 0:
                channel_scores.append(ChannelScore(channel=ch, score=top_score))

        # Determine top hit
        top_hit_channel = None
        top_hit_score = None

        if channel_scores:
            # Sort by score descending
            channel_scores.sort(key=lambda x: -x.score)
            top_hit_channel = channel_scores[0].channel
            top_hit_score = channel_scores[0].score

        return GroupedSearchResults(
            reports=results['reports'],
            ministries=results['ministries'],
            entities=results['entities'],
            findings=results['findings'],
            glossary=results['glossary'],
            top_hit_channel=top_hit_channel,
            top_hit_score=top_hit_score,
        )

    # =========================================================================
    # Channel Handlers
    # =========================================================================

    async def _search_reports(
        self, query: str, limit: int
    ) -> tuple[List[SearchResultReport], Optional[float]]:
        """
        Search reports using rapidfuzz token_set_ratio.

        Returns (results, top_score_normalized)
        """
        if not query or not self._report_corpus:
            return [], None

        # Score all reports
        scored = []
        for entry in self._report_corpus:
            score = fuzz.token_set_ratio(query.lower(), entry['search_text'].lower())
            if score >= self.fuzzy_threshold:
                scored.append((entry, score))

        # Sort by score descending
        scored.sort(key=lambda x: -x[1])

        # Take top N
        top_results = scored[:limit]

        results = []
        top_score = None

        for entry, score in top_results:
            report_info = entry['report_info']

            if top_score is None:
                top_score = score / 100.0  # Normalize to 0-1

            # Get findings count
            findings_count = getattr(report_info, 'findings_count', 0)
            if findings_count == 0:
                # Try to get from semantic data if available
                semantic = getattr(report_info, 'semantic', {})
                findings_count = len(semantic.get('findings', []))

            results.append(SearchResultReport(
                report_id=entry['report_id'],
                title=getattr(report_info, 'report_title', 'Untitled'),
                ministry=getattr(report_info, 'ministry', None),
                audit_year=getattr(report_info, 'audit_year', None),
                findings_count=findings_count,
                snippet=None,  # Could add match highlight in future
            ))

        return results, top_score

    async def _search_ministries(
        self, query: str, limit: int
    ) -> tuple[List[SearchResultMinistry], Optional[float]]:
        """
        Search ministry entities using entity_service.

        Returns (results, top_score_normalized)

        Phase E: LRU cached for common short queries (§15).
        """
        if not query or not self.entity_service:
            return [], None

        query_lower = query.lower().strip()
        cache_key = (query_lower, limit)

        # Check cache
        if cache_key in self._ministry_cache:
            cached_entities, top_score = self._ministry_cache[cache_key]
            # Convert cached dicts back to SearchResultMinistry
            results = [
                SearchResultMinistry(
                    entity_id=ent['id'],
                    canonical_name=ent['canonical_name'],
                    report_count=ent.get('report_count', 0),
                    finding_count=ent.get('finding_count', 0),
                )
                for ent in cached_entities
            ]
            return results, top_score

        try:
            # Search entities with type='ministry'
            entities = self.entity_service.search_entities(
                query=query,
                entity_type='ministry',
                limit=limit,
            )

            results = []
            top_score = None
            cached_entities = []

            for ent in entities:
                # Use mention_count as proxy for relevance score
                # Normalize to 0-1 range using log scale
                mention_count = ent.get('mention_count', 0)
                if mention_count > 0:
                    score = min(1.0, math.log10(mention_count + 1) / 4)  # log10(10000)/4 = 1.0
                else:
                    score = 0.0

                if top_score is None:
                    top_score = score

                results.append(SearchResultMinistry(
                    entity_id=ent['id'],
                    canonical_name=ent['canonical_name'],
                    report_count=ent.get('report_count', 0),
                    finding_count=ent.get('finding_count', 0),
                ))

                # Cache the raw entity dict
                cached_entities.append(ent)

            # Update cache (with size limit)
            if len(self._ministry_cache) >= self._cache_maxsize:
                # Evict oldest entry (first key)
                first_key = next(iter(self._ministry_cache))
                del self._ministry_cache[first_key]

            self._ministry_cache[cache_key] = (cached_entities, top_score)

            return results, top_score

        except Exception as e:
            logger.warning(f"Ministry search failed: {e}")
            return [], None

    async def _search_entities(
        self, query: str, limit: int
    ) -> tuple[List[SearchResultEntity], Optional[float]]:
        """
        Search non-ministry entities using entity_service.

        Returns (results, top_score_normalized)

        Phase E: LRU cached for common short queries (§15).
        """
        if not query or not self.entity_service:
            return [], None

        query_lower = query.lower().strip()
        cache_key = (query_lower, limit)

        # Check cache
        if cache_key in self._entity_cache:
            cached_entities, top_score = self._entity_cache[cache_key]
            # Convert cached dicts back to SearchResultEntity
            results = [
                SearchResultEntity(
                    entity_id=ent['id'],
                    canonical_name=ent['canonical_name'],
                    entity_type=ent.get('entity_type', 'unknown'),
                    mention_count=ent.get('mention_count', 0),
                    primary_tier=ent.get('primary_tier', 'union'),
                )
                for ent in cached_entities
            ]
            return results, top_score

        try:
            # Search all entities first, then filter out ministries
            # (entity_service doesn't support entity_type != X filter directly)
            entities = self.entity_service.search_entities(
                query=query,
                limit=limit * 2,  # Fetch extra to account for ministry filtering
            )

            results = []
            top_score = None
            cached_entities = []

            for ent in entities:
                # Skip ministries
                if ent.get('entity_type') == 'ministry':
                    continue

                if len(results) >= limit:
                    break

                # Use mention_count as proxy for relevance score
                mention_count = ent.get('mention_count', 0)
                if mention_count > 0:
                    score = min(1.0, math.log10(mention_count + 1) / 4)
                else:
                    score = 0.0

                if top_score is None:
                    top_score = score

                results.append(SearchResultEntity(
                    entity_id=ent['id'],
                    canonical_name=ent['canonical_name'],
                    entity_type=ent.get('entity_type', 'unknown'),
                    mention_count=mention_count,
                    primary_tier=ent.get('primary_tier', 'union'),
                ))

                # Cache the raw entity dict
                cached_entities.append(ent)

            # Update cache (with size limit)
            if len(self._entity_cache) >= self._cache_maxsize:
                # Evict oldest entry (first key)
                first_key = next(iter(self._entity_cache))
                del self._entity_cache[first_key]

            self._entity_cache[cache_key] = (cached_entities, top_score)

            return results, top_score

        except Exception as e:
            logger.warning(f"Entity search failed: {e}")
            return [], None

    async def _search_findings(
        self, query: str, limit: int
    ) -> tuple[List[SearchResultFinding], Optional[float]]:
        """
        Search findings using semantic retrieval.

        Only fires when query length >= findings_min_length (default 3).
        Runs retrieval_service.search_findings_snippets() in executor.

        Returns (results, top_score_normalized)
        """
        # Don't run for very short queries (per §4.2 requirement)
        if not query or len(query.strip()) < self.findings_min_length:
            return [], None

        if not self.retrieval_service:
            return [], None

        try:
            # Run sync retrieval in executor
            loop = asyncio.get_event_loop()
            snippets = await loop.run_in_executor(
                _executor,
                self.retrieval_service.search_findings_snippets,
                query,
                limit,
                True,  # auto_filter=True
            )

            results = []
            top_score = None

            for snippet in snippets:
                score = snippet.score

                if top_score is None:
                    top_score = score

                results.append(SearchResultFinding(
                    chunk_id=snippet.chunk_id,
                    report_id=snippet.report_id,
                    section=snippet.section,
                    page=snippet.page,
                    finding_type=snippet.finding_type,
                    severity=snippet.severity,
                    amount_crore=snippet.amount_crore,
                    snippet=snippet.snippet,
                    score=score,
                ))

            return results, top_score

        except Exception as e:
            logger.warning(f"Findings search failed: {e}")
            return [], None

    async def _search_glossary(
        self, query: str, limit: int
    ) -> tuple[List[SearchResultGlossary], Optional[float]]:
        """
        Search glossary using substring matching on terms and abbreviations.

        Groups same term from different reports — includes all definitions.

        Returns (results, top_score_normalized)

        Phase E: LRU cached for performance (glossary is static at startup).
        """
        if not query or not self.glossary_index:
            return [], None

        query_lower = query.lower().strip()
        cache_key = (query_lower, limit)

        # Check cache
        if cache_key in self._glossary_cache:
            cached_entries, top_score = self._glossary_cache[cache_key]
            # Convert cached dicts back to SearchResultGlossary
            results = [
                SearchResultGlossary(
                    term=entry.get('term', ''),
                    abbreviation=entry.get('abbreviation'),
                    definition=entry.get('definition'),
                    report_id=entry.get('report_id', ''),
                )
                for entry in cached_entries
            ]
            return results, top_score

        # Find matching terms (substring match)
        matches = []

        for term_key, entries in self.glossary_index.items():
            # Check if query is substring of term/abbrev
            if query_lower in term_key:
                # Score by match quality: exact > prefix > substring
                if term_key == query_lower:
                    score = 1.0
                elif term_key.startswith(query_lower):
                    score = 0.9
                else:
                    score = 0.7

                for entry in entries:
                    matches.append((entry, score))

        # Sort by score descending
        matches.sort(key=lambda x: -x[1])

        # Deduplicate: same term from same report should appear once
        # but same term from different reports should all appear
        seen = set()
        results = []
        cached_entries = []
        top_score = None

        for entry, score in matches:
            if len(results) >= limit:
                break

            term = entry.get('term', '')
            report_id = entry.get('report_id', '')

            # Dedup key: (term, report_id)
            dedup_key = (term.lower(), report_id)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            if top_score is None:
                top_score = score

            results.append(SearchResultGlossary(
                term=term,
                abbreviation=entry.get('abbreviation'),
                definition=entry.get('definition'),
                report_id=report_id,
            ))

            # Cache the raw entry dict
            cached_entries.append(entry)

        # Update cache (with size limit)
        if len(self._glossary_cache) >= self._cache_maxsize:
            # Evict oldest entry (first key)
            first_key = next(iter(self._glossary_cache))
            del self._glossary_cache[first_key]

        self._glossary_cache[cache_key] = (cached_entries, top_score)

        return results, top_score
