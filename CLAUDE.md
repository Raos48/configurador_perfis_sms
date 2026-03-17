# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RPA service that automates blocking/unblocking server profiles in the SAGGESTAO system. It polls a Django backend for pending tasks, uses Playwright to automate the browser, and reports results back via JWT-authenticated API.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Verify environment
python verify_setup.py

# Run the service (continuous polling loop)
python servico_rpa.py

# Test a single operation without the service (standalone CLI mode)
python bloquear_perfis.py <SIAPE> <CODIGO_UNIDADE> <BLOQUEIO|DESBLOQUEIO>

# Example
python bloquear_perfis.py 1234567 01.001.PRES BLOQUEIO
```

## Architecture

### Data Flow
1. `servico_rpa.py` polls Django API every 5–10s for pending block/unblock tasks
2. For each task, calls `executar_bloqueio()` in `bloquear_perfis.py` with the shared `SaggestaoSessionManager`
3. Result is reported back to Django via `SigaApiClient.confirmar_bloqueio/desbloqueio()`

### Persistent Browser Session (`session_manager.py`)
The most critical architectural component. A single browser instance lives for the entire service lifetime:
- **Lazy start**: Browser only opens on first `ensure_ready()` call
- **Health check (4 layers)**: browser connected → page open → correct URL → SIAPE field visible
- **Recovery**: Closes context, fetches new JSESSIONID, re-navigates
- **Keep-alive**: Page reload every 4 minutes (`SESSION_KEEPALIVE_INTERVAL`)
- **Playwright sync API**: Uses `sync_playwright().start()` (NOT a context manager — required for long-lived sessions)
- **No threads**: Playwright sync API is not thread-safe

### Authentication (`auth.py`)
SAGGESTAO uses session-based auth via JSESSIONID obtained from a local Java server at `localhost:48000`:
```
GET http://localhost:48000 with headers {'Comando': 'NovaSessao', 'Sistema': 'SAGGESTAO'}
```
The JSESSIONID cookie is injected into the Playwright context before navigation.

### Django API Client (`siga_client.py`)
JWT authentication with proactive token refresh at 12 minutes (tokens expire at 15 minutes). Auto-retries on 401 by refreshing, then falls back to full re-auth.

### Browser Automation (`bloquear_perfis.py`)
Automates the SAGGESTAO PrimeFaces UI:
1. Search by SIAPE → click "Alterar" button (with full-search retry up to `MAX_RETRIES` times)
2. Paginate unit table (30 items/page) → find target unit code
3. Toggle "GET" checkbox (uncheck = block, check = unblock)
4. Confirm change (handles divergence warning re-confirmation)

Uses multiple CSS selector strategies with JavaScript click fallbacks for PrimeFaces buttons.

**Alterar button resilience**: `ico-pencil` class is on the `<span>` inside `<a>`, NOT on `<a>` itself.
Correct selectors: `[id$="idAlterarCadastroProfissional"]`, `a:has(span.ico-pencil)`. Do NOT use `a.ico-pencil`.
When all click attempts fail, `_fluxo_principal` resets the search (navigates back, re-enters SIAPE) and retries.

### Metrics (`metrics.py`)
Collects operation stats (successes, failures, durations). Logged to console every hour during service runtime.

## File Structure

| File | Role |
|------|------|
| `servico_rpa.py` | Main polling loop and orchestration |
| `session_manager.py` | Persistent browser session lifecycle |
| `bloquear_perfis.py` | Playwright browser automation |
| `siga_client.py` | HTTP client for Django API (JWT auth) |
| `auth.py` | JSESSIONID acquisition from local Java server |
| `metrics.py` | Operation metrics collection and reporting |
| `colored_logger.py` | Colored console logging with heartbeat |
| `config.py` | All configuration (env vars with defaults) |
| `verify_setup.py` | Pre-flight environment check |

## Key Selectors (SAGGESTAO)

| Element | Selector |
|---------|----------|
| SIAPE input | `input[name="form\\:idMskSiape"]` |
| Edit button | `[id$="idAlterarCadastroProfissional"]` or `a:has(span.ico-pencil)` |
| Unit table rows | `#form\\:tabelaUnidades_data tr` |
| GET checkbox | `[id$="selecionarDeselecionarGet"]` |
| Confirm button | `id=form:botaoConfirmar` |
| Pagination next | `[id="form\\:tabelaUnidades_paginator_bottom"] a.ui-paginator-next:not(.ui-state-disabled)` |

## API Environments

The service supports two API environments switched via `API_ENV` in `.env`:

```
API_ENV=local   # uses SIGA_API_URL (http://localhost:8000)
API_ENV=cloud   # uses SIGA_API_URL_CLOUD (https://sgben-sigabackend.bpbeee.easypanel.host)
```

To switch: edit `API_ENV` in `.env` and restart the service. The active environment and URL are logged at startup.

## API Endpoints (Django Backend)

```
POST /api/token/                          # Get JWT tokens
POST /api/token/refresh/                  # Refresh access token
GET  /api/bloqueios/pendentes-bloqueio/   # List pending blocks
GET  /api/bloqueios/pendentes-desbloqueio/
POST /api/bloqueios/confirmar-bloqueio/   # Report result
POST /api/bloqueios/confirmar-desbloqueio/
```

Backend source: `F:\Sistema SIGA\backend\`

## Environment

Copy `.env.example` to `.env`. Required variables:
- `SIGA_EMAIL` / `SIGA_PASSWORD` — Django staff account (`is_staff=True`)

Optional:
- `API_ENV` — `local` or `cloud` (default: `local`)
- `SIGA_API_URL` — local API URL (default: `http://localhost:8000`)
- `SIGA_API_URL_CLOUD` — cloud API URL (default: `https://sgben-sigabackend.bpbeee.easypanel.host`)
- `BROWSER_HEADLESS` — default `true`
- `SAGGESTAO_CONSULTATION_URL`, `POLLING_INTERVAL`, `SESSION_KEEPALIVE_INTERVAL`, `MAX_RETRIES`, `LOG_LEVEL`, `LOG_FILE`

## Prerequisites

- Python 3.13+
- Java auth server running on `localhost:48000`
- Django backend running (see `SIGA_API_URL`)
- Network access to SAGGESTAO (`psagapr01`)

## Dual-Mode Operation

`executar_bloqueio()` accepts `session_manager=None`. Without a session manager it creates a fresh browser per call (CLI/testing mode). With a session manager it reuses the persistent session (service mode).
