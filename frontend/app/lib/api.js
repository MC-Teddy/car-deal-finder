/**
 * API helper functions for the Car Deal Finder dashboard.
 * All calls target the FastAPI backend whose base URL is set in
 * the NEXT_PUBLIC_API_URL environment variable.
 */

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

/**
 * Generic fetch wrapper with error handling.
 * @param {string} path  - URL path relative to BASE_URL
 * @param {object} [params] - Query-string parameters
 * @returns {Promise<any>} Parsed JSON response
 */
async function apiFetch(path, params = {}) {
  const url = new URL(`${BASE_URL}${path}`);

  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, value);
    }
  });

  const response = await fetch(url.toString(), {
    headers: {
      Accept: 'application/json',
    },
    // Next.js 14: no caching by default (fresh data every request)
    cache: 'no-store',
  });

  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new Error(
      `API error ${response.status} on ${path}: ${text || response.statusText}`
    );
  }

  return response.json();
}

/**
 * Fetch paginated listings with optional filters.
 *
 * @param {object} filters
 * @param {string}  [filters.make]
 * @param {string}  [filters.model]
 * @param {number}  [filters.year_min]
 * @param {number}  [filters.year_max]
 * @param {number}  [filters.price_max]
 * @param {number}  [filters.min_deal_score]  - e.g. 10 means "at least 10% below market"
 * @param {string}  [filters.city]
 * @param {number}  [page=1]
 * @param {number}  [pageSize=20]
 * @returns {Promise<{ items: object[], total: number, page: number, pages: number }>}
 */
export async function getListings(filters = {}, page = 1, pageSize = 20) {
  return apiFetch('/listings', {
    ...filters,
    page,
    page_size: pageSize,
  });
}

/**
 * Fetch top deals (highest deal score listings).
 * @param {number} [limit=5]
 * @returns {Promise<object[]>}
 */
export async function getTopDeals(limit = 5) {
  return apiFetch('/listings/top-deals', { limit });
}

/**
 * Fetch aggregated dashboard statistics.
 * @returns {Promise<{
 *   total_listings: number,
 *   deals_found: number,
 *   best_deal_score: number,
 *   last_scraped_at: string
 * }>}
 */
export async function getStats() {
  return apiFetch('/listings/stats');
}

/**
 * Fetch the list of available car makes.
 * @returns {Promise<string[]>}
 */
export async function getMakes() {
  return apiFetch('/listings/makes');
}

/**
 * Fetch models for a given make.
 * @param {string} make
 * @returns {Promise<string[]>}
 */
export async function getModels(make) {
  if (!make) return [];
  return apiFetch('/listings/models', { make });
}
