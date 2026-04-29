"""
Cross-corpus canonicalization (Phase 12).

Reads per-report `normalized_entities` from each *_overview_llm.json,
batches them through gpt-4o-mini, and produces a global canonical
entity dictionary loaded into Postgres.

Run via:
    python -m src.entity_graph.cli canonicalize --overviews-dir data/batch_jobs/overviews
"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Set, Optional, Any, Tuple
from collections import defaultdict

from openai import OpenAI

from .db import session_scope, init_db
from .models import Entity

logger = logging.getLogger(__name__)


# =============================================================================
# Stop List - Generic aliases that must NEVER be used as merge keys
# =============================================================================

GENERIC_ALIAS_STOP_LIST: Set[str] = {
    # Generic government terms
    "government",
    "state",
    "states",
    "state government",
    "state governments",
    "the state",
    "the government",
    "central government",
    "union government",
    # Generic organizational terms
    "department",
    "departments",
    "the department",
    "ministry",
    "ministries",
    "the ministry",
    "board",
    "boards",
    "the board",
    "committee",
    "committees",
    "the committee",
    "authority",
    "authorities",
    "the authority",
    "council",
    "councils",
    "the council",
    "commission",
    "commissions",
    "the commission",
    "corporation",
    "corporations",
    "the corporation",
    "agency",
    "agencies",
    "the agency",
    "office",
    "offices",
    "the office",
    "bank",
    "banks",
    "the bank",
    "centre",
    "center",
    "centres",
    "centers",
    "the centre",
    "the center",
    # Indian administrative terms
    "psu",
    "psus",
    "cpsu",
    "cpsus",
    "undertaking",
    "undertakings",
    "enterprise",
    "enterprises",
    "organization",
    "organisation",
    "organizations",
    "organisations",
}

# Indian state names - entities from different states must NEVER merge
INDIAN_STATE_NAMES: Set[str] = {
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh",
    "goa", "gujarat", "haryana", "himachal pradesh", "jharkhand", "karnataka",
    "kerala", "madhya pradesh", "maharashtra", "manipur", "meghalaya", "mizoram",
    "nagaland", "odisha", "orissa", "punjab", "rajasthan", "sikkim", "tamil nadu",
    "telangana", "tripura", "uttar pradesh", "uttarakhand", "west bengal",
    # Union territories
    "delhi", "jammu and kashmir", "ladakh", "chandigarh", "puducherry",
    "andaman and nicobar", "dadra and nagar haveli", "daman and diu", "lakshadweep",
}


def _extract_state_from_text(text: str) -> Optional[str]:
    """Extract Indian state name from text, if present."""
    text_lower = text.lower()
    for state in INDIAN_STATE_NAMES:
        if state in text_lower:
            return state
    return None


def _entities_from_different_states(ent1_name: str, ent1_aliases: Set[str],
                                     ent2_name: str, ent2_aliases: Set[str]) -> bool:
    """
    Check if two entities are from different Indian states.
    Returns True if they should NOT be merged due to state mismatch.
    """
    # Get state from entity 1
    state1 = _extract_state_from_text(ent1_name)
    if not state1:
        for alias in ent1_aliases:
            state1 = _extract_state_from_text(alias)
            if state1:
                break

    # Get state from entity 2
    state2 = _extract_state_from_text(ent2_name)
    if not state2:
        for alias in ent2_aliases:
            state2 = _extract_state_from_text(alias)
            if state2:
                break

    # If both have identifiable states and they differ, don't merge
    if state1 and state2 and state1 != state2:
        return True

    return False


# =============================================================================
# Prompt
# =============================================================================

CANONICALIZATION_SYSTEM_PROMPT = """You merge entity records from multiple Indian CAG audit reports into a canonical entity dictionary.

You will receive a JSON list of entity records from different reports. Each record has:
- canonical_form_in_report: how the entity was named in that one report
- entity_type: classification
- aliases_seen: variant spellings/abbreviations seen in that report
- tier_context: union | state | local_body

Your task: merge records that refer to the SAME real-world entity.

Rules:
- Two records refer to the same entity if any of their aliases overlap (case-insensitive) OR their canonical_form_in_report differ only in casing/abbreviation/minor wording
- The merged canonical_name should be the LONGEST and MOST OFFICIAL form across all merged records
- The merged aliases must include EVERY variant from all merged records (deduplicated case-insensitively)
- entity_type: prefer the most specific type (e.g., "psu" over "organization" if both apply)
- primary_tier: pick the tier_context that appears most often across the merged records
- Be conservative: if two records LOOK similar but their aliases don't overlap, keep them SEPARATE
- Skip records where canonical_form_in_report is too generic ("the Ministry", "the State") or under 4 characters

CRITICAL - Do NOT merge based on generic aliases:
- NEVER merge two records based ONLY on shared generic aliases like "State Government", "Government", "State", "Department", "Ministry", "Board", "Authority", "Committee", "Council", "Commission", "Corporation", "Bank", "Office", "Agency", "Centre/Center", "PSU", "Undertaking", "Enterprise", or "Organization".
- These generic terms are NOT valid merge keys. They appear in many unrelated entities.
- Two records ONLY merge if they share a SPECIFIC entity name, specific acronym, or specific proper noun.

CRITICAL - State-specific entities must NEVER merge across states:
- If two records have DIFFERENT Indian state names in their canonical_form_in_report, they are DIFFERENT entities. NEVER merge them.
- Indian state names include: Kerala, Karnataka, Maharashtra, Tamil Nadu, Andhra Pradesh, Telangana, Gujarat, Rajasthan, Madhya Pradesh, Uttar Pradesh, Bihar, West Bengal, Odisha, Punjab, Haryana, Jharkhand, Chhattisgarh, Assam, Himachal Pradesh, Uttarakhand, Goa, Tripura, Meghalaya, Manipur, Nagaland, Mizoram, Arunachal Pradesh, Sikkim.
- "Government of Kerala" and "Government of Karnataka" are DIFFERENT entities, even if both have "GoK" as alias.
- "Kerala State Road Transport Corporation" and "Karnataka State Road Transport Corporation" are DIFFERENT entities.
- Abbreviations like "GoK", "GoM", "GoA" are ambiguous and can refer to multiple states. Do NOT use them alone to merge.
- When you see an abbreviation like "GoK", only merge if both records explicitly have the SAME state name (e.g., both say "Kerala").
- Each state's government, departments, PSUs, and corporations should remain SEPARATE from other states.

Return ONLY valid JSON:
{
  "merged_entities": [
    {
      "canonical_name": "National Highways Authority of India",
      "entity_type": "psu",
      "aliases": ["NHAI", "National Highways Authority", "National Highway Authority of India"],
      "primary_tier": "union"
    }
  ]
}"""

# Fallback prompt for when the main prompt returns empty results
CANONICALIZATION_FALLBACK_PROMPT = """You are converting entity records into a canonical format.

You will receive a JSON list of entity records. For EACH record, output ONE canonical entity.

DO NOT merge any records. DO NOT return an empty array. Return exactly one output entity for each input record.

For each input record:
- canonical_name = the canonical_form_in_report value
- entity_type = the entity_type value
- aliases = combine canonical_form_in_report with aliases_seen (deduplicated)
- primary_tier = the tier_context value

Return ONLY valid JSON with a non-empty 'merged_entities' array:
{
  "merged_entities": [
    {"canonical_name": "...", "entity_type": "...", "aliases": [...], "primary_tier": "..."},
    {"canonical_name": "...", "entity_type": "...", "aliases": [...], "primary_tier": "..."}
  ]
}

CRITICAL: You MUST return exactly {count} entities (one per input). Never return an empty array."""


# =============================================================================
# Pass 2: Conservative LLM-based deduplication for large corpora
# =============================================================================

PASS2_DEDUP_SYSTEM_PROMPT = """You are a conservative deduplication assistant for Indian government entity records.

You will receive a JSON list of canonical entities that have ALREADY been through a first-pass merge.
Your task: identify ONLY clear remaining duplicates that should be merged.

Each entity has:
- _pass2_id: stable identifier for this session
- canonical_name: the merged name from pass 1
- entity_type: organization, psu, ministry, etc.
- aliases: all known variants
- primary_tier: union | state | local_body

Rules for merging:
1. ONLY merge if you are CERTAIN two records refer to the exact same real-world entity
2. Conservative bias: when in doubt, DO NOT merge
3. NEVER merge entities from different Indian states (e.g., "Government of Kerala" vs "Government of Karnataka")
4. NEVER merge based on generic aliases like "State Government", "The Department", "PSU", etc.
5. DO merge if:
   - One entity's canonical_name appears as an alias in another
   - Two entities have the exact same acronym AND matching state context
   - Obvious spelling/punctuation variants of the same specific name

Return a JSON object with merge pairs:
{
  "merge_pairs": [
    {
      "keep_id": "ID of entity to keep (prefer the one with more aliases or longer canonical_name)",
      "absorb_id": "ID of entity to merge INTO keep_id",
      "reason": "Brief explanation"
    }
  ]
}

If no merges are warranted, return: {"merge_pairs": []}

CRITICAL: Be VERY conservative. It's better to miss a merge than to incorrectly combine distinct entities."""


# =============================================================================
# Collection
# =============================================================================

def collect_normalized_entities(overviews_dir: Path) -> List[Dict[str, Any]]:
    """
    Walk every *_overview_llm.json in overviews_dir and return
    a flat list of normalized entity records.
    """
    overview_files = sorted(overviews_dir.glob("*_overview_llm.json"))
    if not overview_files:
        raise RuntimeError(f"No overview files found in {overviews_dir}")

    all_records: List[Dict[str, Any]] = []
    for f in overview_files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            records = data.get("normalized_entities") or []
            for r in records:
                # Tag the record with source for debugging
                r["_source_file"] = f.name
                all_records.append(r)
        except Exception as e:
            logger.warning(f"Failed to read {f.name}: {e}")

    logger.info(f"Collected {len(all_records)} normalized entity records from {len(overview_files)} reports")
    return all_records


# =============================================================================
# Pre-merge: bucket by lowercase canonical for cheap pre-dedup
# =============================================================================

def pre_bucket(records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Group records by case-insensitive canonical_form_in_report.

    This is a free first-pass dedup: 'NHAI' from 50 reports collapses to 1 bucket.
    Reduces the LLM workload massively.

    Skips records whose canonical_form_in_report is in the GENERIC_ALIAS_STOP_LIST
    to prevent merging on generic terms like "State Government".
    """
    buckets: Dict[str, List[Dict]] = defaultdict(list)
    skipped_generic = 0
    for r in records:
        key = (r.get("canonical_form_in_report") or "").lower().strip()
        if not key or len(key) < 3:
            continue
        # Skip records with generic canonical forms
        if key in GENERIC_ALIAS_STOP_LIST:
            skipped_generic += 1
            continue
        buckets[key].append(r)
    logger.info(f"Pre-bucketed into {len(buckets)} unique lowercase canonicals (skipped {skipped_generic} generic forms)")
    return buckets


def collapse_buckets(buckets: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    For each bucket, collapse to one consolidated record with merged aliases.
    Keep the longest canonical_form_in_report seen as the bucket's canonical.

    Output records are still pre-LLM; they need cross-bucket dedup.
    """
    consolidated: List[Dict[str, Any]] = []
    for key, recs in buckets.items():
        # Pick longest canonical
        best_canonical = max(
            (r.get("canonical_form_in_report") or "" for r in recs),
            key=len,
        )

        # Merge aliases case-insensitively
        all_aliases: Set[str] = set()
        for r in recs:
            all_aliases.add(r.get("canonical_form_in_report") or "")
            for a in r.get("aliases_seen") or []:
                if a:
                    all_aliases.add(a)
        all_aliases.discard("")

        # entity_type: most common
        type_counts: Dict[str, int] = defaultdict(int)
        for r in recs:
            t = r.get("entity_type") or "organization"
            type_counts[t] += 1
        best_type = max(type_counts.items(), key=lambda x: x[1])[0]

        # tier: most common
        tier_counts: Dict[str, int] = defaultdict(int)
        for r in recs:
            t = r.get("tier_context") or "union"
            tier_counts[t] += 1
        best_tier = max(tier_counts.items(), key=lambda x: x[1])[0]

        consolidated.append({
            "canonical_form_in_report": best_canonical,
            "entity_type": best_type,
            "aliases_seen": sorted(all_aliases),
            "tier_context": best_tier,
            "_occurrence_count": len(recs),
        })
    return consolidated


# =============================================================================
# LLM cross-bucket canonicalization
# =============================================================================

def _stream_json_response(
    client: OpenAI,
    model: str,
    messages: List[Dict[str, str]],
    max_tokens: int,
    temperature: float = 0.0,
) -> Tuple[Optional[Dict[str, Any]], bool]:
    """
    Stream JSON response from OpenAI and detect truncation.

    Returns:
        (parsed_json, was_truncated)
    """
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=messages,
            response_format={"type": "json_object"},
            stream=True,
        )

        accumulated = ""
        finish_reason = None

        for chunk in response:
            if chunk.choices[0].delta.content:
                accumulated += chunk.choices[0].delta.content
            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason

        # Check if response was truncated
        was_truncated = finish_reason == "length"

        # Try to parse JSON
        parsed = json.loads(accumulated)
        return parsed, was_truncated

    except json.JSONDecodeError as e:
        logger.warning(f"JSON decode error: {e}. Response length: {len(accumulated)}")
        return None, True
    except Exception as e:
        logger.warning(f"Stream error: {e}")
        return None, False


def _local_passthrough_conversion(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Local fallback: convert input records to canonical format without LLM.

    Used when the LLM returns empty responses or fails repeatedly.
    Each input record becomes its own canonical entity (no merging).
    """
    converted: List[Dict[str, Any]] = []
    for rec in records:
        canonical_name = rec.get("canonical_form_in_report") or ""
        if not canonical_name or len(canonical_name) < 3:
            continue

        # Combine canonical name with seen aliases
        aliases = set()
        aliases.add(canonical_name)
        for a in rec.get("aliases_seen") or []:
            if a and len(a) >= 2:
                aliases.add(a)

        converted.append({
            "canonical_name": canonical_name,
            "entity_type": rec.get("entity_type") or "organization",
            "aliases": sorted(aliases),
            "primary_tier": rec.get("tier_context") or "union",
        })

    return converted


def canonicalize_via_llm(
    consolidated: List[Dict[str, Any]],
    model: str = "gpt-4o-mini",
    batch_size: int = 40,
) -> List[Dict[str, Any]]:
    """
    Send consolidated records to LLM in batches for cross-bucket merging.

    Within a single batch, the LLM merges 'NHAI' and 'National Highways Authority of India'
    even if they ended up in different buckets (because of casing/spelling).

    Features:
    - Streaming JSON parsing with truncation detection
    - Exponential backoff retry for failed batches
    - Temperature increase (1.5x) on JSON parse errors
    - Structured logging for dropped entities

    Returns canonical entities ready to load into Postgres.
    """
    client = OpenAI()
    canonical: List[Dict[str, Any]] = []
    dropped_entities: List[Dict[str, Any]] = []  # Track dropped entities

    # Sort by occurrence_count desc — most common entities go in first batches
    # (helps the LLM see the high-frequency canonical names first)
    consolidated_sorted = sorted(
        consolidated, key=lambda r: -r.get("_occurrence_count", 0)
    )

    batch_num = 0
    total_batches = (len(consolidated_sorted) - 1) // batch_size + 1

    for i in range(0, len(consolidated_sorted), batch_size):
        batch = consolidated_sorted[i : i + batch_size]
        batch_num += 1

        # Strip internal fields before sending
        clean_batch = [
            {k: v for k, v in r.items() if not k.startswith("_")}
            for r in batch
        ]

        user_prompt = (
            f"Merge these entity records:\n\n{json.dumps(clean_batch, indent=2, ensure_ascii=False)}\n\n"
            "Return JSON with 'merged_entities' array."
        )

        messages = [
            {"role": "system", "content": CANONICALIZATION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        # Retry logic with exponential backoff and temperature increase
        max_retries = 3
        current_max_tokens = 8000
        current_temperature = 0.0
        retry_delay = 2  # seconds
        batch_success = False

        for attempt in range(max_retries):
            try:
                parsed, was_truncated = _stream_json_response(
                    client=client,
                    model=model,
                    messages=messages,
                    max_tokens=current_max_tokens,
                    temperature=current_temperature,
                )

                if parsed:
                    merged = parsed.get("merged_entities") or []

                    # Check for empty response with non-empty input
                    if len(merged) == 0 and len(clean_batch) > 0:
                        logger.warning(
                            f"Batch {batch_num}/{total_batches}: LLM returned 0 entities for {len(clean_batch)} inputs — "
                            f"retrying with fallback prompt"
                        )

                        # Try LLM fallback with simpler prompt
                        try:
                            fallback_prompt = CANONICALIZATION_FALLBACK_PROMPT.format(count=len(clean_batch))
                            fallback_user_prompt = (
                                f"Convert these {len(clean_batch)} entity records (one output per input, no merging):\n\n"
                                f"{json.dumps(clean_batch, indent=2, ensure_ascii=False)}\n\n"
                                f"Return JSON with 'merged_entities' array containing exactly {len(clean_batch)} entities."
                            )
                            fallback_messages = [
                                {"role": "system", "content": fallback_prompt},
                                {"role": "user", "content": fallback_user_prompt},
                            ]

                            fallback_parsed, _ = _stream_json_response(
                                client=client,
                                model=model,
                                messages=fallback_messages,
                                max_tokens=current_max_tokens,
                                temperature=0.2,
                            )

                            if fallback_parsed and isinstance(fallback_parsed, dict):
                                fallback_merged = fallback_parsed.get("merged_entities") or []
                                if len(fallback_merged) > 0:
                                    canonical.extend(fallback_merged)
                                    logger.info(
                                        f"Batch {batch_num}/{total_batches}: {len(batch)} input → {len(fallback_merged)} recovered (LLM fallback)"
                                    )
                                    batch_success = True
                                    break

                            logger.warning(
                                f"Batch {batch_num}/{total_batches}: LLM fallback also returned 0 entities, using local passthrough"
                            )
                        except Exception as fallback_err:
                            logger.warning(
                                f"Batch {batch_num}/{total_batches}: LLM fallback failed ({fallback_err}), using local passthrough"
                            )

                        # Local passthrough fallback - convert input directly without LLM
                        local_converted = _local_passthrough_conversion(clean_batch)
                        if local_converted:
                            canonical.extend(local_converted)
                            logger.info(
                                f"Batch {batch_num}/{total_batches}: {len(batch)} input → {len(local_converted)} recovered (local passthrough)"
                            )
                            batch_success = True
                            break
                        else:
                            # Should never happen, but log if it does
                            entity_names = [r.get("canonical_form_in_report", "UNKNOWN") for r in batch]
                            logger.error(
                                f"Batch {batch_num}/{total_batches} DROPPED: local passthrough failed. "
                                f"Lost {len(batch)} entities: {entity_names}"
                            )
                            for rec in batch:
                                rec["_drop_reason"] = "local_passthrough_failed"
                            dropped_entities.extend(batch)
                            break

                    if was_truncated:
                        logger.warning(
                            f"Batch {batch_num}/{total_batches}: Response truncated at {current_max_tokens} tokens. "
                            f"Got {len(merged)} entities but may be incomplete."
                        )

                    canonical.extend(merged)
                    logger.info(
                        f"Batch {batch_num}/{total_batches}: {len(batch)} input → {len(merged)} merged"
                        + (" (truncated)" if was_truncated else "")
                        + (f" (temp={current_temperature:.2f})" if current_temperature > 0 else "")
                    )
                    batch_success = True
                    break  # Success - exit retry loop

                else:
                    # JSON parsing failed - increase temperature and retry
                    if attempt < max_retries - 1:
                        current_temperature = (current_temperature + 0.1) * 1.5  # 1.5x increase (starting from 0.1 if was 0)
                        current_max_tokens = min(current_max_tokens + 2000, 16000)
                        logger.warning(
                            f"Batch {batch_num}/{total_batches} attempt {attempt + 1}: JSON parse failed. "
                            f"Retrying with temperature={current_temperature:.2f}, max_tokens={current_max_tokens} in {retry_delay}s..."
                        )
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                    else:
                        # Final attempt failed - log dropped entities with ALL names
                        entity_names = [r.get("canonical_form_in_report", "UNKNOWN") for r in batch]
                        logger.error(
                            f"Batch {batch_num}/{total_batches} DROPPED after {max_retries} attempts (JSON parse failures). "
                            f"Lost {len(batch)} entities: {entity_names}"
                        )
                        for rec in batch:
                            rec["_drop_reason"] = "json_parse_failure"
                        dropped_entities.extend(batch)

            except Exception as e:
                if attempt < max_retries - 1:
                    current_temperature = (current_temperature + 0.1) * 1.5
                    logger.warning(
                        f"Batch {batch_num}/{total_batches} attempt {attempt + 1} error: {e}. "
                        f"Retrying with temperature={current_temperature:.2f} in {retry_delay}s..."
                    )
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    # Final attempt failed - log dropped entities with ALL names
                    entity_names = [r.get("canonical_form_in_report", "UNKNOWN") for r in batch]
                    logger.error(
                        f"Batch {batch_num}/{total_batches} DROPPED after {max_retries} attempts: {e}. "
                        f"Lost {len(batch)} entities: {entity_names}"
                    )
                    for rec in batch:
                        rec["_drop_reason"] = f"exception: {e}"
                    dropped_entities.extend(batch)

    # Log final statistics
    if dropped_entities:
        logger.warning(
            f"CANONICALIZATION COMPLETE: {len(canonical)} entities processed, "
            f"{len(dropped_entities)} entities DROPPED across {len(dropped_entities) // batch_size + (1 if len(dropped_entities) % batch_size else 0)} failed batches"
        )
        # Write dropped entities to file for manual review
        dropped_file = Path("data/batch_jobs/dropped_entities.json")
        dropped_file.parent.mkdir(parents=True, exist_ok=True)
        with open(dropped_file, "w", encoding="utf-8") as f:
            json.dump({
                "total_dropped": len(dropped_entities),
                "dropped_entities": dropped_entities
            }, f, indent=2, ensure_ascii=False)
        logger.warning(f"Dropped entities written to: {dropped_file}")
    else:
        logger.info(f"CANONICALIZATION COMPLETE: {len(canonical)} entities processed, 0 dropped")

    # Final pass: merge across-batch overlaps (same alias appearing in two LLM batches)
    final = _final_alias_merge(canonical)
    logger.info(f"After final alias merge: {len(final)} canonical entities")

    # Post-processing: scrub generic aliases from all entities
    scrubbed = _scrub_generic_aliases(final)
    logger.info(f"After scrubbing generic aliases: {len(scrubbed)} canonical entities")
    return scrubbed


def _scrub_generic_aliases(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Post-processing step: remove generic aliases from each entity's alias list.

    This ensures that entities like "Government of Kerala" keep their specific
    aliases ['Government of Kerala', 'GoK', 'Kerala Government'] but lose
    generic ones like ['State Government', 'Government', 'State'].
    """
    scrubbed: List[Dict[str, Any]] = []
    total_removed = 0

    for ent in entities:
        aliases = ent.get("aliases") or []
        cname = ent.get("canonical_name") or ""

        # Filter out generic aliases (case-insensitive)
        filtered_aliases = [
            a for a in aliases
            if a.lower().strip() not in GENERIC_ALIAS_STOP_LIST
        ]

        removed_count = len(aliases) - len(filtered_aliases)
        total_removed += removed_count

        # Ensure canonical name is in aliases
        if cname and cname not in filtered_aliases:
            filtered_aliases.append(cname)

        scrubbed.append({
            "canonical_name": cname,
            "entity_type": ent.get("entity_type") or "organization",
            "aliases": sorted(set(filtered_aliases)),
            "primary_tier": ent.get("primary_tier"),
        })

    logger.info(f"Scrubbed {total_removed} generic aliases across {len(entities)} entities")
    return scrubbed


def _final_alias_merge(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Cross-batch alias merge.

    If batch 1 produced {NHAI, [NHAI, National Highways Authority]} and
    batch 2 produced {National Highways Authority of India, [NHAI]}, merge them.

    IMPORTANT: Excludes aliases in GENERIC_ALIAS_STOP_LIST from overlap consideration
    to prevent merging unrelated entities that happen to share generic terms.

    Also prevents merging entities from DIFFERENT Indian states (e.g., Government of
    Kerala should never merge with Government of Karnataka, even if they share "GoK").
    """
    alias_to_idx: Dict[str, int] = {}
    out: List[Dict[str, Any]] = []
    blocked_merges = 0

    for ent in entities:
        cname = ent.get("canonical_name") or ""
        aliases = ent.get("aliases") or []
        all_aliases_lower = {a.lower().strip() for a in aliases if a}
        all_aliases_lower.add(cname.lower().strip())
        all_aliases_lower.discard("")

        # Filter out generic aliases for merge-key consideration
        mergeable_aliases = all_aliases_lower - GENERIC_ALIAS_STOP_LIST

        # Find existing entity with overlapping alias (only using non-generic aliases)
        target_idx = None
        for a in mergeable_aliases:
            if a in alias_to_idx:
                candidate_idx = alias_to_idx[a]
                existing = out[candidate_idx]
                existing_aliases_set = {x.lower().strip() for x in existing.get("aliases", [])}

                # Check if merging would combine entities from different states
                if _entities_from_different_states(
                    cname, all_aliases_lower,
                    existing["canonical_name"], existing_aliases_set
                ):
                    # Different states - don't merge, continue looking
                    blocked_merges += 1
                    logger.debug(f"Blocked merge: '{cname}' vs '{existing['canonical_name']}' (different states)")
                    continue

                target_idx = candidate_idx
                break

        if target_idx is None:
            out.append({
                "canonical_name": cname,
                "entity_type": ent.get("entity_type") or "organization",
                "aliases": sorted(set(aliases + [cname])),
                "primary_tier": ent.get("primary_tier"),
            })
            new_idx = len(out) - 1
            # Only register non-generic aliases as merge keys
            for a in mergeable_aliases:
                alias_to_idx[a] = new_idx
        else:
            existing = out[target_idx]
            existing_aliases = set(existing["aliases"])
            existing_aliases.update(aliases)
            existing_aliases.add(cname)
            existing_aliases.discard("")

            if len(cname) > len(existing["canonical_name"]):
                existing["canonical_name"] = cname

            existing["aliases"] = sorted(existing_aliases)
            # Only register non-generic aliases as merge keys
            for a in mergeable_aliases:
                alias_to_idx[a] = target_idx

    if blocked_merges > 0:
        logger.info(f"Blocked {blocked_merges} cross-state merges")

    return out


# =============================================================================
# Pass 2: LLM-based conservative dedup for large corpora
# =============================================================================

def _apply_pass2_merges(
    canonicals: List[Dict[str, Any]],
    merge_pairs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Apply pass 2 merge decisions to the canonical list.

    For each merge pair:
    - Move all aliases from absorb entity to keep entity
    - Prefer longer canonical_name when merging
    - Track absorbed IDs to prevent double-absorption

    Returns survivors (non-absorbed entities).
    """
    # Build lookup by _pass2_id
    id_to_entity: Dict[str, Dict[str, Any]] = {
        e["_pass2_id"]: e for e in canonicals if "_pass2_id" in e
    }

    absorbed_ids: Set[str] = set()

    for pair in merge_pairs:
        keep_id = pair.get("keep_id")
        absorb_id = pair.get("absorb_id")
        reason = pair.get("reason", "")

        if not keep_id or not absorb_id:
            continue

        # Skip if either entity was already absorbed
        if keep_id in absorbed_ids or absorb_id in absorbed_ids:
            logger.debug(f"Skipping merge {absorb_id} -> {keep_id}: one already absorbed")
            continue

        keep_ent = id_to_entity.get(keep_id)
        absorb_ent = id_to_entity.get(absorb_id)

        if not keep_ent or not absorb_ent:
            logger.warning(f"Pass 2 merge references unknown ID: keep={keep_id}, absorb={absorb_id}")
            continue

        # Check for cross-state merge (should have been blocked by LLM, but double-check)
        keep_aliases = set(keep_ent.get("aliases") or [])
        absorb_aliases = set(absorb_ent.get("aliases") or [])
        if _entities_from_different_states(
            keep_ent.get("canonical_name", ""), keep_aliases,
            absorb_ent.get("canonical_name", ""), absorb_aliases
        ):
            logger.warning(f"Blocked pass 2 cross-state merge: {absorb_ent.get('canonical_name')} -> {keep_ent.get('canonical_name')}")
            continue

        # Merge aliases
        merged_aliases = keep_aliases | absorb_aliases
        merged_aliases.add(keep_ent.get("canonical_name", ""))
        merged_aliases.add(absorb_ent.get("canonical_name", ""))
        merged_aliases.discard("")

        keep_ent["aliases"] = sorted(merged_aliases)

        # Prefer longer canonical_name
        if len(absorb_ent.get("canonical_name", "")) > len(keep_ent.get("canonical_name", "")):
            keep_ent["canonical_name"] = absorb_ent["canonical_name"]

        # Mark absorbed
        absorbed_ids.add(absorb_id)
        logger.debug(f"Pass 2 merge: {absorb_ent.get('canonical_name')} -> {keep_ent.get('canonical_name')} ({reason})")

    # Return survivors (remove _pass2_id field)
    survivors: List[Dict[str, Any]] = []
    for ent in canonicals:
        pass2_id = ent.get("_pass2_id")
        if pass2_id and pass2_id in absorbed_ids:
            continue
        # Strip _pass2_id from output
        clean_ent = {k: v for k, v in ent.items() if k != "_pass2_id"}
        survivors.append(clean_ent)

    logger.info(f"Pass 2 applied {len(absorbed_ids)} merges, {len(survivors)} survivors")
    return survivors


def pass2_dedup_via_llm(
    canonicals: List[Dict[str, Any]],
    model: str = "gpt-4o-mini",
    batch_size: int = 250,
) -> List[Dict[str, Any]]:
    """
    Second-pass LLM deduplication for large corpora.

    Sorts entities by (entity_type, primary_tier, canonical_name) to group
    similar entities together, then batches through LLM for conservative
    merge decisions.

    Returns deduplicated canonical list.
    """
    client = OpenAI()

    # Sort for better LLM context: similar entities together
    sorted_canonicals = sorted(
        canonicals,
        key=lambda e: (
            e.get("entity_type") or "zzz",
            e.get("primary_tier") or "zzz",
            (e.get("canonical_name") or "").lower(),
        )
    )

    # Add stable _pass2_id for LLM reference
    for idx, ent in enumerate(sorted_canonicals):
        ent["_pass2_id"] = f"E{idx:04d}"

    all_merge_pairs: List[Dict[str, Any]] = []
    total_batches = (len(sorted_canonicals) - 1) // batch_size + 1

    for batch_num, i in enumerate(range(0, len(sorted_canonicals), batch_size), 1):
        batch = sorted_canonicals[i : i + batch_size]

        # Prepare batch for LLM (include _pass2_id)
        batch_for_llm = [
            {
                "_pass2_id": e["_pass2_id"],
                "canonical_name": e.get("canonical_name"),
                "entity_type": e.get("entity_type"),
                "aliases": e.get("aliases", [])[:20],  # Limit aliases to avoid token overflow
                "primary_tier": e.get("primary_tier"),
            }
            for e in batch
        ]

        user_prompt = (
            f"Review these {len(batch)} entities for remaining duplicates:\n\n"
            f"{json.dumps(batch_for_llm, indent=2, ensure_ascii=False)}\n\n"
            "Return JSON with 'merge_pairs' array. Be conservative - only merge CLEAR duplicates."
        )

        messages = [
            {"role": "system", "content": PASS2_DEDUP_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            parsed, was_truncated = _stream_json_response(
                client=client,
                model=model,
                messages=messages,
                max_tokens=4000,
                temperature=0.0,
            )

            if parsed:
                pairs = parsed.get("merge_pairs") or []
                if pairs:
                    all_merge_pairs.extend(pairs)
                    logger.info(f"Pass 2 batch {batch_num}/{total_batches}: {len(pairs)} merges suggested")
                else:
                    logger.info(f"Pass 2 batch {batch_num}/{total_batches}: no merges")
            else:
                logger.warning(f"Pass 2 batch {batch_num}/{total_batches}: JSON parse failed, skipping")

        except Exception as e:
            logger.warning(f"Pass 2 batch {batch_num}/{total_batches} error: {e}, skipping")

    # Apply all merge decisions
    if all_merge_pairs:
        result = _apply_pass2_merges(sorted_canonicals, all_merge_pairs)
    else:
        # Strip _pass2_id even if no merges
        result = [{k: v for k, v in e.items() if k != "_pass2_id"} for e in sorted_canonicals]
        logger.info("Pass 2: no merges to apply")

    return result


# =============================================================================
# Persist to Postgres
# =============================================================================

def load_canonical_to_db(canonical_entities: List[Dict[str, Any]]) -> int:
    """
    Upsert canonical entities into Postgres.

    Match on canonical_name (unique-indexed). Update aliases on conflict.
    """
    init_db()
    inserted = 0
    updated = 0

    with session_scope() as session:
        for ent_dict in canonical_entities:
            cname = (ent_dict.get("canonical_name") or "").strip()
            if not cname:
                continue

            existing = session.query(Entity).filter_by(canonical_name=cname).first()
            if existing:
                # Merge aliases
                existing_aliases = set(json.loads(existing.aliases))
                new_aliases = set(ent_dict.get("aliases") or [])
                merged = sorted(existing_aliases | new_aliases)
                existing.aliases = json.dumps(merged)
                if ent_dict.get("entity_type") and ent_dict["entity_type"] != "organization":
                    existing.entity_type = ent_dict["entity_type"]
                if ent_dict.get("primary_tier"):
                    existing.primary_tier = ent_dict["primary_tier"]
                updated += 1
            else:
                ent = Entity(
                    canonical_name=cname,
                    entity_type=ent_dict.get("entity_type") or "organization",
                    aliases=json.dumps(ent_dict.get("aliases") or [cname]),
                    primary_tier=ent_dict.get("primary_tier"),
                )
                session.add(ent)
                inserted += 1

    logger.info(f"Canonical load: {inserted} new, {updated} updated")
    return inserted + updated


# =============================================================================
# Top-level orchestrator
# =============================================================================

def canonicalize_all(
    overviews_dir: Path,
    output_path: Optional[Path] = None,
    model: str = "gpt-4o-mini",
    batch_size: int = 40,
    two_pass_threshold: int = 1000,
    pass2_batch_size: int = 250,
    pass2_model: str = "gpt-4o-mini",
) -> List[Dict[str, Any]]:
    """
    End-to-end canonicalization pipeline.

    Args:
        overviews_dir: Directory containing *_overview_llm.json files
        output_path: Where to write canonical_entities.json
        model: Model for pass 1 canonicalization
        batch_size: Batch size for pass 1
        two_pass_threshold: Only run pass 2 if raw record count exceeds this
        pass2_batch_size: Batch size for pass 2
        pass2_model: Model for pass 2 conservative dedup
    """
    raw = collect_normalized_entities(overviews_dir)
    raw_count = len(raw)

    buckets = pre_bucket(raw)
    consolidated = collapse_buckets(buckets)
    canonical = canonicalize_via_llm(consolidated, model=model, batch_size=batch_size)

    # Pass 2: conservative LLM dedup for large corpora
    if raw_count > two_pass_threshold:
        logger.info(f"Raw record count {raw_count} > threshold {two_pass_threshold}; running pass 2 dedup")
        canonical = pass2_dedup_via_llm(
            canonical,
            model=pass2_model,
            batch_size=pass2_batch_size,
        )
        # Re-run cleanup after pass 2 merges
        canonical = _final_alias_merge(canonical)
        canonical = _scrub_generic_aliases(canonical)
        logger.info(f"After pass 2: {len(canonical)} entities")
    else:
        logger.info(f"Raw record count {raw_count} <= threshold {two_pass_threshold}; skipping pass 2")

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({"entities": canonical}, f, indent=2, ensure_ascii=False)
        logger.info(f"Wrote canonical dictionary: {output_path}")

    load_canonical_to_db(canonical)
    return canonical
