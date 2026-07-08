# Privacy Policy for KRX Watchlist Auto Custom GPT

Last updated: 2026-07-09

This Custom GPT provides informational stock-market tables, automation-status checks, and request-time auxiliary stock prices.

## Data sources and external services

The Custom GPT accesses public read-only JSON data from the public GitHub repository `sehwankim0114/krx-watchlist-auto`.

Requests are routed through the Cloudflare Worker service:

`https://krx-live-price-ksh.diaconos.workers.dev`

The Worker may retrieve public JSON data from GitHub through `raw.githubusercontent.com` or the GitHub Contents API. It may temporarily cache public JSON responses to improve reliability and reduce repeated requests.

For request-time auxiliary stock prices, the Worker may use:

* NAVER Stock Mobile for Korean stock prices
* Yahoo Finance Chart data for United States stock prices

These auxiliary prices are informational and do not replace confirmed official historical market datasets.

## Data collected

The service does not ask for or intentionally collect:

* Names
* Email addresses
* Passwords
* GitHub tokens
* API keys
* Payment information
* Brokerage account credentials
* Securities account numbers
* Portfolio quantities
* Average purchase prices
* Other sensitive personal information

API requests are designed to contain only public stock symbols, market labels, public JSON paths, and technical request information required to provide the requested response.

## Data transmitted and processing

When a user requests a stock table, status check, or auxiliary price, technical request information may be processed by OpenAI, Cloudflare, GitHub, NAVER, or Yahoo under their respective privacy policies and service terms.

The Custom GPT operator does not intentionally transmit the user's full conversation, identity, account credentials, brokerage information, or private portfolio information to the external stock-data endpoints.

Users should not enter passwords, API keys, brokerage credentials, account numbers, or other secrets into the GPT conversation.

## Authentication

The public read-only stock-data endpoints do not require user authentication.

No GitHub token, Cloudflare credential, brokerage login, or third-party API key should be provided by users.

## Caching and logs

Public JSON responses may be cached temporarily by the Cloudflare Worker to improve availability and reduce repeated upstream requests.

Cloudflare, GitHub, NAVER, Yahoo, and OpenAI may process standard technical information such as IP addresses, timestamps, request paths, browser or network metadata, and service logs according to their own policies.

## Purpose

The data is used only to:

* Produce informational stock-market tables
* Check automation and data freshness status
* Retrieve request-time auxiliary market prices
* Explain stock-table indicators and risk notices

The service does not guarantee investment performance and does not provide individualized financial, legal, tax, or brokerage advice.

## User responsibilities

Users should confirm prices through their brokerage platform before placing an order.

Users should not provide confidential, authentication, financial-account, or personally identifying information through the Custom GPT or its Actions.

## Contact

Questions, corrections, or privacy-related requests may be submitted through the GitHub repository's Issues page:

`https://github.com/sehwankim0114/krx-watchlist-auto/issues`
