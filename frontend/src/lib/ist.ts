/** All report timestamps are shown in Indian Standard Time, whatever the viewer's device zone. */
export function formatIST(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value.endsWith("Z") || /[+-]\d\d:?\d\d$/.test(value) ? value : value + "Z");
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: true,
  }) + " IST";
}
