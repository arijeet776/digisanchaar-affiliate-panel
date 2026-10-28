import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { ErrorBanner } from "../components/Common";
import { BrandLogo, EmailInput, IconInput, PasswordInput, PasswordRules, passwordRulesMet } from "../components/AuthFields";
import { IconBuilding, IconPhone, IconProfile } from "../components/Icons";

type Step = "checking" | "invalid" | "details" | "done";

interface InvitePreview {
  valid: boolean;
  role?: "manager" | "publisher";
  target_email?: string;
  expires_at?: string;
}

/**
 * Public registration (Part 17): anyone with the Login page can register as a
 * Publisher - no invitation, Manager ID or token is required or shown. Status
 * is PENDING until a Super Admin approves. A legacy invitation link
 * (/register/<token>) still works: it is validated by the server and may
 * carry a Manager relationship, but the person never types it, and a
 * manager_id is never sent from the browser.
 */
export function RegisterPage() {
  const [params] = useSearchParams();
  const { token: pathToken } = useParams();
  const [step, setStep] = useState<Step>("checking");
  const [token, setToken] = useState("");
  const [invite, setInvite] = useState<InvitePreview | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [mobile, setMobile] = useState("");
  const [company, setCompany] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const raw = pathToken ?? params.get("invite") ?? params.get("token");
    if (!raw) {
      setStep("details"); // open Publisher registration - no invitation needed
      return;
    }
    let cancelled = false;
    api
      .get<InvitePreview>(`/invites/${encodeURIComponent(raw.trim())}`)
      .then((r) => {
        if (cancelled) return;
        if (!r.data.valid || !r.data.role) {
          setStep("invalid");
          return;
        }
        setToken(raw.trim());
        setInvite(r.data);
        setEmail(r.data.target_email ?? "");
        setStep("details");
      })
      .catch(() => !cancelled && setStep("invalid"));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathToken]);

  const role: "manager" | "publisher" = invite?.role ?? "publisher";
  const emailLocked = Boolean(invite?.target_email);

  async function submitDetails(e: FormEvent) {
    e.preventDefault();
    if (role === "publisher" && !passwordRulesMet(password)) {
      setError("Password must have at least 5 letters, 1 uppercase letter, 1 number and 1 special character.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.post(`/onboarding/${role}`, {
        ...(token ? { invite_token: token } : {}),
        email,
        password,
        display_name: displayName.trim(),
        mobile: mobile.trim() || undefined,
        ...(role === "publisher" ? { company: company.trim() || undefined } : {}),
      });
      setStep("done");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Signup failed");
    } finally {
      setBusy(false);
    }
  }

  const roleLabel = role === "manager" ? "Manager" : "Publisher";

  return (
    <div className="qx-login-wrap">
      <div className="qx-login-card" data-testid="register-card">
        <BrandLogo />

        {step === "checking" && (
          <p className="qx-login-subtitle" role="status" data-testid="register-checking">Checking your invitation…</p>
        )}

        {step === "invalid" && (
          <div className="qx-auth-notice" data-testid="register-invalid">
            <h2>This invitation can't be used</h2>
            <p>The link may have expired, already been used, or been revoked. You can still register without one.</p>
            <Link to="/register" className="qx-btn qx-btn-primary" style={{ width: "100%", marginBottom: 10 }} data-testid="register-continue-link">
              Register without an invitation
            </Link>
            <div className="qx-divider">OR</div>
            <Link to="/login" className="qx-btn qx-btn-outline" style={{ width: "100%" }} data-testid="register-login-link">
              Login
            </Link>
          </div>
        )}

        {step === "details" && (
          <>
            <p className="qx-login-subtitle">Create a new account to get started</p>
            <ErrorBanner message={error} />
            <form onSubmit={submitDetails}>
              <IconInput id="reg-name" label="Full Name" placeholder="John Doe" value={displayName} onChange={setDisplayName}
                required testId="register-name-input" icon={<IconProfile width={16} height={16} />} />
              <EmailInput id="reg-email" label="Email" placeholder="name@example.com" value={email} onChange={setEmail}
                required readOnly={emailLocked} autoComplete="email" testId="register-email-input" />
              <IconInput id="reg-mobile" label="Mobile *" placeholder="98765 43210" value={mobile} onChange={setMobile}
                required type="tel" autoComplete="tel" testId="register-mobile-input" icon={<IconPhone width={16} height={16} />} />
              {role === "publisher" && (
                <IconInput id="reg-company" label="Company *" placeholder="Acme Inc." value={company} onChange={setCompany}
                  required autoComplete="organization" testId="register-company-input" icon={<IconBuilding width={16} height={16} />} />
              )}
              <PasswordInput id="reg-password" label="Password" placeholder="••••••••" value={password} onChange={setPassword}
                required autoComplete="new-password" testId="register-password-input" />
              {role === "publisher" && <PasswordRules value={password} confirm={confirm} />}
              <PasswordInput id="reg-confirm" label="Confirm Password" placeholder="••••••••" value={confirm} onChange={setConfirm}
                required autoComplete="new-password" testId="register-confirm-input" />
              <button className="qx-btn qx-btn-primary" style={{ width: "100%" }} disabled={busy} type="submit" data-testid="register-submit-button">
                {busy ? "Creating account…" : "Create Account"}
              </button>
            </form>
            <div className="qx-divider">OR</div>
            <Link to="/login" className="qx-btn qx-btn-outline" style={{ width: "100%" }} data-testid="register-login-link">
              Login
            </Link>
          </>
        )}

        {step === "done" && (
          <div data-testid="register-done" style={{ textAlign: "center" }}>
            <div className="qx-badge pending" style={{ marginBottom: 14 }}>pending approval</div>
            <h3 style={{ marginBottom: 8 }}>Registration submitted</h3>
            <p style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.6 }}>
              Your {roleLabel.toLowerCase()} account is <strong>pending Super Admin approval</strong>. You can sign in
              only after a Super Admin approves it. No email verification is needed.
            </p>
            <Link to="/login" className="qx-btn qx-btn-primary" style={{ width: "100%", marginTop: 8 }} data-testid="register-done-login-link">
              Go to Sign In
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
