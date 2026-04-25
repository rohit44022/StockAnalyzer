# Portfolio Excel/PDF Export – TODO

## Tasks
- [x] Add backend endpoint `/api/portfolio/export/xlsx?tab=open|closed` in `web/app.py`
- [x] Add backend endpoint `/api/portfolio/export/pdf?tab=open|closed` in `web/app.py`
- [x] Add Excel and PDF buttons in `web/templates/portfolio.html` nav-pills row
- [x] Wire buttons to call appropriate endpoint based on currently active tab (Open / Closed)
- [x] Fix field mapping so exported data matches UI (position.id lookup, holding.pnl_amount, targets.current_price, vince_risk.sizing_status, volatility_label)
- [x] Test endpoints via Flask test client — both XLSX and PDF for Open and Closed tabs verified

## Status: COMPLETE

Outputs verified:
- Open tab XLSX: 11 rows with Ticker, Strategy, Buy Price, Buy Date, Qty, Invested, Current, P&L, P&L%, Days, Action (HOLD/ADD/SELL), Risk (LOW/MODERATE/HIGH), Sizing (UNDERSIZED/OPTIMAL/OVERSIZED), Notes + TOTAL row.
- Closed tab XLSX: All closed positions with Ticker, Strategy, Buy Price/Date, Sell Price/Date, Qty, realized P&L, P&L%, Days Held, Reason, Notes + TOTAL row.
- PDF exports: A4 landscape tables with matching columns and styled headers.
