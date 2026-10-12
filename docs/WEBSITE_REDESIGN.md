# Meridian website and business workspace release

The public website now introduces Meridian Analytics as a business intelligence
and financial analytics product, with a clear signup path, current API-sourced
pricing, a bounded sample-data demonstration, workflow explanation, source/access
controls, FAQ and the existing working enquiry form. Public copy avoids agent/AI
labels, fake customer proof, unqualified accounting claims and free-trial promises.
Business and individual pricing CTAs select the matching signup account type.
The public homepage is server rendered before the client resolves a session;
protected workspace routes retain their existing authentication gate.

Design research used the official product pages of Metabase, Tableau and Power BI:
- https://www.metabase.com/product/business-intelligence
- https://www.tableau.com/
- https://www.microsoft.com/en/power-platform/products/power-bi

The resulting design decision is an inference from their product presentation:
lead with a clear category and practical outcome, show a concrete product view,
explain the workflow and access model, then provide pricing and signup. Meridian
uses its own copy, existing green brand identity and labelled synthetic examples;
competitor claims, customer lists and performance statistics are not reproduced.

Business users now also have Financial Analytics and Sales & Performance routes.
Both reuse the Executive Overview computation, authorization, currency handling,
source records, dates and Ask panel. Optional grouping maps an actual expense
category/product/branch/region column. Group filters affect metrics, records and
Ask together; top group answers inspect all groups, not just the 100-row display.
Missing amount cells keep affected group totals unavailable. Original row IDs are
preserved. Configurations are retained in sessionStorage per user and tenant for
cross-workspace continuity; they are not persisted company-wide definitions.

Financial scope remains explicit: mapped revenue, expenses, period comparisons
and grouped categories. Gross profit, net profit, cash flow, budgets and invoice
aging are not invented without their required accounting inputs. No schema change
or new environment variable is introduced.

Validation: frontend build (including TypeScript), lint and the expanded backend
Executive/Ask regression check. Browser layout validation remains a release check.
Railway production uses ideal-rejoicing: frontend remarkable-heart and backend
Meridian. A second unrelated project has a failed service and is not the service
serving www.getmeridiananalytics.com or the verified backend API.

www.getmeridiananalytics.com responds successfully; the bare apex address returns
a certificate hostname mismatch from this environment. Code does not repair TLS
certificate/DNS configuration. The apex hostname must be checked in Railway's
frontend custom domains and certificate status using an authenticated account.
No DNS changes were made by this release.

The user has authorized rolling deployment of completed changes for testing.
Rollback this increment by reverting its merge commit and rebuilding both services.
The previously released SQL authorization controls remain in place.
