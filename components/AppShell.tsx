"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { AcudMark } from "@/components/AcudMark";

/**
 * One frame, one navigation, for everything behind the sign-in.
 *
 * Hiring and workforce planning were two apps wearing the same colours: each
 * had its own header, its own row of tabs, and a link across to the other one.
 * Which meant that finding anything depended on knowing which half it lived
 * in - and nobody using it thinks in halves. Every page is a tab now.
 *
 * The order is a sentence rather than a filing system, and it runs the way the
 * work does: where the organisation stands, which roles are short, who has
 * applied to them, what needs attention today - and then the questions a
 * planner asks about all of it. Grouping by which system a page came from was
 * the old arrangement, and nobody using it thinks in systems.
 */

const PAGES = [
  // Where things stand, and which roles are short.
  { href: "/workforce", label: "Overview", exact: true },
  { href: "/workforce/roles", label: "Roles" },

  // What is being done about it, and what needs attention today.
  { href: "/admin", label: "Jobs and applicants", exact: true },
  { href: "/admin/notifications", label: "Alerts" },

  // What if the assumptions change.
  { href: "/workforce/scenarios", label: "Scenarios" },

  // Why people leave, what they are paid, what replacing them costs. One
  // question in three parts, so they sit together and in that order.
  { href: "/workforce/turnover", label: "Turnover" },
  { href: "/workforce/compensation", label: "Compensation" },
  { href: "/workforce/performance", label: "Performance" },
  { href: "/workforce/cost", label: "Hiring cost" },

  // A tool rather than a view of the data. Last, deliberately.
  { href: "/admin/screen", label: "Quick check" },
];

export function AppShell({
  title,
  intro,
  children,
  wide = false,
}: {
  title?: string;
  intro?: string;
  children: React.ReactNode;
  /** Tables and dashboards need the room; a form does not. */
  wide?: boolean;
}) {
  const path = usePathname();
  const width = wide ? "max-w-6xl" : "max-w-5xl";

  const isHere = (page: { href: string; exact?: boolean }) =>
    page.exact ? path === page.href : path.startsWith(page.href);

  const tab = (page: { href: string; label: string; exact?: boolean }) => (
    <Link
      key={page.href}
      href={page.href}
      className={`chip ${
        isHere(page)
          ? "bg-accent text-accent-ink"
          : "raised text-muted hover:text-ink"
      }`}
    >
      {page.label}
    </Link>
  );

  return (
    <div className="min-h-dvh">
      <header className="page-header">
        <div className={`mx-auto ${width} px-6 py-3`}>
          <AcudMark subtitle="Recruitment and workforce" />

          <nav className="mt-2.5 flex flex-wrap items-center gap-1">
            {PAGES.map(tab)}
          </nav>
        </div>
      </header>

      <main className={`mx-auto ${width} space-y-6 px-6 py-8`}>
        {title && (
          <div>
            <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
            {intro && (
              <p className="mt-1 max-w-[70ch] text-sm text-muted">{intro}</p>
            )}
          </div>
        )}
        {children}
      </main>

      <DataFootnote path={path} />
    </div>
  );
}

/**
 * Where the numbers came from, said once and quietly.
 *
 * It used to be a coloured box at the top of every page, repeating the same
 * paragraph seven times - which is how a caveat stops being read. It is not
 * dropped, because two of these pages show figures that are not ACUD's and
 * saying nothing would present them as though they were. It is one line, at
 * the bottom, on the pages it actually applies to.
 */
function DataFootnote({ path }: { path: string }) {
  const planning = path.startsWith("/workforce");
  const pay = path.startsWith("/workforce/compensation");
  const cost = path.startsWith("/workforce/cost");
  if (!planning) return null;

  return (
    <footer className="mx-auto max-w-6xl px-6 pb-8">
      <p className="border-t pt-4 text-xs leading-relaxed text-muted">
        {pay
          ? "Pay figures on this page are simulated, not ACUD's payroll — the dataset carries none."
          : cost
            ? "Rates start from illustrative figures by seniority. Put your own in the boxes and every total recalculates."
            : "Headcount figures come from a frozen forecast — a Lasso regression trained on quarterly records for 2020–2026, unchanged since — not from live HR data."}
      </p>
    </footer>
  );
}
