import { redirect } from "next/navigation";

/**
 * The open-application page moved to the site's front door.
 *
 * Kept as a redirect rather than deleted: this path was handed out, and a link
 * somebody already has should not turn into a 404.
 */
export default function ApplyRedirect() {
  redirect("/");
}
