"""Adapters that turn external data into a LedgerProof dataset.

Public payment datasets are single-source (a transactions table only) and don't match LedgerProof's
three-way settlement schema. `from_transactions` uses a real public transactions CSV as the source
of PG captures (real amounts, method mix, ordering) and derives the settlement report, bank
statement and internal ledger via the real Razorpay fee/settlement model — so reconciliation runs on
real-world payment distributions, with a derived ground-truth key for measurement.

Import from the submodule directly (`from ledgerproof.adapters.from_transactions import adapt_csv`)
so `python -m ledgerproof.adapters.from_transactions` doesn't double-import.
"""
