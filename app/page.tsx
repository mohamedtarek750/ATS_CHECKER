"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AcudMark } from "@/components/AcudMark";
import { publicPostings, type PublicPosting } from "@/lib/api";

/**
 * The landing page. Two doors and nothing else.
 *
 * Everybody who reaches this site is one of two people: somebody who wants to
 * apply, or somebody on the hiring team. Putting the form itself here made the
 * first visible thing a request for a stranger's name, address and CV, before
 * saying whose site it is or what is open.
 *
 * The count of open roles is the one live number here, and it is only shown
 * once it has actually loaded - a "0 roles open" flash while the request is in
 * flight would turn somebody away at the door.
 */
export default function Landing() {
  const [jobs, setJobs] = useState<PublicPosting[] | null>(null);

  useEffect(() => {
    publicPostings()
      .then(setJobs)
      .catch(() => setJobs([]));
  }, []);

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="page-header">
        <div className="mx-auto flex w-full max-w-5xl items-center justify-between gap-3 px-6 py-3.5">
          <AcudMark subtitle="Careers" />
          <Link href="/admin" className="btn-ghost shrink-0 text-sm">
            Staff sign in
          </Link>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col justify-center px-6 py-16 sm:py-24">
        <div className="max-w-[46rem] animate-rise">
          <p className="eyebrow">Administrative Capital for Urban Development</p>

          <h1 className="display mt-3 text-[clamp(2.1rem,6vw,3.6rem)] leading-[1.05]">
            Build the city
            <br />
            that is still being drawn.
          </h1>

          <p className="mt-5 max-w-[46ch] text-[17px] leading-relaxed text-muted">
            ACUD is delivering Egypt&rsquo;s New Administrative Capital — its
            districts, its utilities, and the systems that run them. Send us
            your CV and the hiring team will read it.
          </p>

          <div className="mt-9 flex flex-wrap items-center gap-3">
            <Link href="/apply" className="btn-primary px-6 py-3 text-[15px]">
              Apply
            </Link>
            <Link href="/admin" className="btn-ghost px-6 py-3 text-[15px]">
              Sign in
            </Link>
          </div>

          {/* Live, and the only number on this page. Absent until it arrives. */}
          {jobs !== null && jobs.length > 0 && (
            <p className="mt-6 flex items-center gap-2 text-sm text-muted">
              <span
                className="inline-block h-1.5 w-1.5 rounded-full"
                style={{ background: "rgb(var(--good))" }}
                aria-hidden
              />
              {jobs.length} role{jobs.length === 1 ? "" : "s"} open right now
            </p>
          )}
        </div>

        {/* The roles themselves, once there are any. A careers page that names
            nothing it is hiring for is a form with a logo above it. */}
        {jobs !== null && jobs.length > 0 && (
          <div className="mt-14 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {jobs.slice(0, 6).map((job) => (
              <Link
                key={job.slug}
                href={`/apply/${job.slug}`}
                className="card animate-rise px-5 py-4 transition hover:border-brand"
              >
                <p className="font-medium">{job.title}</p>
                {job.summary && (
                  <p className="mt-1.5 line-clamp-3 text-sm leading-relaxed text-muted">
                    {job.summary}
                  </p>
                )}
                <p className="mt-3 text-sm font-medium text-brand">Apply →</p>
              </Link>
            ))}
          </div>
        )}
      </main>

      <footer className="mx-auto w-full max-w-5xl px-6 pb-10">
        <p className="border-t pt-5 text-xs leading-relaxed text-muted">
          Administrative Capital for Urban Development · العاصمة الإدارية
          للتنمية العمرانية
          <span className="mt-1 block">
            Your details are used for hiring and nothing else, and only the
            hiring team can open your CV.
          </span>
        </p>
      </footer>
    </div>
  );
}
