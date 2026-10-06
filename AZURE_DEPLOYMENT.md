# Azure deployment

Deploy the Docker stack on an Ubuntu x64 VM. Caddy provides HTTPS; Streamlit, Celery,
durable ingestion Redis and disposable answer-cache Redis remain on the private Docker
network. Pinecone remains a separate hosted service. No owner account or server keys
are included in this public repository.

## Credit protection

For Azure for Students, verify the selected subscription and spending limit before
creating resources. In authenticated Cloud Shell, run this read-only check:

```sh
az account set --subscription "Azure for Students"
sid=$(az account show --query id --output tsv)
az rest --method get --url "https://management.azure.com/subscriptions/${sid}?api-version=2022-12-01" --query '{state:state,spendingLimit:subscriptionPolicies.spendingLimit}' --output json
```

Require Enabled and On. Do not upgrade to pay-as-you-go or remove the spending limit.
The included `deploy/azure_credit.py` also performs a read-only verification through
Azure CLI. A result is a point-in-time check, not a permanent billing guarantee.

Student credit is $100 valid for up to 12 months; a running VM consumes credit and can
exhaust it much sooner. Microsoft disables services/subscription when credit is
exhausted or expires. Budget notifications do not themselves stop resources.
[Student-credit behavior](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/azurestudents-subscription-disabled)
and [spending limits](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/spending-limit).
Provider API bills are separate. Retained disks/static IPs may cost money even after
VM deallocation. Review actual prices/quotas/region eligibility for your subscription.

## Server and networking

Choose an available Ubuntu 24.04 LTS x64 VM size with sufficient RAM for app, worker and
Redis. Use SSH key authentication and restrict TCP 22 to your management IP. Allow
TCP 80/443 for Caddy. Do not expose 8501 or Redis ports. Keep the private SSH key outside
the checkout and verify the host identity before connecting. Give the server a public
DNS hostname; a purchased domain is optional.

Clone or copy this source checkout to the VM. Follow `deploy/azure_vm_setup.sh` for the
Docker/runtime installation steps; review scripts before running with administrator
privileges. Never copy private uploads/state into source control.

## Production configuration

Follow [AUTH_SETUP.md](AUTH_SETUP.md) to create a Google web OAuth client with
`https://YOUR_HOSTNAME/oauth2callback`. Prepare a private `.env.cloud` from
`.env.cloud.example` with APP_DOMAIN, TLS_EMAIL, provider keys, OAuth credentials,
ADMIN_EMAILS and random cookie/broker/cache secrets. `deploy/prepare_cloud_env.py`
can generate missing random secrets from a separately configured private local `.env`.
Protect configuration and backup keys with owner-only permissions.

Run preflight and build/start from this repository's root:

```sh
python3 deploy/cloud_preflight.py --env-file .env.cloud
docker compose --env-file .env.cloud -f compose.cloud.yaml build app
docker compose --env-file .env.cloud -f compose.cloud.yaml up --no-build -d
docker compose --env-file .env.cloud -f compose.cloud.yaml ps
```

Install the helper's Python dependencies or use the prepared runtime if needed. Check
the helper's `--help` before use. Production refuses missing OAuth and local-preview
authentication. Cloud app/worker share local state and uploads; this stack is intended
for a single VM, not multiple independent replicas with separate SQLite databases.

## Verify and preserve state

Verify HTTPS and the HTTP redirect, container health, real administrator/student UCI
sign-in, logout and rejection of a non-UCI account. Ingest a reviewed chemistry test
document, inspect chunks/OCR, publish it, verify answers/citations/feedback and repeated
question caching. Confirm private documents cannot appear in student answers.

During updates retain `.env.cloud`, data, uploads and persistent volumes. Finish pending
jobs and take an encrypted state backup plus separate key. The backup excludes vectors,
original uploads and Redis queues; preserve those separately. Never use `down -v` during
routine updates. Roll back to a previously validated image if verification fails.

GitHub is source hosting; creating or updating this repository does not deploy or restart
the Azure application. No GitHub Actions deployment, cloud credentials or paid upgrades
are configured here.
