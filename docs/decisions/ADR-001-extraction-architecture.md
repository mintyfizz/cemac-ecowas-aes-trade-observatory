# ADR-001: Source-aware extraction architecture

## Status

Accepted, May 2026. Amended on May 16, 2026 after UN Comtrade network
validation and the IMF IMTS source substitution.

## Context

The CEMAC–ECOWAS–AES Trade Observatory ingests data from five external
APIs and file sources: World Bank Data360, IMF IMTS, ACLED, IMF WEO, and
Fragile States Index. Each source requires HTTP requests from
somewhere with outbound internet access.

Databricks Free Edition restricts outbound network access from serverless
compute to a curated set of trusted destinations. The exact allow-list is
not fully published. If a source hostname is not resolvable or reachable
from Databricks serverless compute, direct extraction from Databricks
notebooks fails even when the same source is reachable from a local
machine.

The original Week 1 network test confirmed that World Bank direct
extraction works from Databricks. A later UN Comtrade test showed that
`comtradeapi.un.org` fails DNS resolution from Databricks serverless
compute, while the same hostname resolves and responds from the local Mac.
The attempted local fallback also introduced API key and quota friction
that was unnecessary for the current requirement of annual total bilateral
trade by partner.

This means extraction architecture and source choice must be decided per
source, not once globally for the whole project.

## Options considered

### Option A — Direct extraction from Databricks notebooks only

Each external source has a PySpark notebook in Databricks. The notebook
calls the API directly with `requests.get(...)`, parses the response, and
writes to a Delta table. Orchestrated by Lakeflow Jobs. Credentials live
in Databricks secrets.

This is the simplest path when serverless network access works. It is the
preferred option for public sources that Databricks can reach directly.

### Option B — Local extraction only

All extraction lives in local Python modules. A local scheduler runs
extraction jobs from the developer's Mac and writes raw responses for
later Databricks ingestion.

This avoids Databricks egress restrictions, but it gives up the simplicity
and lineage benefits for sources that Databricks can already reach.

### Option C — Hybrid extraction by source

Sources that Databricks Free Edition can reach directly are extracted in
Databricks notebooks. Sources blocked by serverless DNS or egress policy
are extracted locally and then landed in Databricks as raw files for
bronze ingestion.

Credentials stay in the execution environment that uses them: Databricks
secrets for Databricks notebooks, local environment variables or secret
storage for local extractors. API keys are never embedded in URLs, printed
in logs, or committed to Git.

## Decision

**Option C — Hybrid extraction by source, with source substitution when a
candidate source is operationally unsuitable for the current requirement.**

World Bank remains a direct Databricks extraction. The supporting test ran
on May 15, 2026 using `01_network_test.ipynb`. It called the World Bank
Open Data API (`api.worldbank.org`) from a Databricks Free Edition
serverless notebook and received an HTTP 200 response containing valid
Cameroon GDP data: 2020 GDP of 40,773,241,177 USD.

UN Comtrade is not part of the active Week 2 partner-dependency path. A
Databricks serverless test on May 16, 2026 failed before authentication
with DNS resolution errors for `comtradeapi.un.org`. A local Mac network
check resolved the hostname and received an HTTP response from the
endpoint, confirming that the API hostname exists and the failure is
specific to Databricks serverless network access. ADR-003 later
reintroduced Comtrade through a local W00 national-total path for product
structure only.

For annual bilateral total trade, IMF IMTS replaces UN Comtrade. IMF IMTS
is extracted directly in `04_bronze_imts_extract.ipynb` and writes
`bronze.imts_raw`. The source-specific trade decision is
recorded in ADR-002.

## Consequences

**Positive:**
- Working direct extractions stay simple and keep Databricks lineage.
- Blocked sources do not block the whole project; they can either use a
  fallback path or be replaced by a source that satisfies the same
  requirement with lower operational risk.
- The project can continue in Week 2 without waiting for a platform-level
  network change.
- API keys can be kept out of URLs and error logs.

**Negative / risks:**
- Some analytical scope may change when a source is replaced. IMF IMTS
  covers total bilateral goods trade, but not HS product-level detail.
- If a future source truly requires a local fallback, that path will add a
  second extraction surface with local runtime and upload steps.

**Reversibility:**
- If Databricks later allows access to a blocked source, that source can
  move from local fallback back to direct notebook extraction.
- If a currently reachable source becomes blocked, it can move to the
  local fallback path without changing the bronze/silver/gold model.

## Validation

The World Bank test result is preserved as cell output in
`01_network_test.ipynb`.

The UN Comtrade failure mode was observed as repeated
`NameResolutionError` failures for `comtradeapi.un.org` from Databricks
serverless compute. The same hostname resolved from the local Mac and the
API returned an HTTP response. The active replacement is IMF IMTS for total
bilateral trade.
