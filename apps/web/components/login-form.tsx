"use client";

import { useState, type FormEvent } from "react";

import { login } from "@/lib/api/auth";
import { copy } from "@/lib/copy";
import { useSession } from "@/lib/session/session-context";

export interface LoginFormProps {
  onSuccess: () => void;
}

/** Minimal, premium login: email + password, one CTA. No signup, no password reset, no OAuth, no
 * remember-me - none of those exist yet (see docs/architecture/oggi-ui-v1.md, "Login"). */
export function LoginForm({ onSuccess }: LoginFormProps) {
  const { setSession } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return; // blocks a double submit (e.g. a second Enter/click mid-flight)
    setSubmitting(true);
    setError(null);

    const result = await login({ email, password });

    if (result.ok) {
      setSession(result.data);
      setPassword("");
      onSuccess();
      return;
    }

    // The backend's own error is already generic (INVALID_CREDENTIALS covers unknown email,
    // wrong password AND a locked account alike) - never show anything more specific than that.
    setError(result.code === "INVALID_CREDENTIALS" ? copy.login.invalidCredentials : copy.login.genericError);
    setPassword("");
    setSubmitting(false);
  }

  return (
    <form className="login-form" onSubmit={(event) => void handleSubmit(event)} noValidate>
      <h1 className="login-form__heading">{copy.login.heading}</h1>

      <label className="login-form__field" htmlFor="login-email">
        {copy.login.emailLabel}
      </label>
      <input
        id="login-email"
        name="email"
        type="email"
        autoComplete="email"
        required
        value={email}
        disabled={submitting}
        onChange={(event) => setEmail(event.target.value)}
      />

      <label className="login-form__field" htmlFor="login-password">
        {copy.login.passwordLabel}
      </label>
      <input
        id="login-password"
        name="password"
        type="password"
        autoComplete="current-password"
        required
        value={password}
        disabled={submitting}
        onChange={(event) => setPassword(event.target.value)}
      />

      {error ? (
        <p className="login-form__error" role="alert">
          {error}
        </p>
      ) : null}

      <button type="submit" disabled={submitting}>
        {submitting ? copy.login.submitting : copy.login.submit}
      </button>
    </form>
  );
}
