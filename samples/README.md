# Samples

- **PDF** — put course invoices here locally (gitignored; do not commit).
- **JSON examples** — [`examples/`](examples/).

Upload PDFs via the deployed Streamlit UI (**Pipeline** tab), not direct `az storage` (storage data-plane is Deny for public IPs).

Classifier training still uses `./scripts/train_classifier.sh` (temporarily opens your IP on the storage firewall).
