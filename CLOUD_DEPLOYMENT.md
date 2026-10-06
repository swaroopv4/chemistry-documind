# Cloud deployment preparation

The source includes a complete single-host Docker Compose deployment: HTTPS proxy, Streamlit admin/student app, Celery worker, persistent ingestion Redis, and a separate bounded answer-cache Redis. Pinecone remains the shared remote vector database. Once this stack runs on a cloud VM, the laptop is not required for questions or uploads. This request's implementation and deployment files are prepared locally; no cloud account/VM/domain or live OAuth client has been supplied, so no public deployment has been claimed.

## Free hosting option and current limits

The owner has selected **Azure for Students**. Follow [AZURE_DEPLOYMENT.md](AZURE_DEPLOYMENT.md) for the VM setup helper, read-only spending-limit verification, Google login setup and state migration. Azure disables the student subscription/services when the credit is exhausted or expires; keep the spending limit On and do not upgrade to pay-as-you-go. The owner's signed-in Cloud Shell output reported Enabled and spendingLimit On on October 6, 2026. [Microsoft's student credit policy](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/azurestudents-subscription-disabled).

The following Oracle option is an alternative, not the selected deployment.

Oracle Cloud Always Free Ampere A1 is a candidate for running the complete stack on one VM. As checked October 5, 2026, Oracle documents **2 OCPUs / 12 GB total**, plus Always Free storage within its limits—not the older widely quoted 4 OCPU / 24 GB allocation. Capacity can be unavailable, and idle instances can be reclaimed. Use only resources marked Always Free eligible in the home region; verify the console's estimate before creating them. A free tier is not a guarantee of permanent availability or zero provider inference charges. [Oracle's current official limits](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

A 1 GB micro VM is not suitable for this Python/RAGAS stack. Aim for the eligible A1 VM with 12 GB RAM and a 50–100 GB boot disk within the free storage allotment. The pinned image is tested locally on Linux amd64; an ARM image build/test on the actual A1 VM is still required. The Python base, Redis and Caddy images support ARM, but dependency installation/runtime must be validated there. A UCI-provided Linux VM is another option if available to you.

## Before deployment

You need a cloud account/VM you control, SSH access, a public hostname resolving to the VM, and the Google OAuth web client configured in AUTH_SETUP.md. Account registration, billing eligibility and university approval are owner actions. No additional AI-provider key is required. OAuth client ID/secret are required for sign-in; internal cookie/Redis passwords are generated locally. If you use automated DNS or a cloud API to provision resources, that service may require its own credentials; they are not needed by the application itself.

On the VM, install Docker Engine and the Compose plugin using the [official Docker instructions](https://docs.docker.com/engine/install/ubuntu/). Allow inbound HTTPS/HTTP (443/80) in the cloud security group and host firewall; restrict SSH to your own management IP. Do not expose Streamlit, either Redis instance or the Celery broker ports directly.

## Configure and run

Copy this application source to the VM without copying a configured `.env` into a public repository. Keep one worker/concurrency=1. Use a private SSH transfer or enter keys on the VM.

```bash
python3 -m venv .env-tools
.env-tools/bin/python -m pip install python-dotenv
.env-tools/bin/python deploy/prepare_cloud_env.py
# Edit .env.cloud: hostname, TLS email, actual Google OAuth client ID/secret,
# admin UCI email(s), existing Groq/Pinecone keys and index settings.
mkdir -p data .uploads
chmod 700 data .uploads
chmod 600 .env.cloud
docker compose --env-file .env.cloud -f compose.cloud.yaml config --quiet
docker compose --env-file .env.cloud -f compose.cloud.yaml build app
docker compose --env-file .env.cloud -f compose.cloud.yaml up -d --no-build
```

Alternatively copy .env.cloud.example to .env.cloud and generate distinct random URL-safe cookie/broker/cache secrets. Replace every placeholder before starting; the example is not a working credential file. The launcher refuses missing production OAuth or an HTTP callback. Caddy obtains/manages HTTPS certificates once DNS and ports are correct and proxies Streamlit's WebSockets. [Caddy reverse proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy).

The cloud Compose file publishes only ports 80 and 443, uses private password-protected Redis services, keeps the answer-cache memory policy separate from the durable queue, and shares data/uploads with app/worker. App/worker containers have a read-only root filesystem, bounded memory/process limits, dropped capabilities and no-new-privileges. Generated Streamlit auth configuration is held in an ephemeral mounted directory, while SQLite policy/settings/logs persist in data. Neither Redis nor cache health screens reveal passwords or provider keys.

## Existing vectors and validation

Hybrid keyword rows persist in the shared data directory. If that directory is not migrated, use **Documents → Rebuild keyword index from existing vectors** after deploying; this reads existing Pinecone text without re-embedding. New jobs automatically write both dense and keyword indexes. No separate keyword-search container or API key is needed.

Use the same PINECONE_INDEX_NAME and embedding namespace to reach existing vectors. Document policy is local SQLite state: either privately migrate the data directory while services are stopped, or use **Documents → Discover existing vector documents** on the cloud admin account, review each document and publish it with a non-personal source label. Unreviewed vectors remain unavailable to students. A source ZIP deliberately excludes user data, policies, logs, uploads and secrets.

After startup, check Compose service health and the worker, then complete real sign-in tests for the approved admin, a second managed UCI account and a non-UCI account. Publish a reviewed test document, check its student answer/citations, repeat the question to verify Redis hits, mark it private and confirm the answer cannot be reused. Verify job progress and server-side batch ingestion. Review the provider consoles for inference and index spending. Back up the private data directory and queue volume; the answer cache can be discarded/rebuilt. Avoid `down -v` if queue data must be preserved. Public deployment is complete only after these checks and a working HTTPS URL.
