# Privacy Policy for KRX Watchlist Auto Custom GPT

Last updated: 2026-06-25

This Custom GPT uses read-only public JSON files hosted in the public GitHub repository
`sehwankim0114/krx-watchlist-auto`.

## Data collected

The GitHub JSON endpoints do not ask for or intentionally collect names, email addresses,
account credentials, payment information, or other personal information from users.

## Data transmitted

When a user requests a stock table, the GPT may request public JSON files from
`raw.githubusercontent.com`. GitHub and OpenAI may process technical request information
under their own privacy policies.

## Authentication

The read-only endpoints use no user authentication. Users must never enter GitHub tokens,
API keys, passwords, or other secrets into the GPT conversation.

## Purpose

The data is used only to provide informational stock-market tables and automation-status
checks. It is not a promise of investment performance and is not individualized financial advice.

## Contact

Questions or corrections may be submitted through the GitHub repository's Issues page.

<!-- LIVE_PRICE_PRIVACY_V51_BEGIN -->
## Request-time auxiliary stock price service

The Custom GPT may send public stock symbols and market labels to
`https://krx-live-price-ksh.diaconos.workers.dev` to retrieve request-time auxiliary stock prices.
The request does not include account credentials, portfolio quantities,
average purchase prices, names, email addresses, or other personal data.
Returned prices are auxiliary market information and do not replace
confirmed KRX historical datasets.
<!-- LIVE_PRICE_PRIVACY_V51_END -->
