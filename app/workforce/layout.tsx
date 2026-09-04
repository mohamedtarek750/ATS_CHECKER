import { AdminGate } from "@/components/AdminGate";

/**
 * Workforce planning is behind the same sign-in as the rest of the dashboard.
 *
 * It carries headcount, individual-role performance scores, turnover and salary
 * cost - internal figures, and in some hands more sensitive than the applicant
 * data next door. Building it as a second app would have meant a second sign-in
 * to write and keep in step; this reuses the one that already exists.
 */
export default function WorkforceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <AdminGate>{children}</AdminGate>;
}
