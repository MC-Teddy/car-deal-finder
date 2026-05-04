'use client';

/**
 * StatsCard — a summary metric tile used in the top stats bar.
 *
 * Props:
 *   icon      {ReactNode}  Icon element (e.g. from @heroicons/react)
 *   label     {string}     Card title / metric name
 *   value     {string|number}  Primary value to display
 *   subLabel  {string}     Optional secondary text below the value
 *   accent    {string}     Optional colour accent: 'emerald' | 'amber' | 'red' | 'blue'
 *   loading   {boolean}    Show skeleton when true
 */
export default function StatsCard({ icon, label, value, subLabel, accent = 'emerald', loading = false }) {
  const accentClasses = {
    emerald: 'text-emerald-400 bg-emerald-500/10',
    amber:   'text-amber-400   bg-amber-500/10',
    red:     'text-red-400     bg-red-500/10',
    blue:    'text-blue-400    bg-blue-500/10',
    slate:   'text-slate-400   bg-slate-500/10',
  };

  const iconClass = accentClasses[accent] || accentClasses.emerald;

  return (
    <div className="bg-[#1E293B] border border-slate-700/60 rounded-xl p-4 sm:p-5 flex items-start gap-4 shadow-lg hover:border-slate-600 transition-colors">
      {/* Icon */}
      <div className={`flex-shrink-0 w-10 h-10 rounded-lg flex items-center justify-center ${iconClass}`}>
        {icon}
      </div>

      {/* Text */}
      <div className="flex-1 min-w-0">
        <p className="text-xs text-slate-400 font-medium uppercase tracking-wide truncate">
          {label}
        </p>

        {loading ? (
          <>
            <div className="skeleton h-6 w-24 mt-1 rounded" />
            {subLabel !== undefined && (
              <div className="skeleton h-3 w-32 mt-1.5 rounded" />
            )}
          </>
        ) : (
          <>
            <p className="text-xl sm:text-2xl font-bold text-white mt-0.5 leading-tight truncate">
              {value ?? '—'}
            </p>
            {subLabel && (
              <p className="text-xs text-slate-500 mt-0.5 truncate">{subLabel}</p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
