# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A publicly accessible, climate-informed decision support system for small, independent Napa Valley vintners. The system translates publicly available climate and agricultural data into plain-language wine advisories for growers who lack access to large-scale analytics platforms.

## Repository Structure

- `frontend/` — React + TypeScript + TailwindCSS client application
- `backend/` — Server-side API and data processing layer
- `.claude/rules/` — Project conventions (automatically loaded; do not repeat them here)

> **Note:** The project is in early setup. Both `frontend/` and `backend/` are currently empty scaffolds awaiting initialization.

## Development Commands

_Commands will be added here once the frontend and backend are initialized (e.g., `npm run dev`, `npm test`, `npm run lint`)._

## Architecture

Once implemented, the system will follow a frontend/backend split:

- **Frontend**: React SPA served separately, communicates with the backend via REST or GraphQL API
- **Backend**: Ingests publicly available climate and agricultural data, processes it, and exposes advisory endpoints

## Conventions Summary

Key rules are enforced via files in `.claude/rules/`. Quick reference:

- **Branches**: `<type>/issue-<number>-<short-description>` — never push directly to `main`
- **Commits**: Imperative mood, reference issue number (e.g., `Add advisory card component (#7)`), no co-sign lines
- **PRs**: Include `Closes #<number>`, keep under ~400 changed lines, merge commits only
- **CSS**: TailwindCSS first; custom classes use `tm-` prefix; no `@apply`; no inline `style={{}}` unless values are dynamic