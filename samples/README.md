# Samples

- **PDF** — put course invoices here locally (gitignored; do not commit).
- **JSON examples** — [`examples/`](examples/).

Upload PDFs to Azure:

```bash
./scripts/upload_pdf.sh ./samples/*.pdf
```

Or manually:

```bash
STORAGE=$(terraform -chdir=../terraform output -raw storage_account_name)

az storage blob upload \
  --account-name "$STORAGE" \
  --container-name invoices-in \
  --file ./your-invoice.pdf \
  --name your-invoice.pdf \
  --auth-mode login
```
