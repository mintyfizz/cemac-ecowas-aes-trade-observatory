# ADR-001: Extraction Architecture

## Status

Accepted

## Context

The project needs a repeatable ingestion path for public and key-based data
sources while staying compatible with Databricks Free Edition. Week 1 focuses
on proving API access, Unity Catalog setup, and the first bronze Delta table
before adding more sources.

## Decision

Use Databricks notebooks as the first extraction surface and write raw source
responses into bronze Delta tables. Keep bronze append-only and replayable,
then add typed reconciliation in silver and dashboard-ready marts in gold.

Use GitHub as the source-control system for notebooks and documentation.
Credentials stay outside notebooks and are managed through Databricks or local
secret storage.

## Consequences

- The early pipeline remains simple enough to run in Databricks Free Edition.
- Bronze data can be replayed or reprocessed when source schemas change.
- Notebook changes are visible in GitHub for review and portfolio evidence.
- More orchestration can be added later without changing the medallion layout.
