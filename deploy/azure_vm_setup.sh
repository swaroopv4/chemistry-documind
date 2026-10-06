#!/usr/bin/env bash
# Run on the Azure Ubuntu VM. No Azure billing changes or resource creation.
set -Eeuo pipefail
umask 077
action="${1:-prepare}"
if [[ "$EUID" -ne 0 ]]; then
    echo 'Run with sudo: sudo bash deploy/azure_vm_setup.sh prepare|start|status|stop'
    exit 1
fi
app_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$app_root"
[[ -f compose.cloud.yaml && -f deploy/Caddyfile ]] || { echo 'Application files are missing.'; exit 1; }
compose() { docker compose --env-file .env.cloud -f compose.cloud.yaml "$@"; }
case "$action" in
prepare)
    source /etc/os-release
    [[ "$ID" == ubuntu && ( "$VERSION_ID" == 22.04 || "$VERSION_ID" == 24.04 ) ]] || { echo 'Use Ubuntu 22.04 or 24.04.'; exit 1; }
    if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
        apt-get update
        apt-get install -y ca-certificates curl python3-venv
        install -m 0755 -d /etc/apt/keyrings
        curl --fail --silent --show-error --location https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
        chmod a+r /etc/apt/keyrings/docker.asc
        cat >/etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
        apt-get update
        apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    else
        apt-get update
        apt-get install -y python3-venv
    fi
    systemctl enable --now docker
    python3 -m venv .env-tools
    .env-tools/bin/python -m pip install --disable-pip-version-check python-dotenv
    install -m 0700 -d data .uploads
    if [[ ! -f .env.cloud ]]; then
        .env-tools/bin/python deploy/prepare_cloud_env.py
    fi
    chmod 0600 .env.cloud
    echo 'VM prepared. Set hostname, OAuth credentials and rotated AI keys in private .env.cloud.'
    echo 'Before start, verify Azure for Students spending limit is On using deploy/azure_credit.py in Azure Cloud Shell.'
    echo 'Start only after setup is complete: sudo bash deploy/azure_vm_setup.sh start'
    ;;
start)
    [[ -x .env-tools/bin/python && -f .env.cloud ]] || { echo 'Run prepare first.'; exit 1; }
    .env-tools/bin/python deploy/cloud_preflight.py
    # Quiet validation prevents Compose from displaying interpolated secrets.
    compose config --quiet
    compose build app
    compose up -d --no-build --wait --wait-timeout 180
    compose ps
    echo 'Containers started. Verify the HTTPS URL and real UCI login before publishing documents.'
    ;;
status)
    compose ps
    ;;
stop)
    compose stop
    echo 'Application containers stopped; data volumes were preserved.'
    echo 'This does not deallocate the Azure VM. Use Azure Portal Stop (deallocate) to stop VM compute charges.'
    ;;
*)
    echo 'Use prepare, start, status or stop.'
    exit 1
    ;;
esac
