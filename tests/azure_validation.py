"""Offline tests for Azure account protection and private deployment preparation."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from deploy import azure_credit,cloud_preflight,prepare_cloud_env
from dotenv import dotenv_values

IDENTITY='12345678-1234-1234-1234-123456789abc'


def subscription(**overrides):
    return {'subscriptionId':IDENTITY,'displayName':'Azure for Students','state':'Enabled',
            'subscriptionPolicies':{'spendingLimit':'On','quotaId':'student-offer'},**overrides}


def configuration():
    # Test-only values, never provider credentials.
    return {'APP_DOMAIN':'chemistry-test.westus2.cloudapp.azure.com','TLS_EMAIL':'admin@uci.edu',
            'GROQ_API_KEY':'fixture-groq','PINECONE_API_KEY':'fixture-pinecone','ADMIN_EMAILS':'admin@uci.edu',
            'OIDC_PROVIDER':'google','OIDC_CLIENT_ID':'fixture.apps.googleusercontent.com',
            'OIDC_CLIENT_SECRET':'fixture-secret','OIDC_COOKIE_SECRET':'a'*48,
            'BROKER_REDIS_PASSWORD':'b'*48,'CACHE_REDIS_PASSWORD':'c'*48,'DOCUMIND_LOCAL_ADMIN':'false'}


class AzureCreditChecks(unittest.TestCase):
    def test_enabled_limit_on_accepted(self):
        result=azure_credit.validate_subscription(subscription())
        self.assertEqual(result['spending_limit'],'On')
        self.assertEqual(result['subscription_id'],IDENTITY)

    def test_removed_or_unknown_limits_rejected(self):
        for limit in ('Off','CurrentPeriodOff',None,'on'):
            with self.subTest(limit=limit),self.assertRaises(ValueError):
                azure_credit.validate_subscription(subscription(subscriptionPolicies={'spendingLimit':limit}))

    def test_disabled_account_rejected(self):
        with self.assertRaises(ValueError):
            azure_credit.validate_subscription(subscription(state='Disabled'))

    def test_invalid_subscription_response_rejected(self):
        for payload in (None,[],subscription(subscriptionId=None),subscription(subscriptionId='bad'),
                        subscription(subscriptionPolicies='bad'),subscription(subscriptionPolicies=None)):
            with self.subTest(payload=payload),self.assertRaises(ValueError):
                azure_credit.validate_subscription(payload)

    def test_cli_uses_only_read_operations(self):
        calls=[]
        def runner(command,**kwargs):
            calls.append(command)
            self.assertTrue(kwargs['capture_output'])
            return SimpleNamespace(stdout=IDENTITY if len(calls)==1 else json.dumps(subscription()))
        self.assertEqual(azure_credit.fetch_subscription(runner)['spending_limit'],'On')
        self.assertEqual(calls[0],['az','account','show','--query','id','--output','tsv'])
        self.assertEqual(calls[1][:5],['az','rest','--method','get','--url'])
        self.assertIn('/subscriptions/'+IDENTITY+'?',calls[1][5])

    def test_cli_error_does_not_echo_credentials(self):
        def runner(command,**kwargs):
            raise subprocess.CalledProcessError(1,command,stderr='fixture-secret-access-token')
        with self.assertRaises(ValueError) as error:
            azure_credit.fetch_subscription(runner)
        self.assertNotIn('fixture-secret',str(error.exception))

    def test_mismatched_account_response_rejected(self):
        results=iter([IDENTITY,json.dumps(subscription(subscriptionId='aaaaaaaa-1234-1234-1234-123456789abc'))])
        with self.assertRaisesRegex(ValueError,'did not match'):
            azure_credit.fetch_subscription(lambda *a,**k:SimpleNamespace(stdout=next(results)))

    def test_bad_cli_identifier_rejected_before_api(self):
        calls=[]
        def runner(*args,**kwargs):
            calls.append(args)
            return SimpleNamespace(stdout='invalid; write something')
        with self.assertRaisesRegex(ValueError,'invalid subscription identifier'):
            azure_credit.fetch_subscription(runner)
        self.assertEqual(len(calls),1)


class CloudSettingsChecks(unittest.TestCase):
    def test_valid_google_configuration(self):
        self.assertEqual(cloud_preflight.validate(configuration()),[])

    def test_missing_oauth_fails_without_secret_echo(self):
        values=configuration();values['OIDC_CLIENT_SECRET']=''
        errors=cloud_preflight.validate(values)
        self.assertTrue(any('OIDC_CLIENT_SECRET' in error for error in errors))
        self.assertNotIn(values['GROQ_API_KEY'],' '.join(errors))

    def test_public_hostname_required(self):
        for domain in ('127.0.0.1','https://host.example.com','host.example','host;echo.example.com','-host.example.com','localhost'):
            with self.subTest(domain=domain):
                self.assertTrue(cloud_preflight.validate({**configuration(),'APP_DOMAIN':domain}))

    def test_local_preview_rejected(self):
        for value in ('true','1','yes'):
            with self.subTest(value=value):
                self.assertTrue(cloud_preflight.validate({**configuration(),'DOCUMIND_LOCAL_ADMIN':value}))

    def test_redis_credentials_must_be_distinct_and_url_safe(self):
        for value in ('short','p'*40+'@','b'*48):
            with self.subTest(value=value):
                self.assertTrue(cloud_preflight.validate({**configuration(),'CACHE_REDIS_PASSWORD':value}))

    def test_admin_email_cannot_use_similar_domain(self):
        self.assertTrue(cloud_preflight.validate({**configuration(),'ADMIN_EMAILS':'admin@uci.edu.attacker.com'}))

    def test_microsoft_configuration_requires_tenant_uuid(self):
        values={**configuration(),'OIDC_PROVIDER':'microsoft','OIDC_CLIENT_ID':IDENTITY,'OIDC_TENANT_ID':IDENTITY}
        self.assertEqual(cloud_preflight.validate(values),[])
        values['OIDC_TENANT_ID']='common'
        self.assertTrue(cloud_preflight.validate(values))

    def test_private_preparation_preserves_existing_config(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(prepare_cloud_env,'ROOT',Path(folder)):
            destination=Path(folder)/'.env.cloud';destination.write_text('existing-private-settings')
            with self.assertRaises(SystemExit):prepare_cloud_env.main()
            self.assertEqual(destination.read_text(),'existing-private-settings')

    def test_preparation_generates_distinct_secrets_and_preserves_owner(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(prepare_cloud_env,'ROOT',Path(folder)):
            root=Path(folder)
            (root/'.env.cloud.example').write_text('APP_DOMAIN=your-public-hostname.example\nADMIN_EMAILS=admin@uci.edu\nTLS_EMAIL=admin@uci.edu\n')
            (root/'.env').write_text('ADMIN_EMAILS=admin@uci.edu\nGROQ_API_KEY=fixture-private-key\n')
            stdout=io.StringIO()
            with contextlib.redirect_stdout(stdout):prepare_cloud_env.main()
            values=dotenv_values(root/'.env.cloud')
            self.assertEqual(values['ADMIN_EMAILS'],'admin@uci.edu')
            self.assertEqual(values['TLS_EMAIL'],'admin@uci.edu')
            self.assertEqual(values['GROQ_API_KEY'],'fixture-private-key')
            secrets=[values[key] for key in ('OIDC_COOKIE_SECRET','BROKER_REDIS_PASSWORD','CACHE_REDIS_PASSWORD')]
            self.assertEqual(len(set(secrets)),3)
            self.assertTrue(all(len(value)>=48 for value in secrets))
            for value in secrets+['fixture-private-key']:self.assertNotIn(value,stdout.getvalue())


if __name__=='__main__':unittest.main(verbosity=2)
