import './globals.css';

export const metadata = {
  title: 'Car Deal Finder — لقطات السيارات',
  description: 'Find the best used car deals in Saudi Arabia — أفضل صفقات السيارات المستعملة في السعودية',
};

export default function RootLayout({ children }) {
  return (
    <html lang="ar" dir="ltr">
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-screen bg-[#0F172A] text-slate-100">
        {/* Top header bar */}
        <header className="sticky top-0 z-50 bg-[#0F172A] border-b border-slate-800 shadow-lg">
          <div className="max-w-screen-2xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
            {/* Logo + title */}
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-emerald-500 flex items-center justify-center flex-shrink-0">
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 24 24"
                  fill="currentColor"
                  className="w-5 h-5 text-white"
                >
                  <path d="M3.375 4.5C2.339 4.5 1.5 5.34 1.5 6.375V13.5h12V6.375c0-1.036-.84-1.875-1.875-1.875h-8.25zM13.5 15h-12v2.625c0 1.035.84 1.875 1.875 1.875h.375a3 3 0 116 0h3a.75.75 0 00.75-.75V15z" />
                  <path d="M8.25 19.5a1.5 1.5 0 10-3 0 1.5 1.5 0 003 0zM15.75 6.75a.75.75 0 00-.75.75v11.25c0 .087.015.17.042.248a3 3 0 015.958.464c.853-.175 1.522-.935 1.464-1.883a18.659 18.659 0 00-3.732-10.104 1.837 1.837 0 00-1.47-.725h-1.512z" />
                  <path d="M19.5 19.5a1.5 1.5 0 10-3 0 1.5 1.5 0 003 0z" />
                </svg>
              </div>
              <div>
                <h1 className="text-base sm:text-lg font-bold text-white leading-tight">
                  Car Deal Finder
                </h1>
                <p className="text-xs text-slate-400 leading-tight hidden sm:block">
                  لقطات السيارات في السعودية
                </p>
              </div>
            </div>

            {/* Right side badge */}
            <div className="flex items-center gap-2">
              <span className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-slate-800 text-xs text-slate-400 border border-slate-700">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                Live Market Data
              </span>
              <span className="text-xs text-slate-500 hidden md:block">🇸🇦 Saudi Arabia</span>
            </div>
          </div>
        </header>

        {/* Main content */}
        <main className="max-w-screen-2xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          {children}
        </main>

        {/* Footer */}
        <footer className="border-t border-slate-800 mt-12">
          <div className="max-w-screen-2xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-slate-500">
            <span>Car Deal Finder — لقطات السيارات &copy; {new Date().getFullYear()}</span>
            <span>Data sourced from Haraj, Syarah, Motory</span>
          </div>
        </footer>
      </body>
    </html>
  );
}
