# ADR-001: Extraction architecture

## Status

Accepted, May 2026.

## Context

The CEMAC–ECOWAS–AES Trade Observatory ingests data from five external
APIs and file sources: World Bank Data360, UN Comtrade, ACLED, IMF WEO,
and Fragile States Index. Each source requires HTTP requests from
somewhere with outbound internet access.

Databricks Free Edition restricts outbound network access from serverless
compute to a curated set of trusted destinations. The exact allow-list is
not fully published. If the project's external APIs are not on the list,
direct extraction from Databricks notebooks would fail and a fallback
architecture would be required.

This question had to be resolved before any extraction code was written,
because the answer changes where the code lives, how it is scheduled, and
how credentials are managed.

## Options considered

### Option A — Direct extraction from Databricks notebooks

Each external source has a PySpark notebook in
`databricks/notebooks/01_bronze/`. The notebook calls the API directly
with `requests.get(...)`, parses the response, and writes to a Delta
table. Orchestrated by Lakeflow Jobs. All credentials live in Databricks
secrets.

Single platform. Simple lineage. Easier to reason about.

### Option B — Local extraction with Prefect, upload to Databricks Volumes

Extraction lives in `extraction/extract/` as local Python modules. A
Prefect flow on the developer's Mac schedules extraction runs and writes
raw responses to a Databricks Volume using the Databricks Python SDK.
Bronze notebooks read from the Volume instead of from external APIs.

Two platforms. More moving parts. Robust against egress restrictions and
against future changes to managed-platform terms.

## Decision

**Option A — Direct extraction from Databricks notebooks.**

The decision is supported by a network access test run on May 15, 2026
using the notebook `01_network_test.ipynb`. The test called the World Bank
Open Data API (`api.worldbank.org`) from a Databricks Free Edition
serverless notebook and received an HTTP 200 response containing valid
Cameroon GDP data: 2020 GDP of 40,773,241,177 USD.

This confirms that direct outbound HTTPS requests from Databricks
serverless compute work for at least one of the project's required
sources. The remaining four sources will be verified individually in
week 2 as their extraction notebooks are built.

## Consequences

**Positive:**
- Pipeline lives in a single platform. Lineage is automatically tracked
  end-to-end in Unity Catalog.
- No second orchestration system to maintain.
- No second credential management surface.
- Faster to build by approximately three days versus the local-extraction
  fallback.

**Negative / risks:**
- The project is dependent on Databricks Free Edition's egress policies
  remaining stable. If the trusted destination list changes to exclude one
  of the five sources, that source's extraction would break.
- Mitigated by the operations strategy in the project specification
  (Section 21): daily uptime monitoring will surface broken extractions
  within hours.

**Reversibility:**
- If a future change to Free Edition's network policies breaks a source,
  that specific source can be migrated to Option B independently. The
  fallback architecture remains a viable per-source alternative.

## Validation

The test result that supports this decision is preserved as cell output
in `01_network_test.ipynb`. The notebook can be re-run at any time to
verify that the assumption still holds.
