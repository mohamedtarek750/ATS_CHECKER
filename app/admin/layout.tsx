import { AdminGate } from "@/components/AdminGate";

/**
 * Everything under /admin is behind the sign-in.
 *
 * A layout rather than a check per page, so a page added later is protected by
 * default instead of by remembering. The API enforces the same rule
 * independently - this only decides what a person is shown.
 */
export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <AdminGate>{children}</AdminGate>;
}
