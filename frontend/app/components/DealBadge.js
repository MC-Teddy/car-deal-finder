'use client';

/**
 * DealBadge — colour-coded badge showing how good a deal is.
 *
 * Props:
 *   score  {number}  Positive = % below market, negative = % above market.
 *                    e.g.  22  → "22% below market"  (excellent)
 *                          15  → "15% below market"  (good)
 *                           5  → "5% below market"   (fair)
 *                          -8  → "8% above market"   (overpriced)
 */
export default function DealBadge({ score }) {
  if (score === undefined || score === null) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-slate-700 text-slate-400">
        N/A
      </span>
    );
  }

  const pct = Math.abs(score).toFixed(1);

  if (score > 20) {
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 whitespace-nowrap">
        🔥 {pct}% below
      </span>
    );
  }

  if (score >= 10) {
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold bg-blue-500/20 text-blue-300 border border-blue-500/30 whitespace-nowrap">
        ✅ {pct}% below
      </span>
    );
  }

  if (score >= 0) {
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-slate-600/50 text-slate-300 border border-slate-500/30 whitespace-nowrap">
        {pct}% below
      </span>
    );
  }

  // Overpriced (score < 0)
  return (
    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-red-500/20 text-red-300 border border-red-500/30 whitespace-nowrap">
      {pct}% above
    </span>
  );
}
