import Link from "next/link";

export const metadata = { title: "Privacy Policy — Meridian" };

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="text-[16px] font-medium text-ink tracking-tight mb-3">{title}</h2>
      <div className="flex flex-col gap-3 text-[13.5px] text-ink-soft leading-relaxed">{children}</div>
    </section>
  );
}

export default function PrivacyPolicyPage() {
  return (
    <div className="min-h-screen bg-paper">
      <div className="max-w-2xl mx-auto px-8 py-16">
        <Link href="/" className="text-[15px] font-semibold tracking-tight text-ink mb-1 inline-block">
          Meridian
        </Link>
        <h1 className="text-[24px] font-medium text-ink tracking-tight mb-1 mt-3">Privacy Policy</h1>
        <p className="text-[12px] text-ink-soft mb-6">Last updated: September 2026</p>

        <div className="bg-amber-soft border border-amber rounded-[4px] px-4 py-3 mb-10 text-[12.5px] text-amber leading-relaxed">
          <strong className="font-medium">Draft, pending legal review.</strong> This document accurately
          describes what Meridian&apos;s software actually does today, but it has not yet been reviewed by
          a lawyer for legal completeness or jurisdiction-specific compliance (including Nigeria&apos;s
          NDPR). Treat it as a good-faith disclosure, not a substitute for formal legal counsel.
        </div>

        <Section title="Who we are">
          <p>
            Meridian is operated by <strong className="text-ink font-medium">Meridian Techverse Limited</strong>,
            a company registered in Nigeria. This policy explains what information we collect through
            getmeridiananalytics.com and the Meridian application, and how we handle it.
          </p>
        </Section>

        <Section title="What we collect">
          <p>
            <strong className="text-ink font-medium">Account information</strong>: your email address,
            company name, and a password — stored as a salted cryptographic hash, never in plain text.
          </p>
          <p>
            <strong className="text-ink font-medium">Connected data source credentials</strong>: if you
            connect a database, its host/username/password are encrypted at rest before being stored.
            Meridian never stores a copy of your underlying business data itself — each question runs a
            live, read-only, authorized query against your own database at the moment you ask it.
          </p>
          <p>
            <strong className="text-ink font-medium">Uploaded documents</strong>: if you upload a PDF,
            Word, PowerPoint, or Excel file, its extracted text is stored so you can ask questions about
            it, until you delete it.
          </p>
          <p>
            <strong className="text-ink font-medium">Usage and audit data</strong>: every query, connection
            change, sign-in, and export is recorded in a hash-chained audit log, for your own
            organization&apos;s security and accountability — this is visible to your own account&apos;s
            admins, not sold or used for any other purpose.
          </p>
        </Section>

        <Section title="How your data reaches an AI model">
          <p>
            When you ask a question, the relevant authorized schema (table/column names, never raw
            customer data beyond what your question&apos;s result actually returns), the computed result,
            and any document text you&apos;ve attached are sent to Anthropic&apos;s Claude API to generate
            the plain-English explanation. Meridian is read-only by design — the AI can query and explain,
            it cannot write, alter, or delete anything in your connected systems.
          </p>
        </Section>

        <Section title="Third parties we rely on">
          <p>Meridian uses a small number of specialist providers, each for exactly one job:</p>
          <ul className="list-disc pl-5 flex flex-col gap-1.5">
            <li><strong className="text-ink font-medium">Anthropic</strong> — processes your questions and data to generate answers.</li>
            <li><strong className="text-ink font-medium">Paystack</strong> — processes subscription payments; Meridian never sees or stores your card details directly.</li>
            <li><strong className="text-ink font-medium">Resend</strong> — delivers transactional emails (welcome, invites, security notifications).</li>
            <li><strong className="text-ink font-medium">Railway</strong> — hosts the application and its database.</li>
          </ul>
          <p>None of these providers are permitted to use your data for their own purposes beyond providing their service to us.</p>
        </Section>

        <Section title="How we protect it">
          <p>
            Two-factor authentication (with self-service recovery), encrypted credentials, row- and
            column-level access control enforced on every query, and a tamper-evident audit trail —
            security is checked on every request, not configured once and forgotten. See the
            &quot;Built for a real security review&quot; section on our homepage for specifics.
          </p>
        </Section>

        <Section title="How long we keep it">
          <p>
            Your data is retained for as long as your account is active. If you delete a document, a
            connection, or your account, the underlying records are removed. We don&apos;t yet have an
            automated data-retention/deletion schedule beyond explicit user action — if you need something
            deleted, contact us and we&apos;ll handle it directly.
          </p>
        </Section>

        <Section title="Your rights">
          <p>
            You can request a copy of your account&apos;s data, correction of inaccurate information, or
            deletion of your account at any time by contacting us at{" "}
            <a href="mailto:hello@getmeridiananalytics.com" className="text-teal hover:text-teal-deep transition-colors">
              hello@getmeridiananalytics.com
            </a>.
          </p>
        </Section>

        <Section title="Changes to this policy">
          <p>
            If this policy changes materially, we&apos;ll update the date at the top of this page and,
            where the change is significant, notify account admins by email.
          </p>
        </Section>

        <Section title="Contact">
          <p>
            Questions about this policy or your data:{" "}
            <a href="mailto:hello@getmeridiananalytics.com" className="text-teal hover:text-teal-deep transition-colors">
              hello@getmeridiananalytics.com
            </a>
          </p>
        </Section>
      </div>
    </div>
  );
}
