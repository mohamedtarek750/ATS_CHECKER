"use client";

/**
 * Finance, and the one number on this page they actually need.
 *
 * The hiring cost page is the only screen in the system whose subject is money
 * rather than people, so it is the only one Finance has any reason to open -
 * and until now the way to tell them what it said was to read the total out
 * over the phone. This puts the total, the positions behind it, and the
 * departments carrying most of it into a message addressed to them.
 *
 * WHY WHATSAPP AND NOT AN API
 * ---------------------------
 * A wa.me link needs no account, no credential, no credit and no provider that
 * can be down. It opens WhatsApp with the message written and Finance's number
 * in the To field, and a person presses send - which is the same rule the
 * candidate emails follow, and for the same reason: the number moves the
 * moment somebody edits the rates above, and a figure that changes on its own
 * should not leave the building on its own either.
 *
 * ONE LINK IS ONE CHAT
 * --------------------
 * A wa.me link opens a single conversation - WhatsApp has no format for
 * addressing two people at once, and there is no arrangement of this code that
 * changes that. So more than one number means one button each, carrying the
 * identical message. Two presses instead of one, which is the honest cost of
 * not having a WhatsApp Business account behind this.
 *
 * THE NUMBERS ARE NOT IN THIS FILE
 * --------------------------------
 * They are real people's mobiles and this repository is public. They come from
 * NEXT_PUBLIC_FINANCE_PHONE, comma-separated the way every other list of
 * recipients in this system is - and with it unset the card says so rather
 * than quietly disappearing, because a contact panel that vanishes when
 * misconfigured looks exactly like one nobody asked for.
 */

const NAME = process.env.NEXT_PUBLIC_FINANCE_NAME || "Finance";

/** Digits only, which is what wa.me and tel: both want. */
const CONTACTS = (process.env.NEXT_PUBLIC_FINANCE_PHONE ?? "")
  .split(",")
  .map((one) => ({ shown: one.trim(), digits: one.replace(/[^\d]/g, "") }))
  .filter((one) => one.digits.length >= 8);

export function FinanceContact({
  total,
  positions,
  roles,
  topDepartments,
  rates,
}: {
  total: number;
  positions: number;
  roles: number;
  /** [department, cost], heaviest first. */
  topDepartments: [string, number][];
  rates: Record<string, number>;
}) {
  const money = (n: number) => `$${Math.round(n).toLocaleString("en-US")}`;

  // Written as somebody would write it, not as a form dump - it arrives in a
  // chat, next to messages from people.
  const message = [
    "ACUD — cost of the current hiring gap",
    "",
    `${money(total)} to fill ${positions} positions across ${roles} roles.`,
    "",
    ...topDepartments
      .slice(0, 3)
      .map(([department, cost]) => `${department}: ${money(cost)}`),
    "",
    "At " +
      Object.entries(rates)
        .map(([level, rate]) => `${level} ${money(rate)}`)
        .join(", ") +
      " per hire.",
  ].join("\n");

  if (CONTACTS.length === 0) {
    return (
      <div className="card px-5 py-4">
        <h3 className="text-sm font-medium">Send this to Finance</h3>
        <p className="mt-1.5 text-sm leading-relaxed text-muted">
          Set <code>NEXT_PUBLIC_FINANCE_PHONE</code> in the deployment&rsquo;s
          environment — with the country code, like{" "}
          <code>+20 10 XXXXXXXX</code>, and separated by commas for more than
          one — and this becomes a button per number that opens WhatsApp with
          the figures below already written.
        </p>
      </div>
    );
  }

  return (
    <div className="card px-5 py-4">
      <h3 className="text-sm font-medium">Send this to {NAME}</h3>

      <p className="mt-1.5 text-sm leading-relaxed text-muted">
        The total above, the positions behind it, and the three departments
        carrying most of it — written out and addressed to {NAME}. It follows
        whatever rates are in the boxes, so correct them first and the message
        corrects itself.
        {CONTACTS.length > 1 && (
          <>
            {" "}
            A WhatsApp link opens one conversation, so each number is its own
            button carrying the same message.
          </>
        )}
      </p>

      <div className="mt-3 space-y-2">
        {CONTACTS.map((contact) => (
          <div key={contact.digits} className="flex flex-wrap items-center gap-2">
            {/* A link, not a script. A control that builds a URL and then opens
                it after any wait is one the browser blocks without saying so. */}
            <a
              href={`https://wa.me/${contact.digits}?text=${encodeURIComponent(message)}`}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-primary text-sm"
            >
              WhatsApp
            </a>
            <a href={`tel:+${contact.digits}`} className="btn-ghost text-sm">
              Call
            </a>
            <span className="text-xs tabular-nums text-muted">
              {contact.shown}
            </span>
          </div>
        ))}
      </div>

      <details className="mt-3">
        <summary className="cursor-pointer text-xs text-muted">
          What it will say
        </summary>
        <pre className="mt-2 overflow-x-auto whitespace-pre-wrap rounded-lg bg-raised px-4 py-3 text-xs leading-relaxed text-muted">
          {message}
        </pre>
      </details>
    </div>
  );
}
