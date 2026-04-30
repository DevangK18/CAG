/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * API Client for CAG Gateway Backend
 * Connects to FastAPI backend at localhost:8000 (dev) or relative URL (production)
 *
 * v6: Added Overview & Summaries API endpoints (Phase 10)
 * v7: Production-ready API base URL with env var support
 */

// Use nullish coalescing (??) not logical OR (||)
// In production, VITE_API_BASE_URL="" (empty string) should be used, not fallback to localhost
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

// Backend routes are mounted at /api/* prefix (except /health which is at root)
const API_URL = `${API_BASE_URL}/api`;

// ============================================================================
// Types matching backend responses
// ============================================================================

export interface APICitation {
  citation_key: string;
  report_id: string;
  report_title: string;
  filename: string;
  section: string;
  page_logical: string;
  page_physical: number;
  score?: number;
  finding_type?: string;
  severity?: string;
  amount_crore?: number;
  audit_year?: string;
}

export interface APIReportSummary {
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

export interface APIReportDetail {
  id: string;
  title: string;
  report_no: string;
  ministry: string;
  sector: string;
  year: number;
  pages: number;
  filename: string;
  status: string;
  executive_summary: string;
  key_findings: string[];
  recommendations: string[];
  monetary_impact: string | null;
  findings_count: number;
  report_type?: string | null;
  government_body_type: string;
  state_name?: string | null;
  department?: string | null;
  audit_category: string;
}

export interface APIChatResponse {
  answer: string;
  citations: APICitation[];
  sources_used: number;
  model_used: string;
}

export interface APIHealthResponse {
  status: string;
  rag_service: string;
  reports_loaded: number;
  version: string;
}

// ============================================================================
// Charts & Tables Types
// ============================================================================

export type ChartType = 'bar' | 'line' | 'pie' | 'area' | 'table_chart' | 'unknown';

export interface ChartItem {
  id: string;
  title: string;
  type: ChartType;
  section: string;
  page: number;
  analysis: string;
  thumbnail_url?: string | null;
  bbox?: number[] | null;
  source_chunk_id?: string | null;
}

export interface TableItem {
  id: string;
  title: string;
  section: string;
  page: number;
  rows: number;
  columns: number;
  analysis: string;
  headers?: string[] | null;
  data_preview?: string[][] | null;
  bbox?: number[] | null;
  source_chunk_id?: string | null;
}

export interface ChartsResponse {
  charts: ChartItem[];
  total: number;
  report_id: string;
}

export interface TablesResponse {
  tables: TableItem[];
  total: number;
  report_id: string;
}

// ============================================================================
// Time Series Types
// ============================================================================

export interface SeriesReportSummary {
  report_id: string;
  report_title: string;
  audit_year: string;
  report_year: number;
  filename: string;
}

export interface TimeSeriesInfo {
  series_id: string;
  name: string;
  description: string;
  reports: SeriesReportSummary[];
  years_covered: string[];
}

export interface SeriesListResponse {
  series: TimeSeriesInfo[];
  total: number;
}

export interface SeriesQueryRequest {
  query: string;
  style?: string;
  compare_years?: boolean;
  top_k_per_report?: number;
}

export interface SeriesQueryResponse {
  answer: string;
  citations: APICitation[];
  years_compared: string[];
  sources_used: number;
  model_used: string;
}

// ============================================================================
// Overview Types (Phase 10)
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

export interface OverviewResponse {
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
  };
  table_of_contents: TOCEntry[];
  findings_summary: FindingSummaryData;
  findings_list: FindingItem[];
  recommendations: RecommendationItem[];
  section_classifications: any[];
  entities: Record<string, any>;
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
// Summaries Types (Phase 10)
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

export interface SummariesListResponse {
  report_id: string;
  generated_at: string;
  total_variants: number;
  total_errors: number;
  variants: SummaryVariantInfo[];
}

export interface SummaryContentResponse {
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

// ============================================================================
// Base API Functions
// ============================================================================

export async function fetchHealth(): Promise<APIHealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`);
  if (!response.ok) throw new Error('Health check failed');
  return response.json();
}

export async function fetchReports(params?: {
  sector?: string;
  year?: number;
  government_body_type?: string;
  state_name?: string;
  audit_category?: string;
}): Promise<{ reports: APIReportSummary[]; total: number }> {
  const searchParams = new URLSearchParams();
  if (params?.sector) searchParams.set('sector', params.sector);
  if (params?.year) searchParams.set('year', params.year.toString());
  if (params?.government_body_type) searchParams.set('government_body_type', params.government_body_type);
  if (params?.state_name) searchParams.set('state_name', params.state_name);
  if (params?.audit_category) searchParams.set('audit_category', params.audit_category);

  const queryString = searchParams.toString();
  const url = `${API_URL}/reports${queryString ? `?${queryString}` : ''}`;

  const response = await fetch(url);
  if (!response.ok) throw new Error('Failed to fetch reports');
  return response.json();
}

export async function fetchReport(reportId: string): Promise<APIReportDetail> {
  const response = await fetch(`${API_URL}/reports/${reportId}`);
  if (!response.ok) throw new Error(`Failed to fetch report: ${reportId}`);
  return response.json();
}

export interface FilterOption {
  value: string;
  label?: string;
  count: number;
}

export interface ReportFiltersResponse {
  government_body_types: FilterOption[];
  states: FilterOption[];
  audit_categories: FilterOption[];
}

export async function fetchReportFilters(): Promise<ReportFiltersResponse> {
  const response = await fetch(`${API_URL}/reports/filters`);
  if (!response.ok) throw new Error('Failed to fetch report filters');
  return response.json();
}

export function getPdfUrl(filename: string): string {
  return `${API_URL}/files/${filename}`;
}

// ============================================================================
// Charts & Tables API Functions
// ============================================================================

export async function fetchReportCharts(
  reportId: string,
  options?: {
    page?: number;
    chartType?: ChartType;
    limit?: number;
    offset?: number;
  }
): Promise<ChartsResponse> {
  const params = new URLSearchParams();
  
  if (options?.page) params.append('page', options.page.toString());
  if (options?.chartType) params.append('chart_type', options.chartType);
  if (options?.limit) params.append('limit', options.limit.toString());
  if (options?.offset) params.append('offset', options.offset.toString());
  
  const queryString = params.toString();
  const url = `${API_URL}/reports/${reportId}/charts${queryString ? `?${queryString}` : ''}`;
  
  const response = await fetch(url);
  
  if (!response.ok) {
    throw new Error(`Failed to fetch charts: ${response.statusText}`);
  }
  
  return response.json();
}

export async function fetchReportTables(
  reportId: string,
  options?: {
    page?: number;
    minRows?: number;
    minColumns?: number;
    limit?: number;
    offset?: number;
  }
): Promise<TablesResponse> {
  const params = new URLSearchParams();
  
  if (options?.page) params.append('page', options.page.toString());
  if (options?.minRows) params.append('min_rows', options.minRows.toString());
  if (options?.minColumns) params.append('min_columns', options.minColumns.toString());
  if (options?.limit) params.append('limit', options.limit.toString());
  if (options?.offset) params.append('offset', options.offset.toString());
  
  const queryString = params.toString();
  const url = `${API_URL}/reports/${reportId}/tables${queryString ? `?${queryString}` : ''}`;
  
  const response = await fetch(url);
  
  if (!response.ok) {
    throw new Error(`Failed to fetch tables: ${response.statusText}`);
  }
  
  return response.json();
}

// ============================================================================
// Time Series API Functions
// ============================================================================

export async function fetchSeries(): Promise<SeriesListResponse> {
  const response = await fetch(`${API_URL}/series`);
  
  if (!response.ok) {
    throw new Error(`Failed to fetch series: ${response.statusText}`);
  }
  
  return response.json();
}

export async function fetchSeriesById(seriesId: string): Promise<TimeSeriesInfo> {
  const response = await fetch(`${API_URL}/series/${seriesId}`);
  
  if (!response.ok) {
    throw new Error(`Failed to fetch series ${seriesId}: ${response.statusText}`);
  }
  
  return response.json();
}

export async function querySeriesData(
  seriesId: string,
  request: SeriesQueryRequest
): Promise<SeriesQueryResponse> {
  const response = await fetch(`${API_URL}/series/${seriesId}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query: request.query,
      style: request.style || 'adaptive',
      compare_years: request.compare_years ?? true,
      top_k_per_report: request.top_k_per_report || 5,
    }),
  });
  
  if (!response.ok) {
    throw new Error(`Failed to query series: ${response.statusText}`);
  }
  
  return response.json();
}

// ============================================================================
// Overview API Functions (Phase 10)
// ============================================================================

/**
 * Fetch complete overview for a report
 */
export async function fetchReportOverview(reportId: string): Promise<OverviewResponse> {
  const response = await fetch(`${API_URL}/reports/${reportId}/overview`);
  
  if (!response.ok) {
    if (response.status === 404) {
      throw new Error('Overview not available. Report may not have been processed yet.');
    }
    throw new Error(`Failed to fetch overview: ${response.statusText}`);
  }
  
  return response.json();
}

/**
 * Fetch table of contents for PDF navigation
 */
export async function fetchReportTOC(reportId: string): Promise<{
  report_id: string;
  title: string;
  entry_count: number;
  entries: TOCEntry[];
}> {
  const response = await fetch(`${API_URL}/reports/${reportId}/toc`);
  
  if (!response.ok) {
    throw new Error(`Failed to fetch TOC: ${response.statusText}`);
  }
  
  return response.json();
}

/**
 * Fetch topics covered in the report
 */
export async function fetchReportTopics(reportId: string): Promise<{
  report_id: string;
  topic_count: number;
  topics: TopicCovered[];
}> {
  const response = await fetch(`${API_URL}/reports/${reportId}/topics`);
  
  if (!response.ok) {
    throw new Error(`Failed to fetch topics: ${response.statusText}`);
  }
  
  return response.json();
}

/**
 * Fetch glossary terms
 */
export async function fetchReportGlossary(
  reportId: string,
  search?: string
): Promise<{
  report_id: string;
  term_count: number;
  terms: GlossaryTerm[];
}> {
  const params = search ? `?search=${encodeURIComponent(search)}` : '';
  const response = await fetch(`${API_URL}/reports/${reportId}/glossary${params}`);
  
  if (!response.ok) {
    throw new Error(`Failed to fetch glossary: ${response.statusText}`);
  }
  
  return response.json();
}

/**
 * Fetch audit scope details
 */
export async function fetchReportAuditScope(reportId: string): Promise<{
  report_id: string;
  scope: AuditScope | null;
}> {
  const response = await fetch(`${API_URL}/reports/${reportId}/audit-scope`);
  
  if (!response.ok) {
    throw new Error(`Failed to fetch audit scope: ${response.statusText}`);
  }
  
  return response.json();
}

/**
 * Fetch audit objectives
 */
export async function fetchReportObjectives(reportId: string): Promise<{
  report_id: string;
  objective_count: number;
  objectives: string[];
}> {
  const response = await fetch(`${API_URL}/reports/${reportId}/objectives`);
  
  if (!response.ok) {
    throw new Error(`Failed to fetch objectives: ${response.statusText}`);
  }
  
  return response.json();
}

// ============================================================================
// Summaries API Functions (Phase 10)
// ============================================================================

/**
 * Fetch list of available summary variants for a report
 */
export async function fetchSummariesList(reportId: string): Promise<SummariesListResponse> {
  const response = await fetch(`${API_URL}/reports/${reportId}/summaries`);
  
  if (!response.ok) {
    if (response.status === 404) {
      throw new Error('Summaries not available. Report may not have been processed yet.');
    }
    throw new Error(`Failed to fetch summaries: ${response.statusText}`);
  }
  
  return response.json();
}

/**
 * Fetch a specific summary variant
 */
export async function fetchSummary(
  reportId: string,
  variant: SummaryVariant
): Promise<SummaryContentResponse> {
  const response = await fetch(`${API_URL}/reports/${reportId}/summaries/${variant}`);
  
  if (!response.ok) {
    if (response.status === 404) {
      throw new Error(`Summary variant '${variant}' not available for this report.`);
    }
    if (response.status === 500) {
      const error = await response.json();
      throw new Error(error.detail || `Failed to generate ${variant} summary.`);
    }
    throw new Error(`Failed to fetch summary: ${response.statusText}`);
  }
  
  return response.json();
}

/**
 * Fetch a random summary variant (Surprise Me)
 */
export async function fetchRandomSummary(reportId: string): Promise<SummaryContentResponse> {
  const response = await fetch(`${API_URL}/reports/${reportId}/summaries/random`);
  
  if (!response.ok) {
    throw new Error(`Failed to fetch random summary: ${response.statusText}`);
  }
  
  return response.json();
}

/**
 * Fetch summary metadata (without full content)
 */
export async function fetchSummaryMetadata(
  reportId: string,
  variant: SummaryVariant
): Promise<{
  report_id: string;
  variant: string;
  name: string;
  icon: string;
  description: string;
  audience: string;
  expected_length: string;
  available: boolean;
  word_count: number;
  thinking_used: boolean;
  error: string | null;
  generated_at: string;
}> {
  const response = await fetch(`${API_URL}/reports/${reportId}/summaries/${variant}/metadata`);
  
  if (!response.ok) {
    throw new Error(`Failed to fetch summary metadata: ${response.statusText}`);
  }
  
  return response.json();
}

// ============================================================================
// Streaming Chat (SSE)
// ============================================================================

export interface StreamEvent {
  type:
    | 'citation_map'
    | 'caveat'
    | 'token'
    | 'done'
    | 'error'
    // Phase 13
    | 'groundedness'
    // Phase 11
    | 'planning'
    | 'sub_query'
    | 'iteration'
    | 'reformulation'
    | 'synthesizing'
    | 'agentic_trace';
  data: any;
}

export type CitationMap = Record<string, {
  report_id: string;
  report_title: string;
  filename: string;
  section: string;
  page_logical: string;
  page_physical: number;
  finding_type?: string;
  severity?: string;
  amount_crore?: number;
  audit_year?: string;
}>;

export async function* streamChat(params: {
  query: string;
  style?: string;
  report_ids?: string[];
  top_k?: number;
}): AsyncGenerator<StreamEvent> {
  const response = await fetch(`${API_URL}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query: params.query,
      style: params.style || 'adaptive',
      report_ids: params.report_ids,
      top_k: params.top_k || 10,
    }),
  });

  if (!response.ok) {
    yield { type: 'error', data: 'Stream request failed' };
    return;
  }

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const data = JSON.parse(line.slice(6));
          yield data as StreamEvent;
        } catch (e) {
          console.error('Failed to parse SSE event:', line);
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * Phase 11: Stream from the agentic endpoint.
 * Same parameters as streamChat; the backend decides whether to short-circuit
 * to the regular path (simple queries) or run the multi-hop loop.
 */
export async function* streamChatAgentic(params: {
  query: string;
  style?: string;
  report_ids?: string[];
  top_k?: number;
}): AsyncGenerator<StreamEvent> {
  const response = await fetch(`${API_URL}/chat/agentic/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query: params.query,
      style: params.style || 'adaptive',
      report_ids: params.report_ids,
      top_k: params.top_k || 10,
    }),
  });

  if (!response.ok) {
    yield { type: 'error', data: 'Stream request failed' };
    return;
  }

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const data = JSON.parse(line.slice(6));
          yield data as StreamEvent;
        } catch (e) {
          console.error('Failed to parse SSE event:', line);
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export async function* streamSeriesChat(
  seriesId: string,
  params: {
    query: string;
    style?: string;
    compare_years?: boolean;
    top_k_per_report?: number;
  }
): AsyncGenerator<StreamEvent> {
  const response = await fetch(`${API_URL}/series/${seriesId}/query/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query: params.query,
      style: params.style || 'adaptive',
      compare_years: params.compare_years ?? true,
      top_k_per_report: params.top_k_per_report || 5,
    }),
  });

  if (!response.ok) {
    yield { type: 'error', data: 'Series stream request failed' };
    return;
  }

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const data = JSON.parse(line.slice(6));
          yield data as StreamEvent;
        } catch (e) {
          console.error('Failed to parse SSE event:', line);
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
// ============================================================================
// Home Page API Functions (Phase A - Stubs)
// ============================================================================

import type {
  HomeStats,
  HomeFacets,
  HomeFeatured,
  TrendingSearch,
  EntitySummary,
  EntityDetail,
  GroupedSearchResults,
  SearchChannel,
} from '../types';

/**
 * Get home page stats
 * Phase A: Stub implementation
 */
export async function getHomeStats(): Promise<HomeStats> {
  return Promise.resolve({
    total_reports: 37,
    total_entities: 390,
    total_ministries: 50,
    total_mentions: 25000,
    total_findings: 5000,
    total_charts: 150,
    total_tables: 200,
    latest_ingest: '2024-12-01',
    year_range: [2020, 2024],
  });
}

/**
 * Get home page facets
 * Phase A: Stub implementation
 */
export async function getHomeFacets(): Promise<HomeFacets> {
  return Promise.resolve({
    tiers: [
      { value: 'union', label: 'Union', count: 20 },
      { value: 'state', label: 'State', count: 15 },
      { value: 'local_body', label: 'Local Body', count: 2 },
    ],
    states: [
      { value: 'MH', label: 'Maharashtra', count: 5 },
      { value: 'KA', label: 'Karnataka', count: 4 },
    ],
    years: [
      { value: '2024', label: '2024', count: 10 },
      { value: '2023', label: '2023', count: 15 },
    ],
    ministries: [],
    entities: [],
    audit_categories: [],
  });
}

/**
 * Get home page featured content
 * Phase A: Stub implementation
 */
export async function getHomeFeatured(): Promise<HomeFeatured> {
  return Promise.resolve({
    top_ministries: [],
    top_entities: [],
    recent_reports: [],
    deep_dives: [],
    popular_starts: [],
  });
}

/**
 * Get trending searches
 * Phase A: Stub implementation
 */
export async function getHomeTrending(): Promise<TrendingSearch[]> {
  return Promise.resolve([]);
}

/**
 * Get random surprise report
 * Phase A: Stub implementation
 */
export async function getSurpriseReport(): Promise<APIReportSummary> {
  return Promise.resolve({
    id: '2023_01_sample',
    title: 'Sample Report',
    report_no: '2023/01',
    ministry: 'Ministry of Sample',
    sector: 'Sample Sector',
    year: 2023,
    findings_count: 10,
    monetary_impact: '₹100 crore',
    status: 'published',
    filename: 'sample.pdf',
    government_body_type: 'union',
    audit_category: 'performance',
  });
}

/**
 * Get random surprise entity
 * Phase A: Stub implementation
 */
export async function getSurpriseEntity(): Promise<EntitySummary> {
  return Promise.resolve({
    id: 1,
    canonical_name: 'Sample Entity',
    entity_type: 'PSU',
    primary_tier: 'union',
    aliases: [],
    first_seen_year: 2020,
    last_seen_year: 2024,
    mention_count: 100,
    finding_count: 20,
    report_count: 5,
  });
}

/**
 * Smart search across all channels
 * Phase A: Stub implementation
 */
export async function smartSearch(params: {
  q: string;
  type?: SearchChannel;
  limit?: number;
}): Promise<GroupedSearchResults> {
  return Promise.resolve({
    reports: [],
    ministries: [],
    entities: [],
    findings: [],
    glossary: [],
    top_hit_channel: null,
    top_hit_score: null,
  });
}

/**
 * Get entity full details
 * Phase A: Stub implementation
 */
export async function getEntityFull(id: number): Promise<EntityDetail> {
  return Promise.resolve({
    id,
    canonical_name: 'Sample Entity',
    entity_type: 'PSU',
    primary_tier: 'union',
    aliases: [],
    first_seen_year: 2020,
    last_seen_year: 2024,
    mention_count: 100,
    finding_count: 20,
    report_count: 5,
  });
}
