# Terms of Service

> **⚠️ NOT LEGAL ADVICE — DO NOT PUBLISH AS-IS.** This is a starting draft
> written to match what Meridian's code actually does (read-only database
> access, AI-generated analysis via Anthropic's API, Paystack billing), not
> a reviewed legal document. Have a lawyer licensed in your operating
> jurisdiction(s) review and adapt it — especially §5 (data processing) and
> §9 (liability), which carry real regulatory and financial exposure if
> wrong. Every `[BRACKETED]` placeholder needs a real value. If you'll have
> customers in the EU/UK, you separately need a GDPR-compliant Data
> Processing Agreement (DPA) — not included here; see the note at the end.

**Last updated: [DATE]**

These Terms of Service ("**Terms**") govern access to and use of Meridian
(the "**Service**"), provided by [COMPANY NAME], a [ENTITY TYPE]
incorporated in [JURISDICTION] ("**we**", "**us**", "**Meridian**"). By
creating an account or using the Service, you ("**Customer**", "**you**")
agree to these Terms on behalf of yourself and the organization you
represent.

## 1. The Service

Meridian is a business analytics tool that connects to a database you
authorize, answers natural-language questions about that data, and
generates reports, presentations, and exports from the results. Key
things worth being explicit about, because they shape what we're actually
promising:

- **Read-only by design.** Meridian's database connectors are built to be
  structurally incapable of writing to your database — see the technical
  README for exactly what's verified and how. We do not guarantee this
  makes writing *impossible* under every conceivable database
  configuration, and you're responsible for using a properly-scoped,
  least-privilege credential as documented.
- **AI-generated content.** Explanations, insights, and forecasts are
  produced in part by a third-party AI model (currently Anthropic's
  Claude). AI output can be wrong, incomplete, or misleading, including
  when it sounds confident. Forecasts are explicitly simple trend
  projections, not statistical predictions — see in-product disclaimers.
  You are responsible for verifying anything before relying on it for a
  business decision.
- **Document uploads.** Content you upload (PDF/DOCX/XLSX) is extracted
  and may be sent to our AI sub-processor as part of answering a
  question. Don't upload anything you're not authorized to share with us
  and our sub-processors.

## 2. Accounts & Eligibility

You must provide accurate registration information and are responsible
for activity under your account. The person who registers an organization
becomes its administrator and can invite others, connect data sources,
and manage billing. You must be authorized to bind the organization you
register on behalf of.

## 3. Subscription, Billing & Refunds

- Subscribing to Meridian charges you immediately via
  [Paystack](https://paystack.com) — there is no delayed-billing free
  trial.
- Full refund if you cancel within 7 days of your first charge; after
  that, cancelling stops future billing but does not refund the current
  period. See the [Refund Policy](./REFUND_POLICY.md) for the complete
  terms, which are incorporated into these Terms by reference.
- We may change subscription pricing on notice; changes apply to future
  billing periods, not ones already paid for.
- You're responsible for keeping payment information current. A failed
  renewal charge may result in suspended access until resolved.

## 4. Acceptable Use

You agree not to:

- Use the Service to access, or attempt to access, data you're not
  authorized to access, including by circumventing the row-level or
  column-level access controls an admin on your account has configured;
- Attempt to use the Service to write, alter, or delete data in a
  connected database, or to probe for ways around its read-only
  enforcement;
- Upload content that infringes someone else's rights or that you're not
  authorized to share with us and our sub-processors;
- Attempt to submit prompts or documents designed to manipulate the AI
  model into bypassing these Terms or the Service's access controls
  (prompt injection), or otherwise attempt to reverse-engineer, extract
  the underlying model behind, or abuse the AI features;
- Resell, sublicense, or provide the Service to third parties outside
  your own organization without our written agreement;
- Use the Service in a way that violates applicable law.

We may suspend or terminate accounts that violate this section.

## 5. Your Data

- **You own your data.** Data in the databases and documents you connect
  or upload remains yours. We don't claim ownership of it and don't use
  it to train AI models.
- **Sub-processors.** To provide the Service we share limited data with:
  - **Anthropic** (AI model provider) — receives the parts of your
    question and already-computed, policy-filtered results needed to
    generate an explanation; per Meridian's design, raw unaggregated
    tables and database credentials are never sent to it.
  - **Paystack** (payment processor) — receives billing/payment
    information necessary to process your subscription; we do not store
    your card details ourselves.
  - **[HOSTING PROVIDER]** — hosts the application and the databases
    described below.
  A full, current sub-processor list is available at [URL] / on request.
- **Where data lives.** Your organization's metadata (accounts, connection
  configuration, query history, audit log, uploaded documents) is stored
  in our own database, encrypted at rest for connection credentials
  specifically. Your source database itself is never copied wholesale —
  Meridian queries it live, on demand.
- **Retention & deletion.** [Describe how long data is kept after
  cancellation and how a customer can request deletion — this needs a
  real answer before publishing, not a placeholder left blank.]
- **Security.** We maintain [description of your actual security
  practices — encryption, access controls, incident response]. See
  §9 for the limits of what we can promise here.

**If you'll have customers in the EU/UK or otherwise subject to GDPR/UK
GDPR, you need a separate Data Processing Agreement (DPA) with defined
processing purposes, sub-processor flow-down terms, and international
transfer mechanisms — this document is not a DPA and does not satisfy
that requirement.**

## 6. Intellectual Property

We own the Service itself (software, design, trademarks). You retain all
rights to your data. Reports, presentations, and exports generated from
your data belong to you.

## 7. Disclaimers

THE SERVICE IS PROVIDED "AS IS." TO THE MAXIMUM EXTENT PERMITTED BY LAW,
WE DISCLAIM ALL WARRANTIES, EXPRESS OR IMPLIED, INCLUDING MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE, AND NON-INFRINGEMENT. WE DO NOT WARRANT
THAT AI-GENERATED INSIGHTS, EXPLANATIONS, OR FORECASTS ARE ACCURATE,
COMPLETE, OR SUITABLE FOR ANY PARTICULAR BUSINESS DECISION.

## 8. Limitation of Liability

[This section determines your actual financial exposure if something goes
wrong — a generic cap ("liability limited to fees paid in the prior 12
months," carve-outs for gross negligence/fraud, exclusion of indirect/
consequential damages) is standard, but the right numbers and carve-outs
depend on your risk tolerance and what your insurer/lawyer will actually
back. Do not ship this section without them reviewing it.]

## 9. Termination

Either party may terminate for the other's material breach of these
Terms not cured within [X] days of notice. You may cancel your
subscription at any time per §3. On termination, your access ends; see
§5 for data retention/deletion after that point.

## 10. Changes to These Terms

We may update these Terms; material changes will be notified via
[email / in-app notice] with [X] days' notice before taking effect.
Continued use after that constitutes acceptance.

## 11. Governing Law

These Terms are governed by the laws of [JURISDICTION], without regard to
conflict-of-law principles. [Add dispute resolution mechanism — courts of
a specific jurisdiction, or arbitration — once decided.]

## 12. Contact

[COMPANY NAME]
[ADDRESS]
[SUPPORT EMAIL]
