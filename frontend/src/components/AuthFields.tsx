import { useState, type ReactNode } from "react";
import { IconEye, IconEyeOff, IconLock, IconMail } from "./Icons";

interface BaseProps {
  id: string; label: string; value: string; onChange: (v: string) => void;
  placeholder?: string; testId?: string; required?: boolean; disabled?: boolean; readOnly?: boolean;
  autoComplete?: string; hint?: ReactNode;
}

export function IconInput({ icon, type = "text", ...p }: BaseProps & { icon: ReactNode; type?: string }) {
  return (
    <div className="qx-field">
      <label htmlFor={p.id}>{p.label}</label>
      <div className="qx-input-wrap">
        <span className="qx-input-icon">{icon}</span>
        <input id={p.id} className="qx-input qx-input-with-icon" type={type} placeholder={p.placeholder}
          value={p.value} onChange={(e) => p.onChange(e.target.value)} required={p.required}
          disabled={p.disabled} readOnly={p.readOnly} autoComplete={p.autoComplete} data-testid={p.testId} />
      </div>
      {p.hint && <div className="qx-hint">{p.hint}</div>}
    </div>
  );
}

export function EmailInput(p: BaseProps) {
  return <IconInput {...p} type="email" icon={<IconMail width={16} height={16} />} />;
}

export function passwordStrength(v: string): number {
  let n = 0;
  if (v.length >= 12) n++;
  if (/[a-z]/.test(v) && /[A-Z]/.test(v)) n++;
  if (/\d/.test(v)) n++;
  if (/[^A-Za-z0-9]/.test(v)) n++;
  return n;
}

export function PasswordInput({ showStrength, ...p }: BaseProps & { showStrength?: boolean }) {
  const [show, setShow] = useState(false);
  const score = passwordStrength(p.value);
  return (
    <div className="qx-field">
      <label htmlFor={p.id}>{p.label}</label>
      <div className="qx-input-wrap">
        <span className="qx-input-icon"><IconLock width={16} height={16} /></span>
        <input id={p.id} className="qx-input qx-input-with-icon qx-input-with-action" type={show ? "text" : "password"}
          placeholder={p.placeholder} value={p.value} onChange={(e) => p.onChange(e.target.value)}
          required={p.required} autoComplete={p.autoComplete} data-testid={p.testId} />
        <button type="button" className="qx-input-action" onClick={() => setShow((s) => !s)} aria-label={show ? "Hide password" : "Show password"}>
          {show ? <IconEyeOff width={17} height={17} /> : <IconEye width={17} height={17} />}
        </button>
      </div>
      {showStrength && (
        <div className="qx-strength" aria-hidden="true">
          {[1, 2, 3, 4].map((i) => <span key={i} className={i <= score ? "on" : ""} />)}
        </div>
      )}
      {p.hint && <div className="qx-hint">{p.hint}</div>}
    </div>
  );
}


/** Public Publisher registration password policy. Mirrors the backend
 * (schemas/auth.py::validate_publisher_password) 1:1; the backend enforces it
 * independently - this is only the live indicator. */
export const PASSWORD_RULES: { key: string; label: string; test: (v: string) => boolean }[] = [
  { key: "letters", label: "At least 5 letters", test: (v) => (v.match(/\p{L}/gu) ?? []).length >= 5 },
  { key: "uppercase", label: "At least 1 uppercase letter", test: (v) => /\p{Lu}/u.test(v) },
  { key: "number", label: "At least 1 number", test: (v) => /\d/.test(v) },
  { key: "special", label: "At least 1 special character", test: (v) => /[^\p{L}\p{N}\s]/u.test(v) },
];

export function passwordRulesMet(v: string): boolean {
  return PASSWORD_RULES.every((r) => r.test(v));
}

export function PasswordRules({ value, confirm }: { value: string; confirm?: string }) {
  const met = PASSWORD_RULES.filter((r) => r.test(value)).length;
  return (
    <div className="qx-pw-rules" data-testid="password-rules" aria-live="polite">
      <div className="qx-strength" aria-hidden="true">
        {PASSWORD_RULES.map((r, i) => <span key={r.key} className={i < met ? "on" : ""} />)}
      </div>
      <ul>
        {PASSWORD_RULES.map((r) => {
          const ok = r.test(value);
          return (
            <li key={r.key} className={ok ? "met" : "unmet"} data-testid={`pw-rule-${r.key}`} data-met={ok}>
              <span className="qx-pw-mark" aria-hidden="true">{ok ? "✓" : "○"}</span>
              {r.label}
              <span className="qx-sr-only">{ok ? " (met)" : " (not met)"}</span>
            </li>
          );
        })}
        {confirm !== undefined && (
          <li className={confirm.length > 0 && confirm === value ? "met" : "unmet"} data-testid="pw-rule-match"
              data-met={confirm.length > 0 && confirm === value}>
            <span className="qx-pw-mark" aria-hidden="true">{confirm.length > 0 && confirm === value ? "✓" : "○"}</span>
            Passwords match
          </li>
        )}
      </ul>
    </div>
  );
}


/** DigiSanchaar logo for auth pages. Both variants have transparent backgrounds (no
 * white rectangle); the dark variant only lightens the wordmark. The theme is
 * switched purely in CSS from <html data-theme>, so there is no flash. */
export function BrandLogo() {
  return (
    <>
      <img src="/quantix-logo-full.png" alt="DigiSanchaar" className="qx-login-logo qx-brand-light" />
      <img src="/quantix-logo-full-dark.png" alt="" aria-hidden="true" className="qx-login-logo qx-brand-dark" />
    </>
  );
}
