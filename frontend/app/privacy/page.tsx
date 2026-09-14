import Link from "next/link";

export const metadata = { title: "Privacy Policy — Meridian" };

const SECTIONS = [
  { id: "who-we-are", label: "Who we are" },
  { id: "what-we-collect", label: "Information we collect" },
  { id: "how-we-use-it", label: "How we use it" },
  { id: "ai-processing", label: "How your data reaches an AI model" },
  { id: "third-parties", label: "Third parties we rely on" },
  { id: "payment-security", label: "Payment security" },
  { id: "cookies", label: "Cookies and similar technologies" },
  { id: "security", label: "How we protect your data" },
  { id: "retention", label: "Data retention" },
  { id: "international", label: "International data transfers" },
  { id: "children", label: "Children's privacy" },
  { id: "your-rights", label: "Your rights" },
  { id: "changes", label: "Changes to this policy" },
  { id: "contact", label: "Contact" },
] as const;

function Section({
  id, title, children,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="mb-10 scroll-mt-24">
      <h2 className="text-[17px] font-medium text-ink tracking-tight mb-3 pb-2 border-b border-line">
        {title}
      </h2>
      <div className="flex flex-col gap-3 text-[13.5px] text-ink-soft leading-relaxed">{children}</div>
    </section>
  );
}

export default function PrivacyPolicyPage() {
  return (
    <div className="min-h-screen bg-paper">
      <div className="max-w-5xl mx-auto px-6 md:px-8 py-16">
        <Link href="/" className="text-[15px] font-semibold tracking-tight text-ink mb-1 inline-block">
          Meridian
        </Link>
        <h1 className="text-[28px] font-medium text-ink tracking-tight mb-1.5 mt-3">Privacy Policy</h1>
        <p className="text-[12.5px] text-ink-soft mb-12">
          Effective September 2026 · Meridian Techverse Limited
        </p>

        <div className="md:grid md:grid-cols-[200px_1fr] md:gap-12">
          {/* Table of contents — sticky on wide screens, matching the
              same "orient the reader before the wall of text" job a
              printed contract's own section list plays. Purely
              navigational; every anchor points at a Section id below. */}
          <nav className="hidden md:block sticky top-16 self-start text-[12.5px] text-ink-soft leading-relaxed">
            <div className="text-[11px] font-medium text-ink uppercase tracking-wide mb-3">On this page</div>
            <ul className="flex flex-col gap-2">
              {SECTIONS.map((s) => (
                <li key={s.id}>
                  <a href={`#${s.id}`} className="hover:text-teal-deep transition-colors">
                    {s.label}
                  </a>
                </li>
              ))}
            </ul>
          </nav>

          <div className="max-w-2xl">
            <Section id="who-we-are" title="Who we are">
              <p>
                Meridian is operated by <strong className="text-ink font-medium">Meridian Techverse
                Limited</strong>, a company incorporated in Nigeria. This policy explains what
                information we collect through getmeridiananalytics.com and the Meridian application
                (together, the &quot;Service&quot;), why we collect it, and how it is handled.
              </p>
            </Section>

            <Section id="what-we-collect" title="Information we collect">
              <p>
                <strong className="text-ink font-medium">Account information.</strong> Your email
                address, company name, and a password, stored as a salted cryptographic hash — never
                in plain text.
              </p>
              <p>
                <strong className="text-ink font-medium">Connected data source credentials.</strong>{" "}
                If you connect a database, its host, username, and password are encrypted at rest
                before being stored. Meridian does not store a copy of your underlying business
                data — each question runs a live, read-only, authorized query against your own
                database at the moment you ask it.
              </p>
              <p>
                <strong className="text-ink font-medium">Uploaded documents.</strong> If you upload a
                PDF, Word, PowerPoint, Excel, or CSV file, its extracted text is stored so you can ask
                questions about it, until you delete it.
              </p>
              <p>
                <strong className="text-ink font-medium">Payment information.</strong> Handled
                entirely by Paystack — see &quot;Payment security&quot; below. Meridian never receives
                or stores your card number, expiry date, or CVV.
              </p>
              <p>
                <strong className="text-ink font-medium">Usage and audit data.</strong> Every query,
                connection change, sign-in, and export is recorded in a hash-chained audit log for your
                organization&apos;s own security and accountability. This log is visible to your own
                account&apos;s administrators — it is not sold, shared, or used for any other purpose.
              </p>
            </Section>

            <Section id="how-we-use-it" title="How we use it">
              <p>
                We use the information above to provide and secure the Service: authenticating you,
                running the queries and analyses you request, enforcing the access controls your
                organization configures, billing your subscription, sending transactional emails
                (welcome messages, invites, security notifications), and investigating misuse or
                security incidents. We do not use your connected business data or document content to
                train any model, and we do not sell personal information.
              </p>
            </Section>

            <Section id="ai-processing" title="How your data reaches an AI model">
              <p>
                When you ask a question, the relevant authorized schema (table and column names, never
                raw records beyond what your question&apos;s result actually returns), the computed
                result, and any document text you have attached are sent to Anthropic&apos;s Claude API
                to generate a plain-English explanation. Meridian is read-only by design — the AI can
                query and explain; it cannot write, alter, or delete anything in your connected
                systems.
              </p>
            </Section>

            <Section id="third-parties" title="Third parties we rely on">
              <p>Meridian uses a small number of specialist providers, each for exactly one job:</p>
              <ul className="list-disc pl-5 flex flex-col gap-1.5">
                <li><strong className="text-ink font-medium">Anthropic</strong> — processes your questions and data to generate answers.</li>
                <li><strong className="text-ink font-medium">Paystack</strong> — processes subscription payments; Meridian never sees or stores your card details directly.</li>
                <li><strong className="text-ink font-medium">Resend</strong> — delivers transactional emails (welcome, invites, security notifications).</li>
                <li><strong className="text-ink font-medium">Railway</strong> — hosts the application and its database.</li>
              </ul>
              <p>None of these providers is permitted to use your data for its own purposes beyond providing its service to us.</p>
            </Section>

            <Section id="payment-security" title="Payment security">
              <p>
                All payments are processed by <strong className="text-ink font-medium">Paystack</strong>,
                a PCI DSS Level 1 certified payment processor — the highest level of certification in
                the payments industry. Your card details are entered directly into Paystack&apos;s
                secure checkout and never pass through Meridian&apos;s own servers. We receive only a
                confirmation that payment succeeded and a reference number for our records.
              </p>
            </Section>

            <Section id="cookies" title="Cookies and similar technologies">
              <p>
                Meridian uses only the minimum browser storage required to keep you signed in during a
                session and to remember interface preferences (such as a collapsed panel). We do not
                use third-party advertising or cross-site tracking cookies.
              </p>
            </Section>

            <Section id="security" title="How we protect your data">
              <p>
                Two-factor authentication (with self-service recovery), encrypted credentials, row- and
                column-level access control enforced on every query, and a tamper-evident audit trail —
                security is checked on every request, not configured once and forgotten. See
                &quot;Built for a real security review&quot; on our homepage for specifics.
              </p>
            </Section>

            <Section id="retention" title="Data retention">
              <p>
                Your data is retained for as long as your account is active. If you delete a document,
                a connection, or your account, the underlying records are removed. If you need something
                deleted outside of that, contact us at the address below and we will handle it directly.
              </p>
            </Section>

            <Section id="international" title="International data transfers">
              <p>
                Meridian&apos;s infrastructure and service providers may process data outside Nigeria.
                Where this occurs, we rely on providers that maintain appropriate technical and
                contractual safeguards for cross-border data processing.
              </p>
            </Section>

            <Section id="children" title="Children's privacy">
              <p>
                Meridian is a business analytics product intended for organizations and their employees.
                It is not directed at, and we do not knowingly collect information from, individuals
                under 18.
              </p>
            </Section>

            <Section id="your-rights" title="Your rights">
              <p>
                You can request a copy of your account&apos;s data, correction of inaccurate
                information, or deletion of your account at any time by contacting us at{" "}
                <a href="mailto:hello@getmeridiananalytics.com" className="text-teal hover:text-teal-deep transition-colors">
                  hello@getmeridiananalytics.com
                </a>.
              </p>
            </Section>

            <Section id="changes" title="Changes to this policy">
              <p>
                If this policy changes materially, we will update the effective date at the top of this
                page and, where the change is significant, notify account administrators by email.
              </p>
            </Section>

            <Section id="contact" title="Contact">
              <p>
                Questions about this policy or your data:{" "}
                <a href="mailto:hello@getmeridiananalytics.com" className="text-teal hover:text-teal-deep transition-colors">
                  hello@getmeridiananalytics.com
                </a>
              </p>
            </Section>
          </div>
        </div>
      </div>
    </div>
  );
}
