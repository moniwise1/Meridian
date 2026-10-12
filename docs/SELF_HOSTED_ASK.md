# Private inference for Ask

Ask can run its SQL planner, follow-up resolver, document analysis and narrative
analysis through an operator-controlled Ollama service. Claude remains the default
for existing deployments. Selecting Ollama requires no Anthropic API key, and a
failed local request never falls back to a hosted provider.

## Railway setup

Run the model server as a separate service on Railway private networking. Do not
generate a public domain for it. Restrict who can modify the project, variables,
deployment image and volumes. Model storage and inference need capacity separate
from the existing backend; do not install a model in the API container or assume
an 8 GB CPU service can meet production latency and concurrency requirements.

Configure these backend variables only after the model service is ready:

```
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://ask-model.railway.internal:11434
OLLAMA_MODEL_FAST=<installed tool-capable model>
OLLAMA_MODEL_REASONING=<installed tool-capable model>
OLLAMA_MODEL_VISION=<optional installed vision model>
LLM_TIMEOUT_SECONDS=120
LLM_MAX_RESPONSE_BYTES=2000000
```

Use the actual service name. Fast and reasoning models may be the same model.
Evaluate both SQL accuracy and document tool use before enabling production.
Model licensing, hardware fit, concurrent memory use, context length and latency
must be checked against the actual selected model. No model is downloaded by
Meridian automatically. Image description is omitted when no vision model is
configured; the existing document text extraction still runs.

HTTP is accepted only for loopback and Railway private service hostnames. Other
origins require verified HTTPS. Do not use an unauthenticated public inference
server. Endpoint configuration is operator-owned, never supplied by an Ask user.
Outbound requests ignore ambient proxy variables and do not follow redirects.
Errors are sanitized, responses are bounded, and incomplete/truncated responses
are rejected. The adapter strips provider-specific prompt cache settings and
translates only the existing allowlisted analysis tools and their results.

## What independence means

Inference still uses tokens internally, but self-hosting removes Claude API token
billing and its credential dependency. Infrastructure has its own cost. This is
not training a new foundation model. The chosen model still needs its weights,
an inference runtime and enough memory/compute.

Models do not get direct database credentials, shell execution, arbitrary file
access, network requests or the ability to modify source data. Existing tenant,
source, table/column/row policy, SQL validation, query limits, rate limits and
deterministic calculations remain in force. Prompt injection cannot grant new
tools. The model's chart suggestions still pass the chart sanitizer.

## Public internet research boundary

This release does not add unrestricted web browsing. Public research needs an
explicit, separate mode with public-only search terms, bounded retrieval, SSRF
protection on every redirect/resolution, source citations and isolation from
customer data. Never send a private prompt, document, schema, record or conversation
to a search engine automatically. Web content must remain untrusted evidence,
not instructions. Do not allow a research tool to access internal model/network
origins, metadata services, credentials or authenticated customer sessions.

## Rollout and rollback

The provider contract is tested without live model calls using a bounded tool
roundtrip, malformed responses, unauthorized tools, transport failures, redirects
and invalid configurations. These tests verify the integration boundary, not a
specific model's reasoning quality. Before activation, run representative real
SQL, multi-file, chart, long-document and adversarial prompts against the installed
model, measure latency and concurrency, and check that responses cite only actual
authorized evidence. Keep LLM_PROVIDER=anthropic until those checks pass.

To roll back, set LLM_PROVIDER=anthropic with the existing Anthropic key, then
redeploy. Switching is an operator decision; there is no automatic provider fallback.
