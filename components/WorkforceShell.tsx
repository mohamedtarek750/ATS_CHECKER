"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Note } from "./Shell";
import { FORECAST } from "@/lib/workforce";

const PAGES = [
  { href: "/workforce", label: "Overview" },
  { href: "/workforce/roles", label: "Roles" },
  { href: "/workforce/performance", label: "Performance" },
  { href: "/workforce/turnover", label: "Turnover" },
  { href: "/workforce/cost", label: "Hiring cost" },
];

/**
 * The frame every workforce page sits in.
 *
 * The link across to the ATS is deliberate and so is its direction: workforce
 * planning says how many people a role is short, and the ATS is where the
 * people to fill it arrive. Two apps on two domains would break that in half.
 */
export function WorkforceShell({
  title,
  intro,
  children,
}: {
  title: string;
  intro?: string;
  children: React.ReactNode;
}) {
  const path = usePathname();

  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-10 border-b bg-bg/85 backdrop-blur">
        <div className="mx-auto max-w-5xl px-6 py-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <h1 className="truncate text-[15px] font-semibold tracking-tight">
                ACUD · Workforce planning
              </h1>
              <p className="truncate text-xs text-muted">
                Where the gaps are, before anybody is hired
              </p>
            </div>
            <Link href="/admin" className="btn-ghost shrink-0 text-sm">
              Vacancies &amp; applicants →
            </Link>
          </div>

          <nav className="mt-2.5 flex flex-wrap gap-1">
            {PAGES.map((page) => {
              const active =
                page.href === "/workforce"
                  ? path === "/workforce"
                  : path.startsWith(page.href);
              return (
                <Link
                  key={page.href}
                  href={page.href}
                  className={`chip ${
                    active
                      ? "bg-accent text-accent-ink"
                      : "raised text-muted hover:text-ink"
                  }`}
                >
                  {page.label}
                </Link>
              );
            })}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-6 px-6 py-8">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
          {intro && (
            <p className="mt-1 max-w-[70ch] text-sm text-muted">{intro}</p>
          )}
        </div>
        {children}
      </main>
    </div>
  );
}

/**
 * Says, on every page, that these numbers are a snapshot.
 *
 * The ATS figures next door change every time somebody applies; these have not
 * moved since the model was exported. Two kinds of number under one roof, one
 * live and one frozen, is how a reader comes to trust the wrong one.
 */
export function ForecastNote() {
  return (
    <Note>
      <strong className="text-ink">A frozen forecast, not live data.</strong>{" "}
      Produced once by a {FORECAST.model} trained on {FORECAST.trainedOn}, and
      unchanged since. {FORECAST.note} Nothing on the applicant side updates
      these figures.
    </Note>
  );
}
