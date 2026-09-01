"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Note } from "./Shell";
import {
  authStatus,
  setAdminToken,
  whoAmI,
  type AdminUser,
  type AuthStatus,
} from "@/lib/api";

/**
 * Nothing behind this renders until somebody has signed in.
 *
 * The gate is only the visible half. Every admin endpoint checks the token for
 * itself, because a guard that lives in the browser is a guard an attacker can
 * skip by calling the API directly. This exists so a recruiter sees a sign-in
 * button instead of a wall of failed requests.
 */
export function AdminGate({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [user, setUser] = useState<AdminUser | null>(null);
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(true);

  const check = useCallback(async () => {
    setChecking(true);
    try {
      const state = await authStatus();
      setStatus(state);
      if (!state.required) {
        setUser({ email: "", name: "", picture: "" });
      } else if (state.configured) {
        // A token may still be in this tab's session from a moment ago.
        try {
          setUser(await whoAmI());
        } catch {
          setUser(null);
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not reach the server.");
    }
    setChecking(false);
  }, []);

  useEffect(() => {
    check();
  }, [check]);

  async function onCredential(token: string) {
    setAdminToken(token);
    setError("");
    try {
      setUser(await whoAmI());
    } catch (e) {
      setAdminToken("");
      setError(e instanceof Error ? e.message : "That sign-in was refused.");
    }
  }

  if (checking) {
    return <Centered><p className="text-sm text-muted">Checking…</p></Centered>;
  }

  if (error && !status) {
    return <Centered><Note tone="bad">{error}</Note></Centered>;
  }

  // A deployment where sign-in was never finished. Not a login failure, and
  // telling somebody to "sign in" would send them round a loop with no way out.
  if (status?.required && !status.configured) {
    return (
      <Centered>
        <Note tone="bad">
          <strong>The dashboard is not set up for sign-in.</strong>
          <span className="mt-2 block">
            Set <code>GOOGLE_OAUTH_CLIENT_ID</code> and{" "}
            <code>ATS_ADMIN_EMAILS</code> in the deployment&rsquo;s environment.
            Until then it stays shut, because it holds applicants&rsquo; CVs.
          </span>
        </Note>
      </Centered>
    );
  }

  if (!user) {
    return (
      <Centered>
        <div className="card animate-rise px-6 py-8 text-center">
          <h1 className="text-lg font-semibold">ACUD ATS</h1>
          <p className="mt-1.5 mb-5 text-sm text-muted">
            Sign in with the Google account your team put on the list.
          </p>
          <GoogleButton
            clientId={status?.client_id ?? ""}
            onCredential={onCredential}
          />
          {error && (
            <div className="mt-4 text-left">
              <Note tone="bad">{error}</Note>
            </div>
          )}
        </div>
      </Centered>
    );
  }

  return (
    <>
      {status && !status.required && (
        <div className="border-b bg-warn-wash px-6 py-2 text-center text-xs text-warn">
          Sign-in is switched off (<code>ATS_AUTH=off</code>). Anyone who can
          reach this page can read every applicant&rsquo;s CV.
        </div>
      )}
      {children}
    </>
  );
}

/**
 * Google's own button, drawn by Google's script.
 *
 * Deliberately not a hand-rolled OAuth flow. The token this produces is signed
 * by Google and verified by Google's library on the server; the browser never
 * holds a secret and this app never sees a password.
 */
function GoogleButton({
  clientId,
  onCredential,
}: {
  clientId: string;
  onCredential: (token: string) => void;
}) {
  const holder = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);
  // Kept in a ref so the callback Google holds always calls the current one.
  const latest = useRef(onCredential);
  latest.current = onCredential;

  useEffect(() => {
    if (!clientId) return;

    let cancelled = false;
    function draw() {
      const google = (window as unknown as { google?: any }).google;
      if (cancelled || !google?.accounts?.id || !holder.current) return;
      google.accounts.id.initialize({
        client_id: clientId,
        callback: (response: { credential?: string }) => {
          if (response?.credential) latest.current(response.credential);
        },
      });
      google.accounts.id.renderButton(holder.current, {
        theme: "outline",
        size: "large",
        width: 260,
        text: "signin_with",
      });
    }

    const existing = document.getElementById("google-identity");
    if (existing) {
      draw();
      return () => {
        cancelled = true;
      };
    }

    const script = document.createElement("script");
    script.id = "google-identity";
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.onload = draw;
    script.onerror = () => !cancelled && setFailed(true);
    document.head.appendChild(script);
    return () => {
      cancelled = true;
    };
  }, [clientId]);

  if (failed) {
    return (
      <Note tone="bad">
        Google&rsquo;s sign-in script could not be loaded. Check the connection
        and reload.
      </Note>
    );
  }
  return <div ref={holder} className="flex justify-center" />;
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-dvh">
      <main className="mx-auto w-full max-w-md px-6 py-16">{children}</main>
    </div>
  );
}
