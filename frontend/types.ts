/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * 
 * TypeScript type definitions for CAG Gateway
 * v6: Added Phase 10 Overview & Summaries types
 */

// View states
export type ViewState = 'landing' | 'report' | 'time-series' | 'series-chat' | 'how-it-works';

// Tab states for report view - Added 'summaries' tab
export type TabState = 'overview' | 'findings' | 'recommendations' | 'charts' | 'tables' | 'summaries';

// Audit report from API
export interface AuditReport {
  id: string;
  reportNumber: string | null;
  title: string;
  ministry: string;
  sector: string;
  year: number;
  findingsCount: number;
  impact: string;
  reportType?: string; // Financial Audit, Performance Audit, Compliance Audit
  summary?: string;
  findings?: string[];
  recommendations?: string[];
  pdfFilename?: string;

  // Multi-tier expansion fields
  government_body_type?: 'union' | 'state' | 'local_body';
  state_name?: string | null;
  department?: string | null;
  audit_category?: 'compliance' | 'performance' | 'financial' | 'revenue' | 'commercial' | 'atir';
  report_subtype?: string | null;
}

// Time series (now from API, not hardcoded)
export interface ReportSeries {
  id: string;
  topic: string;
  ministry: string;
  description: string;
  reportIds: string[];
  yearsCovered: string[];
}

// Report within a series (includes audit year)
export interface SeriesReport {
  reportId: string;
  reportTitle: string;
  auditYear: string;
  reportYear: number;
  filename: string;
}

// Extended series info from API
export interface TimeSeriesDetail {
  seriesId: string;
  name: string;
  description: string;
  reports: SeriesReport[];
  yearsCovered: string[];
}

// Chat message
export interface Message {
  id?: string;
  role: 'user' | 'assistant';
  content: string;
  isStreaming?: boolean;
}

// Citation with full metadata
export interface Citation {
  citationKey: string;
  reportId: string;
  reportTitle: string;
  filename: string;
  section: string;
  pageLogical: string;
  pagePhysical: number;
  auditYear?: string;
  findingType?: string;
  severity?: string;
  amountCrore?: number;
}

// Response styles for chat
export type ResponseStyle = 
  | 'executive' 
  | 'concise' 
  | 'detailed' 
  | 'technical' 
  | 'comparative' 
  | 'adaptive';

// ============================================================================
// Phase 10: Overview Types
// ============================================================================

export interface AuditScope {
  period: {
    start: string;
    end: string;
    description: string;
  };
  geographic_coverage: string[];
  sample_size: {
    total: number | null;
    description: string | null;
  };
  entities_covered: string[];
}

export interface TopicCovered {
  name: string;
  sections: string[];
  page_start: number;
  page_end: number;
  description: string;
}

export interface GlossaryTerm {
  term: string;
  abbreviation: string;
  definition: string | null;
  category: string;
}

export interface TOCEntry {
  id: string;
  title: string;
  level: number;
  page_start: number;
  page_end: number;
  hierarchy: Record<string, string>;
}

export interface FindingSummaryData {
  total_count: number;
  total_monetary_crore: number;
  by_severity: Record<string, number>;
  by_type: Record<string, { count: number; total_crore: number }>;
}

export interface FindingItem {
  id: string;
  severity: string;
  type: string;
  amount_crore: number;
  chapter: string;
  section: string;
  page: number;
  text: string;
  summary: string;
}

export interface RecommendationItem {
  id: string;
  text: string;
  summary: string;
  chapter: string;
  page: number;
}

export interface OverviewData {
  basic_info: {
    report_id: string;
    report_number: string;
    report_year: number;
    title: string;
    ministry: string;
    sector: string;
    report_type: string;
    publication_date: string;
    source_url: string;
    source_filename: string;

    // Multi-tier expansion fields
    government_body_type?: 'union' | 'state' | 'local_body';
    state_name?: string | null;
    department?: string | null;
    audit_category?: 'compliance' | 'performance' | 'financial' | 'revenue' | 'commercial' | 'atir';
    report_subtype?: string | null;
  };
  table_of_contents: TOCEntry[];
  findings_summary: FindingSummaryData;
  findings_list: FindingItem[];
  recommendations: RecommendationItem[];
  audit_scope: AuditScope | null;
  audit_objectives: string[] | null;
  topics_covered: TopicCovered[] | null;
  glossary_terms: GlossaryTerm[] | null;
  _metadata: {
    generated_at: string;
    llm_extraction_available: boolean;
    summaries_available: boolean;
    phase: string;
  };
}

// ============================================================================
// Phase 10: Summaries Types
// ============================================================================

export type SummaryVariant = 'executive' | 'journalist' | 'deep_dive' | 'simple' | 'policy';

export interface SummaryVariantInfo {
  id: SummaryVariant;
  name: string;
  icon: string;
  description: string;
  audience: string;
  length: string;
  available: boolean;
  word_count: number;
}

export interface SummaryContent {
  report_id: string;
  variant: SummaryVariant;
  name: string;
  icon: string;
  description: string;
  audience: string;
  content: string;
  word_count: number;
  thinking_used: boolean;
  generated_at: string;
  is_random?: boolean;
}

// Variant display metadata for UI
export const SUMMARY_VARIANT_CONFIG: Record<SummaryVariant, {
  name: string;
  icon: string;
  shortIcon: string;
  color: string;
  bgColor: string;
}> = {
  executive: {
    name: 'Executive Brief',
    icon: '📋',
    shortIcon: 'EB',
    color: '#1a365d',
    bgColor: '#ebf8ff',
  },
  journalist: {
    name: "Journalist's Take",
    icon: '📰',
    shortIcon: 'JT',
    color: '#744210',
    bgColor: '#fffaf0',
  },
  deep_dive: {
    name: 'Deep Dive',
    icon: '🔬',
    shortIcon: 'DD',
    color: '#553c9a',
    bgColor: '#faf5ff',
  },
  simple: {
    name: 'Simple Explainer',
    icon: '💡',
    shortIcon: 'SE',
    color: '#276749',
    bgColor: '#f0fff4',
  },
  policy: {
    name: 'Policy Brief',
    icon: '🏛️',
    shortIcon: 'PB',
    color: '#702459',
    bgColor: '#fff5f7',
  },
};

// ============================================================================
// Home Page Types (NEW)
// ============================================================================

export interface HomeStats {
  total_reports: number;
  total_entities: number;
  total_ministries: number;
  total_mentions: number;
  total_findings: number;
  total_charts: number;
  total_tables: number;
  latest_ingest: string | null;
  year_range: [number, number];
}

export interface FacetValue {
  value: string;
  label: string | null;
  count: number;
}

export interface HomeFacets {
  tiers: FacetValue[];
  states: FacetValue[];
  years: FacetValue[];
  ministries: FacetValue[];
  entities: FacetValue[];
  audit_categories: FacetValue[];
}

export interface FeaturedMinistry {
  entity_id: number;
  canonical_name: string;
  report_count: number;
  finding_count: number;
  mention_count: number;
  primary_tier: string;
}

export interface FeaturedEntity {
  entity_id: number;
  canonical_name: string;
  entity_type: string;
  mention_count: number;
  finding_count: number;
  primary_tier: string;
}

export interface ReportSummary {
  id: string;
  title: string;
  report_no: string;
  ministry: string;
  sector: string;
  year: number;
  findings_count: number;
  monetary_impact: string | null;
  status: string;
  filename: string;
  report_type?: string | null;
  government_body_type: string;
  state_name?: string | null;
  department?: string | null;
  audit_category: string;
}

export interface TimeSeriesInfoItem {
  series_id: string;
  name: string;
  description: string;
  reports: SeriesReportSummary[];
  years_covered: string[];
}

export interface SeriesReportSummary {
  report_id: string;
  report_title: string;
  audit_year: string;
  report_year: number;
  filename: string;
}

export interface HomeFeatured {
  top_ministries: FeaturedMinistry[];
  top_entities: FeaturedEntity[];
  recent_reports: ReportSummary[];
  deep_dives: TimeSeriesInfoItem[];
  popular_starts: (FeaturedMinistry | FeaturedEntity)[];
}

// ============================================================================
// Smart Search Types (NEW)
// ============================================================================

export interface SearchResultReport {
  kind: 'report';
  report_id: string;
  title: string;
  ministry: string | null;
  audit_year: string | null;
  findings_count: number;
  snippet?: string | null;
}

export interface SearchResultMinistry {
  kind: 'ministry';
  entity_id: number;
  canonical_name: string;
  report_count: number;
  finding_count: number;
}

export interface SearchResultEntity {
  kind: 'entity';
  entity_id: number;
  canonical_name: string;
  entity_type: string;
  mention_count: number;
  primary_tier: string;
}

export interface SearchResultFinding {
  kind: 'finding';
  chunk_id: string;
  report_id: string;
  section: string;
  page: number;
  finding_type: string | null;
  severity: string | null;
  amount_crore: number | null;
  snippet: string;
  score: number;
}

export interface SearchResultGlossary {
  kind: 'glossary';
  term: string;
  abbreviation: string | null;
  definition: string | null;
  report_id: string;
}

export type SearchResultRow =
  | SearchResultReport
  | SearchResultMinistry
  | SearchResultEntity
  | SearchResultFinding
  | SearchResultGlossary;

export type SearchChannel = 'all' | 'reports' | 'ministries' | 'entities' | 'findings' | 'glossary';

export interface GroupedSearchResults {
  reports: SearchResultReport[];
  ministries: SearchResultMinistry[];
  entities: SearchResultEntity[];
  findings: SearchResultFinding[];
  glossary: SearchResultGlossary[];
  top_hit_channel: SearchChannel | null;
  top_hit_score: number | null;
}

// ============================================================================
// Entity Page Types (NEW)
// ============================================================================

export interface EntitySummary {
  id: number;
  canonical_name: string;
  entity_type: string;
  primary_tier: string;
  aliases: string[];
  first_seen_year: number | null;
  last_seen_year: number | null;
  mention_count: number;
  finding_count: number;
  report_count: number;
}

export interface EntityDetail extends EntitySummary {
  // Entity detail can extend summary with additional fields as needed
}

// ============================================================================
// Trending & Groundedness Types (NEW)
// ============================================================================

export interface TrendingSearch {
  query_text: string;
  hit_count: number;
  last_seen: string;
}

export interface GroundednessClaim {
  text: string;
  grounded: boolean;
  confidence: number;
  reason: string;
  source_ref?: string;
}

export interface GroundednessReport {
  verified: boolean;
  overall_score: number;
  num_claims: number;
  num_grounded: number;
  num_ungrounded: number;
  claims: GroundednessClaim[];
  provider_used: string;
}