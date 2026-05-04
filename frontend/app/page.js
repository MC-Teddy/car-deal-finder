'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import {
  ChartBarIcon,
  TagIcon,
  TrophyIcon,
  ClockIcon,
  ArrowTopRightOnSquareIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ArrowPathIcon,
  ExclamationTriangleIcon,
} from '@heroicons/react/24/outline';

import StatsCard from './components/StatsCard';
import DealBadge from './components/DealBadge';
import Filters   from './components/Filters';
import { getListings, getStats } from './lib/api';

// ---------- helpers ----------

function formatSAR(num) {
  if (num == null) return '—';
  return Number(num).toLocaleString('en-SA') + ' SAR';
}

function formatMileage(km) {
  if (km == null) return '—';
  return Number(km).toLocaleString('en-SA') + ' km';
}

function timeAgo(dateStr) {
  if (!dateStr) return '—';
  const diff = (Date.now() - new Date(dateStr).getTime()) / 1000;
  if (diff < 60)         return 'Just now';
  if (diff < 3600)       return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400)      return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function sourceBadge(source) {
  const map = {
    haraj:  { label: 'Haraj',  bg: 'bg-orange-500/20 text-orange-300 border-orange-500/30' },
    syarah: { label: 'Syarah', bg: 'bg-purple-500/20 text-purple-300 border-purple-500/30' },
    motory: { label: 'Motory', bg: 'bg-sky-500/20    text-sky-300    border-sky-500/30'    },
  };
  const key   = (source || '').toLowerCase();
  const entry = map[key] || { label: source || 'Unknown', bg: 'bg-slate-600/50 text-slate-300 border-slate-500/30' };

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${entry.bg}`}>
      {entry.label}
    </span>
  );
}

const PAGE_SIZE = 20;
const REFRESH_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes

// ---------- skeleton rows ----------
function SkeletonRows({ count = 8 }) {
  return Array.from({ length: count }).map((_, i) => (
    <tr key={i} className={i % 2 === 0 ? 'bg-[#1E293B]' : 'bg-[#1a2537]'}>
      {Array.from({ length: 10 }).map((__, j) => (
        <td key={j} className="px-4 py-3">
          <div className="skeleton h-4 rounded" style={{ width: `${50 + Math.random() * 50}%` }} />
        </td>
      ))}
    </tr>
  ));
}

// ---------- main page ----------
export default function DashboardPage() {
  const [stats,       setStats]       = useState(null);
  const [statsError,  setStatsError]  = useState(false);
  const [statsLoading,setStatsLoading]= useState(true);

  const [listings,    setListings]    = useState([]);
  const [total,       setTotal]       = useState(0);
  const [pages,       setPages]       = useState(1);
  const [page,        setPage]        = useState(1);
  const [filters,     setFilters]     = useState({});
  const [listLoading, setListLoading] = useState(true);
  const [listError,   setListError]   = useState(null);

  const [lastUpdated,  setLastUpdated]  = useState(null);
  const [minutesSince, setMinutesSince] = useState(0);

  const refreshTimer  = useRef(null);
  const minutesTimer  = useRef(null);

  // ----- fetch stats -----
  const fetchStats = useCallback(async () => {
    try {
      setStatsLoading(true);
      const data = await getStats();
      setStats(data);
      setStatsError(false);
    } catch {
      setStatsError(true);
    } finally {
      setStatsLoading(false);
    }
  }, []);

  // ----- fetch listings -----
  const fetchListings = useCallback(async (activeFilters, activePage) => {
    try {
      setListLoading(true);
      setListError(null);
      const data = await getListings(activeFilters, activePage, PAGE_SIZE);
      setListings(data.items ?? []);
      setTotal(data.total ?? 0);
      setPages(data.pages ?? 1);
      setLastUpdated(new Date());
      setMinutesSince(0);
    } catch (err) {
      setListError(err.message || 'Failed to connect to the API.');
      setListings([]);
    } finally {
      setListLoading(false);
    }
  }, []);

  // ----- initial load -----
  useEffect(() => {
    fetchStats();
    fetchListings({}, 1);
  }, [fetchStats, fetchListings]);

  // ----- auto refresh every 5 min -----
  useEffect(() => {
    refreshTimer.current = setInterval(() => {
      fetchStats();
      fetchListings(filters, page);
    }, REFRESH_INTERVAL_MS);

    return () => clearInterval(refreshTimer.current);
  }, [filters, page, fetchStats, fetchListings]);

  // ----- "X mins ago" ticker -----
  useEffect(() => {
    minutesTimer.current = setInterval(() => {
      if (lastUpdated) {
        setMinutesSince(Math.floor((Date.now() - lastUpdated.getTime()) / 60000));
      }
    }, 30000);
    return () => clearInterval(minutesTimer.current);
  }, [lastUpdated]);

  // ----- filter change -----
  function handleFilter(newFilters) {
    setFilters(newFilters);
    setPage(1);
    fetchListings(newFilters, 1);
  }

  // ----- pagination -----
  function goToPage(newPage) {
    if (newPage < 1 || newPage > pages) return;
    setPage(newPage);
    fetchListings(filters, newPage);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // ----- manual refresh -----
  function handleManualRefresh() {
    fetchStats();
    fetchListings(filters, page);
  }

  return (
    <div>
      {/* ============ STATS BAR ============ */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <StatsCard
          icon={<ChartBarIcon className="w-5 h-5" />}
          label="Total Listings"
          value={stats ? stats.total_listings?.toLocaleString('en-SA') : null}
          subLabel="Scraped from all sources"
          accent="blue"
          loading={statsLoading}
        />
        <StatsCard
          icon={<TagIcon className="w-5 h-5" />}
          label="Deals Found"
          value={stats ? stats.deals_found?.toLocaleString('en-SA') : null}
          subLabel=">10% below market price"
          accent="emerald"
          loading={statsLoading}
        />
        <StatsCard
          icon={<TrophyIcon className="w-5 h-5" />}
          label="Best Deal Today"
          value={stats ? `${Number(stats.best_deal_score ?? 0).toFixed(1)}% below` : null}
          subLabel="Highest discount found"
          accent="amber"
          loading={statsLoading}
        />
        <StatsCard
          icon={<ClockIcon className="w-5 h-5" />}
          label="Last Scraped"
          value={stats ? timeAgo(stats.last_scraped_at) : null}
          subLabel={stats?.last_scraped_at ? new Date(stats.last_scraped_at).toLocaleString('en-SA') : ''}
          accent="slate"
          loading={statsLoading}
        />
      </div>

      {statsError && (
        <div className="mb-4 flex items-center gap-2 px-4 py-3 bg-amber-500/10 border border-amber-500/30 rounded-lg text-amber-300 text-sm">
          <ExclamationTriangleIcon className="w-4 h-4 flex-shrink-0" />
          Could not load stats — API may be unreachable.
        </div>
      )}

      {/* ============ FILTERS ============ */}
      <Filters onFilter={handleFilter} loading={listLoading} />

      {/* ============ TABLE HEADER ROW ============ */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 mb-3">
        <div>
          <h2 className="text-base font-semibold text-white">
            {listLoading
              ? 'Loading deals…'
              : `${total.toLocaleString('en-SA')} listings found`}
          </h2>
          {lastUpdated && !listLoading && (
            <p className="text-xs text-slate-500 mt-0.5">
              Last updated {minutesSince === 0 ? 'just now' : `${minutesSince} min ago`}
              {' · '}auto-refreshes every 5 min
            </p>
          )}
        </div>

        {/* Manual refresh */}
        <button
          onClick={handleManualRefresh}
          disabled={listLoading}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-slate-200 text-xs font-medium rounded-lg transition-colors"
        >
          <ArrowPathIcon className={`w-3.5 h-3.5 ${listLoading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* ============ ERROR STATE ============ */}
      {listError && !listLoading && (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <ExclamationTriangleIcon className="w-12 h-12 text-red-400 mb-3" />
          <h3 className="text-lg font-semibold text-white mb-1">API Unreachable</h3>
          <p className="text-slate-400 text-sm max-w-md mb-4">{listError}</p>
          <button
            onClick={handleManualRefresh}
            className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-semibold rounded-lg transition-colors"
          >
            Try Again
          </button>
        </div>
      )}

      {/* ============ DEALS TABLE ============ */}
      {!listError && (
        <div className="overflow-x-auto rounded-xl border border-slate-700/60 shadow-lg">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="bg-slate-800/80 text-left">
                {[
                  'Deal Score',
                  'Car',
                  'Price (SAR)',
                  'Market Avg',
                  'You Save',
                  'Mileage',
                  'City',
                  'Source',
                  'Listed',
                  '',
                ].map((col) => (
                  <th
                    key={col}
                    className="px-4 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wide whitespace-nowrap"
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {listLoading ? (
                <SkeletonRows count={10} />
              ) : listings.length === 0 ? (
                <tr>
                  <td colSpan={10}>
                    <div className="flex flex-col items-center justify-center py-20 text-center">
                      <div className="text-5xl mb-4">🔍</div>
                      <h3 className="text-lg font-semibold text-white mb-1">
                        No deals found
                      </h3>
                      <p className="text-slate-400 text-sm">
                        Try adjusting your filters — or check back after the next scrape.
                      </p>
                    </div>
                  </td>
                </tr>
              ) : (
                listings.map((car, idx) => {
                  const saving    = (car.market_avg_price ?? 0) - (car.price ?? 0);
                  const savingPct = car.market_avg_price
                    ? ((saving / car.market_avg_price) * 100)
                    : null;

                  return (
                    <tr
                      key={car.id ?? idx}
                      className={`border-t border-slate-700/40 hover:bg-slate-700/30 transition-colors ${
                        idx % 2 === 0 ? 'bg-[#1E293B]' : 'bg-[#1a2537]'
                      }`}
                    >
                      {/* Deal Score */}
                      <td className="px-4 py-3 whitespace-nowrap">
                        <DealBadge score={car.deal_score ?? savingPct} />
                      </td>

                      {/* Car */}
                      <td className="px-4 py-3 whitespace-nowrap">
                        <span className="font-semibold text-white">
                          {[car.make, car.model].filter(Boolean).join(' ') || '—'}
                        </span>
                        {car.year && (
                          <span className="ml-1.5 text-slate-400">{car.year}</span>
                        )}
                      </td>

                      {/* Price */}
                      <td className="px-4 py-3 whitespace-nowrap font-mono text-white">
                        {formatSAR(car.price)}
                      </td>

                      {/* Market Avg */}
                      <td className="px-4 py-3 whitespace-nowrap font-mono text-slate-400">
                        {formatSAR(car.market_avg_price)}
                      </td>

                      {/* You Save */}
                      <td className="px-4 py-3 whitespace-nowrap">
                        {saving > 0 ? (
                          <span className="text-emerald-400 font-semibold">
                            {formatSAR(saving)}
                            {savingPct != null && (
                              <span className="text-xs text-emerald-500 ml-1">
                                ({savingPct.toFixed(1)}%)
                              </span>
                            )}
                          </span>
                        ) : saving < 0 ? (
                          <span className="text-red-400">
                            +{formatSAR(Math.abs(saving))}
                          </span>
                        ) : (
                          <span className="text-slate-500">—</span>
                        )}
                      </td>

                      {/* Mileage */}
                      <td className="px-4 py-3 whitespace-nowrap text-slate-300">
                        {formatMileage(car.mileage_km)}
                      </td>

                      {/* City */}
                      <td className="px-4 py-3 whitespace-nowrap text-slate-300">
                        {car.city || '—'}
                      </td>

                      {/* Source */}
                      <td className="px-4 py-3 whitespace-nowrap">
                        {sourceBadge(car.source)}
                      </td>

                      {/* Listed age */}
                      <td className="px-4 py-3 whitespace-nowrap text-slate-400 text-xs">
                        {timeAgo(car.listed_at)}
                      </td>

                      {/* View button */}
                      <td className="px-4 py-3 whitespace-nowrap text-right">
                        {car.listing_url ? (
                          <a
                            href={car.listing_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 px-3 py-1.5 bg-emerald-600/20 hover:bg-emerald-600/40 text-emerald-300 text-xs font-medium rounded-lg border border-emerald-600/30 transition-colors"
                          >
                            View
                            <ArrowTopRightOnSquareIcon className="w-3 h-3" />
                          </a>
                        ) : (
                          <span className="text-slate-600 text-xs">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* ============ PAGINATION ============ */}
      {!listError && !listLoading && pages > 1 && (
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 mt-5">
          <p className="text-sm text-slate-400">
            Page <span className="text-white font-medium">{page}</span> of{' '}
            <span className="text-white font-medium">{pages}</span>
            {' · '}
            <span className="text-slate-500">{total.toLocaleString('en-SA')} total results</span>
          </p>

          <div className="flex items-center gap-2">
            <button
              onClick={() => goToPage(page - 1)}
              disabled={page <= 1}
              className="flex items-center gap-1 px-3 py-2 bg-slate-700 hover:bg-slate-600 disabled:opacity-40 disabled:cursor-not-allowed text-slate-200 text-sm font-medium rounded-lg transition-colors"
            >
              <ChevronLeftIcon className="w-4 h-4" />
              Previous
            </button>

            {/* Page number pills */}
            <div className="hidden sm:flex items-center gap-1">
              {Array.from({ length: Math.min(pages, 7) }, (_, i) => {
                let pg;
                if (pages <= 7) {
                  pg = i + 1;
                } else if (page <= 4) {
                  pg = i < 6 ? i + 1 : pages;
                } else if (page >= pages - 3) {
                  pg = i === 0 ? 1 : pages - 6 + i;
                } else {
                  const offsets = [-3, -2, -1, 0, 1, 2, 3];
                  pg = i === 0 ? 1 : page + offsets[i - 1];
                }

                return (
                  <button
                    key={pg}
                    onClick={() => goToPage(pg)}
                    className={`w-9 h-9 rounded-lg text-sm font-medium transition-colors ${
                      pg === page
                        ? 'bg-emerald-600 text-white'
                        : 'bg-slate-700 hover:bg-slate-600 text-slate-300'
                    }`}
                  >
                    {pg}
                  </button>
                );
              })}
            </div>

            <button
              onClick={() => goToPage(page + 1)}
              disabled={page >= pages}
              className="flex items-center gap-1 px-3 py-2 bg-slate-700 hover:bg-slate-600 disabled:opacity-40 disabled:cursor-not-allowed text-slate-200 text-sm font-medium rounded-lg transition-colors"
            >
              Next
              <ChevronRightIcon className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
