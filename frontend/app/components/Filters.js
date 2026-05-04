'use client';

import { useState, useEffect } from 'react';
import { getMakes, getModels } from '../lib/api';
import { MagnifyingGlassIcon, XMarkIcon, AdjustmentsHorizontalIcon } from '@heroicons/react/24/outline';

const CURRENT_YEAR = new Date().getFullYear();

const inputClass =
  'w-full bg-[#0F172A] border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500 transition-colors';

const labelClass = 'block text-xs font-medium text-slate-400 mb-1.5';

/**
 * Filters panel.
 *
 * Props:
 *   onFilter  {function}  Called with the filter object when Search is clicked.
 *   loading   {boolean}   Disable controls while results are loading.
 */
export default function Filters({ onFilter, loading = false }) {
  const [makes, setMakes]     = useState([]);
  const [models, setModels]   = useState([]);
  const [open, setOpen]       = useState(true); // collapsed on mobile

  const [make,       setMake]       = useState('');
  const [model,      setModel]      = useState('');
  const [yearMin,    setYearMin]    = useState('');
  const [yearMax,    setYearMax]    = useState('');
  const [priceMax,   setPriceMax]   = useState('');
  const [minScore,   setMinScore]   = useState(0);
  const [city,       setCity]       = useState('');

  // Fetch makes on mount
  useEffect(() => {
    getMakes()
      .then((data) => setMakes(Array.isArray(data) ? data : []))
      .catch(() => setMakes([]));
  }, []);

  // Fetch models whenever make changes
  useEffect(() => {
    setModel('');
    if (!make) {
      setModels([]);
      return;
    }
    getModels(make)
      .then((data) => setModels(Array.isArray(data) ? data : []))
      .catch(() => setModels([]));
  }, [make]);

  function buildFilters() {
    return {
      make:            make      || undefined,
      model:           model     || undefined,
      year_min:        yearMin   ? Number(yearMin)   : undefined,
      year_max:        yearMax   ? Number(yearMax)   : undefined,
      price_max:       priceMax  ? Number(priceMax)  : undefined,
      min_deal_score:  minScore  > 0 ? minScore : undefined,
      city:            city      || undefined,
    };
  }

  function handleSearch(e) {
    e.preventDefault();
    onFilter(buildFilters());
  }

  function handleClear() {
    setMake('');
    setModel('');
    setYearMin('');
    setYearMax('');
    setPriceMax('');
    setMinScore(0);
    setCity('');
    onFilter({});
  }

  return (
    <div className="bg-[#1E293B] border border-slate-700/60 rounded-xl shadow-lg mb-6 overflow-hidden">
      {/* Panel header / toggle */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-5 py-3.5 text-left hover:bg-slate-700/30 transition-colors"
      >
        <span className="flex items-center gap-2 text-sm font-semibold text-slate-200">
          <AdjustmentsHorizontalIcon className="w-4 h-4 text-emerald-400" />
          Filter Deals
        </span>
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          className={`w-4 h-4 text-slate-400 transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
        >
          <path
            fillRule="evenodd"
            d="M5.22 8.22a.75.75 0 011.06 0L10 11.94l3.72-3.72a.75.75 0 111.06 1.06l-4.25 4.25a.75.75 0 01-1.06 0L5.22 9.28a.75.75 0 010-1.06z"
            clipRule="evenodd"
          />
        </svg>
      </button>

      {/* Filter body */}
      {open && (
        <form onSubmit={handleSearch} className="px-5 pb-5 pt-2">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">

            {/* Make */}
            <div>
              <label className={labelClass}>Make</label>
              <select
                value={make}
                onChange={(e) => setMake(e.target.value)}
                className={inputClass}
                disabled={loading}
              >
                <option value="">All Makes</option>
                {makes.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>

            {/* Model */}
            <div>
              <label className={labelClass}>Model</label>
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className={inputClass}
                disabled={loading || !make}
              >
                <option value="">All Models</option>
                {models.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>

            {/* Year Min */}
            <div>
              <label className={labelClass}>Year From</label>
              <input
                type="number"
                placeholder="e.g. 2018"
                min="1990"
                max={CURRENT_YEAR}
                value={yearMin}
                onChange={(e) => setYearMin(e.target.value)}
                className={inputClass}
                disabled={loading}
              />
            </div>

            {/* Year Max */}
            <div>
              <label className={labelClass}>Year To</label>
              <input
                type="number"
                placeholder={String(CURRENT_YEAR)}
                min="1990"
                max={CURRENT_YEAR}
                value={yearMax}
                onChange={(e) => setYearMax(e.target.value)}
                className={inputClass}
                disabled={loading}
              />
            </div>

            {/* Max Price */}
            <div>
              <label className={labelClass}>Max Price (SAR)</label>
              <input
                type="number"
                placeholder="e.g. 80,000"
                min="0"
                step="1000"
                value={priceMax}
                onChange={(e) => setPriceMax(e.target.value)}
                className={inputClass}
                disabled={loading}
              />
            </div>

            {/* City */}
            <div>
              <label className={labelClass}>City</label>
              <input
                type="text"
                placeholder="e.g. Riyadh, Jeddah"
                value={city}
                onChange={(e) => setCity(e.target.value)}
                className={inputClass}
                disabled={loading}
              />
            </div>

            {/* Min Deal Score slider — spans full width on its own row */}
            <div className="sm:col-span-2">
              <label className={labelClass}>
                Min Deal Score — at least{' '}
                <span className="text-emerald-400 font-bold">{minScore}%</span>{' '}
                below market
              </label>
              <input
                type="range"
                min="0"
                max="30"
                step="1"
                value={minScore}
                onChange={(e) => setMinScore(Number(e.target.value))}
                className="w-full mt-1"
                disabled={loading}
              />
              <div className="flex justify-between text-xs text-slate-500 mt-0.5">
                <span>0% (all)</span>
                <span>10% (good)</span>
                <span>20% (great)</span>
                <span>30%+</span>
              </div>
            </div>
          </div>

          {/* Buttons */}
          <div className="flex flex-col sm:flex-row gap-3 mt-5">
            <button
              type="submit"
              disabled={loading}
              className="flex items-center justify-center gap-2 px-5 py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-lg transition-colors"
            >
              <MagnifyingGlassIcon className="w-4 h-4" />
              Search Deals
            </button>
            <button
              type="button"
              onClick={handleClear}
              disabled={loading}
              className="flex items-center justify-center gap-2 px-5 py-2.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed text-slate-200 text-sm font-semibold rounded-lg transition-colors"
            >
              <XMarkIcon className="w-4 h-4" />
              Clear Filters
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
