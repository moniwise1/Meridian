import Link from "next/link";

export const metadata = { title: "Terms of Service — Meridian" };

const SECTIONS = [
  { id: "acceptance", label: "1. Acceptance" },
  { id: "the-service", label: "2. What Meridian is" },
  { id: "your-account", label: "3. Your account" },
  { id: "billing", label: "4. Subscriptions and billing" },
  { id: "acceptable-use", label: "5. Acceptable use" },
  { id: "your-data", label: "6. Your data" },
  { id: "ai-limitation", label: "7. AI-generated content" },
  { id: "availability", label: "8. Availability" },
  { id: "liability", label: "9. Limitation of liability" },
  { id: "indemnity", label: "10. Indemnification" },
  { id: "termination", label: "11. Termination" },
  { id: "force-majeure", label: "12. Force majeure" },
  { id: "changes", label: "13. Changes to these terms" },
  { id: "general", label: "14. General provisions" },
  { id: "governing-law", label: "15. Governing law" },
  { id: "contact", label: "16. Contact" },
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

export default function TermsOfServicePage() {
  return (
    <div className="min-h-screen bg-paper">
      <div className="max-w-5xl mx-auto px-6 md:px-8 py-16">
        <Link href="/" className="text-[15px] font-semibold tracking-tight text-ink mb-1 inline-block">
          Meridian
        </Link>
        <h1 className="text-[28px] font-medium text-ink tracking-tight mb-1.5 mt-3">Terms of Service</h1>
        <p className="text-[12.5px] text-ink-soft mb-12">
          Effective September 2026 · Meridian Techverse Limited
        </p>

        <div className="md:grid md:grid-cols-[200px_1fr] md:gap-12">
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
            <Section id="acceptance" title="1. Acceptance">
              <p>
                By creating an account or using Meridian, you agree to these terms on behalf of
                yourself and, if you register on behalf of a company, that company. Meridian is
                operated by <strong className="text-ink font-medium">Meridian Techverse Limited</strong>{" "}
                (RC 9849528), a company incorporated in the Federal Republic of Nigeria.
              </p>
            </Section>

            <Section id="the-service" title="2. What Meridian is">
              <p>
                Meridian is an AI-powered analytics agent: it connects to your databases and documents,
                answers business questions in plain English, and shows its work — the query it ran,
                data quality notes, and a confidence-rated explanation. It is read-only by design:
                Meridian can query and explain, and nothing else. It never writes, alters, or deletes
                data in any system you connect.
              </p>
            </Section>

            <Section id="your-account" title="3. Your account">
              <p>
                You are responsible for keeping your login credentials secure and for all activity
                under your account. If you invite teammates, you are responsible for managing their
                access and permissions within your organization&apos;s workspace. We strongly recommend
                enabling two-factor authentication.
              </p>
            </Section>

            <Section id="billing" title="4. Subscriptions and billing">
              <p>
                Paid plans are billed from the moment you subscribe via Paystack — there is no
                delayed-billing free trial. If you are not satisfied, you may cancel within 7 days of
                subscribing for a full refund; after that window, cancelling stops future billing but
                the current billing period is not refunded. Plan limits (seats, connected data sources,
                monthly questions, and monthly downloads) are described on our pricing page and enforced
                automatically. All payment processing is handled by Paystack under its own terms and
                security standards — see our{" "}
                <Link href="/privacy#payment-security" className="text-teal hover:text-teal-deep transition-colors">
                  Privacy Policy
                </Link>.
              </p>
            </Section>

            <Section id="acceptable-use" title="5. Acceptable use">
              <p>You agree not to:</p>
              <ul className="list-disc pl-5 flex flex-col gap-1.5">
                <li>Attempt to bypass, disable, or circumvent Meridian&apos;s read-only enforcement or access controls.</li>
                <li>Use Meridian to process data you are not legally authorized to access or analyze.</li>
                <li>Attempt to gain unauthorized access to another organization&apos;s workspace, data, or account.</li>
                <li>Use the service to build a competing product, or to reverse-engineer the underlying software.</li>
                <li>Use the service for any unlawful purpose.</li>
              </ul>
            </Section>

            <Section id="your-data" title="6. Your data">
              <p>
                You retain ownership of all data you connect to or upload into Meridian. We access it
                only to provide the service to you — running the query you asked for, generating the
                explanation you requested. See our{" "}
                <Link href="/privacy" className="text-teal hover:text-teal-deep transition-colors">
                  Privacy Policy
                </Link>{" "}
                for how it is handled.
              </p>
            </Section>

            <Section id="ai-limitation" title="7. AI-generated content — a real limitation, stated plainly">
              <p>
                Meridian&apos;s explanations are generated by an AI model interpreting deterministically
                computed numbers — the numbers themselves are never invented by the AI, but its
                interpretation, phrasing, and judgment calls can still be wrong. Every answer includes a
                stated confidence level and the underlying query for exactly this reason: verify
                anything you intend to act on for a decision that matters, the same way you would
                sanity-check any analyst&apos;s report. Meridian does not provide financial, legal, tax,
                or other professional advice.
              </p>
            </Section>

            <Section id="availability" title="8. Availability">
              <p>
                We monitor uptime and work to keep the service available, but we do not currently
                guarantee a specific uptime percentage or service-level agreement. Current status and
                incident history are published at{" "}
                <Link href="/status" className="text-teal hover:text-teal-deep transition-colors">
                  our status page
                </Link>.
              </p>
            </Section>

            <Section id="liability" title="9. Limitation of liability">
              <p>
                Meridian is provided &quot;as is.&quot; To the maximum extent permitted by law, Meridian
                Techverse Limited is not liable for indirect, incidental, or consequential damages
                arising from your use of the service, including decisions made based on its output.
              </p>
            </Section>

            <Section id="indemnity" title="10. Indemnification">
              <p>
                You agree to indemnify and hold Meridian Techverse Limited harmless from any claim
                arising from your use of the Service in violation of these terms or applicable law,
                including data you were not authorized to process.
              </p>
            </Section>

            <Section id="termination" title="11. Termination">
              <p>
                You may cancel your subscription and stop using Meridian at any time from your
                account&apos;s Billing page. We may suspend or terminate accounts that violate these
                terms, including the acceptable-use section above.
              </p>
            </Section>

            <Section id="force-majeure" title="12. Force majeure">
              <p>
                Neither party is liable for a failure or delay in performance caused by circumstances
                beyond its reasonable control, including internet or infrastructure outages, government
                action, or other events of force majeure.
              </p>
            </Section>

            <Section id="changes" title="13. Changes to these terms">
              <p>
                If these terms change materially, we will update the effective date at the top of this
                page and, where the change is significant, notify account administrators by email.
              </p>
            </Section>

            <Section id="general" title="14. General provisions">
              <p>
                If any provision of these terms is found unenforceable, the remaining provisions
                continue in full force. You may not assign these terms without our written consent; we
                may assign them in connection with a merger, acquisition, or sale of assets. These terms
                are the entire agreement between you and Meridian Techverse Limited regarding the
                Service, superseding any prior agreement on the same subject.
              </p>
            </Section>

            <Section id="governing-law" title="15. Governing law">
              <p>These terms are governed by the laws of the Federal Republic of Nigeria.</p>
            </Section>

            <Section id="contact" title="16. Contact">
              <p>
                Questions about these terms:{" "}
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
