"""Read-only Azure spending-limit verification; never changes billing or resources."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import uuid


def validate_subscription(payload):
    if not isinstance(payload,dict):
        raise ValueError('Azure returned an invalid subscription response.')
    try:
        identity = str(uuid.UUID(payload.get('subscriptionId','')))
    except (ValueError,TypeError,AttributeError):
        raise ValueError('Azure returned an invalid subscription identifier.') from None
    policies = payload.get('subscriptionPolicies')
    if not isinstance(policies,dict):
        raise ValueError('Azure spending-limit policy is missing or invalid.')
    limit = policies.get('spendingLimit')
    if payload.get('state')!='Enabled':
        raise ValueError('The selected Azure subscription is not enabled.')
    if limit!='On':
        raise ValueError('Azure spending limit is not verified as On. Keep Azure for Students with its credit protection; do not deploy using an unlimited paid subscription.')
    return {'subscription_id':identity,'subscription_name':payload.get('displayName',''),
        'state':payload['state'],'spending_limit':limit,
        'quota_id':policies.get('quotaId',''),
        'checked_utc':datetime.now(timezone.utc).isoformat(),
        'protection':'Azure-native credit spending limit. Budget alerts are notifications only.'}


def fetch_subscription(runner=subprocess.run):
    try:
        account = runner(['az','account','show','--query','id','--output','tsv'],check=True,capture_output=True,text=True,timeout=30)
        try:
            identity = str(uuid.UUID(account.stdout.strip()))
        except (ValueError,TypeError,AttributeError):
            raise ValueError('Azure CLI returned an invalid subscription identifier.') from None
        response = runner(['az','rest','--method','get','--url',
            f'https://management.azure.com/subscriptions/{identity}?api-version=2022-12-01',
            '--output','json'],check=True,capture_output=True,text=True,timeout=45)
        payload = json.loads(response.stdout)
        report = validate_subscription(payload)
        if report['subscription_id']!=identity:
            raise ValueError('Azure subscription response did not match the selected account.')
        return report
    except (OSError,subprocess.SubprocessError,json.JSONDecodeError):
        raise ValueError('Azure account verification failed. Run this in signed-in Azure Cloud Shell or install Azure CLI and sign in. No billing change was made.') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',help='Optional safe JSON report; it contains account identifiers, not tokens.')
    args = parser.parse_args()
    try:
        report = fetch_subscription()
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(report,indent=2),encoding='utf-8')
            path.chmod(0o600)
        print(json.dumps(report,indent=2))
    except ValueError as error:
        raise SystemExit(str(error)) from None


if __name__=='__main__': main()
