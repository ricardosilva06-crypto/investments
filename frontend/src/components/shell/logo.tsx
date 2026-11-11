export function Logo({ className = "size-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden="true">
      <defs>
        <linearGradient id="ii-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#9fb4ff" />
          <stop offset="1" stopColor="#5b6cf0" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="16" fill="url(#ii-g)" />
      <path d="M17 44V22M27 44V30M37 44V26M47 44V18" stroke="#0d0f13" strokeWidth="5.5" strokeLinecap="round" />
    </svg>
  );
}
