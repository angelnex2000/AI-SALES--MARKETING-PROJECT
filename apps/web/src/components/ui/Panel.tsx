export default function Panel({
  title,
  subtitle,
  action,
  children,
  className = "",
}: {
  title?: string;
  subtitle?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`glass-panel rounded-2xl p-6 shadow-xl border border-slate-800/80 ${className}`}>
      {(title || action) && (
        <div className="mb-4 flex items-center justify-between border-b border-slate-800/60 pb-3">
          <div>
            {title && <h2 className="font-display text-base font-semibold text-slate-100">{title}</h2>}
            {subtitle && <p className="text-xs text-slate-400 mt-0.5">{subtitle}</p>}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}
