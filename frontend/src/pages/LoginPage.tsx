import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { ErrorBanner } from "../components/Common";
import { BrandLogo, EmailInput, PasswordInput } from "../components/AuthFields";

export function LoginPage() {
  const { login, error } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await login(email, password);
      navigate("/", { replace: true });
    } catch {
      /* error already surfaced via useAuth().error */
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="qx-login-wrap">
      <div className="qx-login-card" data-testid="login-card">
        <BrandLogo />
        <p className="qx-login-subtitle">Enter your credentials to access your account</p>
        <ErrorBanner message={error} />
        <form onSubmit={handleSubmit}>
          <EmailInput id="email" label="Email" placeholder="name@example.com" value={email} onChange={setEmail}
            required autoComplete="username" testId="login-email-input" />
          <PasswordInput id="password" label="Password" placeholder="••••••••" value={password} onChange={setPassword}
            required autoComplete="current-password" testId="login-password-input" />
          <button
            className="qx-btn qx-btn-primary"
            style={{ width: "100%", marginTop: 6 }}
            disabled={submitting}
            type="submit"
            data-testid="login-submit-button"
          >
            {submitting ? "Signing in…" : "Sign In"}
          </button>
        </form>
        <div className="qx-divider">OR</div>
        <Link to="/register" className="qx-btn qx-btn-outline" style={{ width: "100%" }} data-testid="login-register-link">
          Register
        </Link>
      </div>
    </div>
  );
}
