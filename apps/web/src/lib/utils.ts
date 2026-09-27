/** Shared formatting helpers. Kept tiny and dependency-free. */

/** Compact money for KPI tiles and deal cards: 96000 → "$96K". */
export function money(amount: number | null | undefined, currency = "$"): string {
  if (amount === null || amount === undefined) return "—";
  const abs = Math.abs(amount);
  if (abs >= 1_000_000) return `${currency}${(amount / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${currency}${Math.round(amount / 1_000)}K`;
  return `${currency}${amount.toFixed(0)}`;
}

/** ISO timestamp → "Jul 15, 11:30". Returns "—" for null. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** ISO timestamp → "Jul 15, 2026". */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

/** "pending_approval" → "Pending Approval" — for enum values with no meta map. */
export function humanize(value: string): string {
  return value
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}
