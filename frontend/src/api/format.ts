const SYMBOLS: Record<string, string> = { INR: "₹", USD: "$", EUR: "€", GBP: "£" };

/** "₹10 INR" / "$10 USD". Currency comes from the API (never guessed here);
 * a missing payout renders as an em dash. */
export function formatPayout(amount: number | null | undefined, currency: string | null | undefined): string {
  if (amount === null || amount === undefined) return "—";
  const cur = currency ?? "";
  const n = Number.isInteger(amount) ? String(amount) : amount.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
  return `${SYMBOLS[cur] ?? ""}${n}${cur ? ` ${cur}` : ""}`;
}

export function formatLocation(city?: string | null, state?: string | null, country?: string | null): string {
  return [city, state, country].filter(Boolean).join(", ");
}

export function formatDateTime(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : "";
}
