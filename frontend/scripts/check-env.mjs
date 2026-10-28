// Build-time guard for hosted builds (Netlify sets NETLIFY=true). Prints presence/validity only, never secrets.
// Without VITE_API_BASE_URL the app calls /api/v1 on the Netlify origin, which answers with index.html -> login "fails" silently.
const onHost = process.env.NETLIFY === "true" || process.env.CI === "true";
const v = (process.env.VITE_API_BASE_URL || "").trim();
if (!onHost) process.exit(0);
const problems = [];
if (!v) problems.push("VITE_API_BASE_URL is not set (set it in Netlify > Site configuration > Environment variables).");
else if (!/^https:\/\/[^\s/]+(\/.*)?$/.test(v)) problems.push("VITE_API_BASE_URL must be an absolute https URL of the backend, e.g. https://<service>.onrender.com/api/v1");
else if (/localhost|127\.0\.0\.1/.test(v)) problems.push("VITE_API_BASE_URL points to localhost.");
for (const k of Object.keys(process.env)) {
  if (k.startsWith("VITE_") && /(SECRET|SERVICE_KEY|PASSWORD|PRIVATE)/i.test(k)) problems.push(`${k}: secrets must never be exposed through VITE_* variables.`);
}
if (problems.length) { console.error("Build blocked:\n - " + problems.join("\n - ")); process.exit(1); }
console.log("env check OK: VITE_API_BASE_URL is set (value not printed).");
