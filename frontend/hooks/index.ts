/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * 
 * Hooks index - exports all custom hooks
 * v5: Added series hooks
 */

export { useReports } from './useReports';
export { useReport } from './useReport';
export { useChatStream } from './useChatStream';
export { useCharts } from './useCharts';
export { useTables } from './useTables';
export { useSeries, useSeriesDetail } from './useSeries';
export { useSeriesChat } from './useSeriesChat';

// New phase 10 additions
export { useOverview } from './useOverview';
export { useSummaries } from './useSummaries';

// Home page hooks (Phase B/C)
export { useHomeStats } from './useHomeStats';
export { useHomeFacets } from './useHomeFacets';
export { useHomeFeatured } from './useHomeFeatured';
export { useSurpriseMe } from './useSurpriseMe';
export { useSmartSearch } from './useSmartSearch';

// Entity page hook (Phase D)
export { useEntity } from './useEntity';