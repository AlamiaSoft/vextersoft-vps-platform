# ADR-001: Architecture Baseline & Project Standards

## Status
Accepted

## Date
2026-10-07

## Context
When building extensible software systems, maintaining a single source of truth for architectural decisions prevents tribal knowledge drift and helps AI agents make consistent decisions.

## Decision
1. All technical tasks must reference approved ADRs when relevant.
2. Changes to core system contracts require an updated ADR.
3. Automated test gates must be executed prior to closing task specifications.

## Consequences
- Clean, deterministic system evolution.
- Fast onboarding for human engineers and autonomous AI agents alike.
