import asyncio
import base64
import email
import os
import ssl
import time
from email.message import Message

import aiosmtpd
import requests
from aiosmtpd.controller import UnthreadedController
from aiosmtpd.smtp import SMTP, AuthResult, LoginPassword, Envelope
from msal import ConfidentialClientApplication


def parse_email(msg: Message):
    email_data = {
        "subject": msg['subject'],
        "to_recipients": [recipient.strip() for recipient in msg['to'].split(',')],
        "text_body": None,
        "html_body": None,
        "attachments": []
    }

    for part in msg.walk():
        content_type = part.get_content_type()
        content_disposition = part.get("Content-Disposition")

        if content_disposition and "attachment" in content_disposition:
            filename = part.get_filename()
            attachment_content = part.get_payload(decode=True)
            email_data['attachments'].append({
                "name": filename,
                "content_type": content_type,
                "content": base64.b64encode(attachment_content).decode()
            })
        elif content_type == 'text/plain' and not email_data['text_body']:
            email_data['text_body'] = part.get_payload(decode=True).decode()
        elif content_type == 'text/html' and not email_data['html_body']:
            email_data['html_body'] = part.get_payload(decode=True).decode()

    return email_data


def construct_email_payload(email_data):
    recipients = [{"emailAddress": {"address": addr}} for addr in email_data['to_recipients']]
    # Choose the appropriate body content and type
    body = {
        "contentType": "HTML" if email_data['html_body'] else "Text",
        "content": email_data['html_body'] if email_data['html_body'] else email_data['text_body']
    }

    payload = {
        "message": {
            "subject": email_data['subject'],
            "body": body,
            "toRecipients": recipients,
        }
    }

    # Attachments processing
    if email_data['attachments']:
        payload['message']['attachments'] = [{
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": attachment['name'],
            "contentType": attachment['content_type'],
            "contentBytes": attachment['content']
        } for attachment in email_data['attachments']]

    return payload


class O365RelayHandler:
    token_cache = {
        'token': None,
        'expiry': None
    }
    def get_access_token(self):
        client_secret = os.environ.get('AZURE_CLIENT_SECRET')
        client_id = os.environ.get('AZURE_CLIENT_ID')
        tenant_id = os.environ.get('AZURE_TENANT_ID')

        current_time = time.time()
        if self.token_cache['token'] and self.token_cache['expiry'] > current_time + 300:
            return self.token_cache['token']

        # Token either not in cache or expired, request new token
        authority = f"https://login.microsoftonline.com/{tenant_id}"
        app = ConfidentialClientApplication(
            client_id=client_id,
            client_credential=client_secret,
            authority=authority
        )

        scopes = ["https://graph.microsoft.com/.default"]  # Scope for all permissions
        token_response = app.acquire_token_for_client(scopes=scopes)

        print(token_response)

        if "access_token" in token_response:
            # Update cache with new token and expiry
            self.token_cache['token'] = token_response['access_token']
            self.token_cache['expiry'] = current_time + token_response['expires_in']
            return token_response['access_token']
        else:
            raise Exception(f"Could not obtain token: {token_response.get('error_description')}")

    def send_email(self, user, email_payload):
        headers = {
            "Authorization": f"Bearer {self.get_access_token()}",
            "Content-Type": "application/json"
        }
        response = requests.post(
            f'https://graph.microsoft.com/v1.0/users/{user}/sendMail',
            headers=headers,
            json=email_payload
        )

    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        envelope.rcpt_tos.append(address)
        return '250 OK'

    async def handle_DATA(self, server, session, envelope: Envelope):
        content = envelope.content.decode('utf8', errors='replace')
        b = email.message_from_string(content)

        email_data = parse_email(b)
        email_payload = construct_email_payload(email_data)
        self.send_email(envelope.mail_from, email_payload)

        return '250 Message accepted for delivery'


context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
context.load_cert_chain(
    os.environ.get('SSL_CERT_PATH'), os.environ.get('SSL_KEY_PATH')
)


class ControllerStarttls(UnthreadedController):
    def factory(self):
        return SMTP(self.handler, require_starttls=True, tls_context=context)


def authenticator_func(server, session, envelope, mechanism, auth_data: LoginPassword):
    if auth_data.login.decode('utf-8') != os.environ.get('SMTP_USERNAME') or auth_data.password.decode(
            'utf-8') != os.environ.get('SMTP_PASSWORD'):
        return AuthResult(success=False)

    return AuthResult(success=True)


async def main():
    loop = asyncio.get_running_loop()

    controller = aiosmtpd.controller.UnthreadedController(
        O365RelayHandler(),
        hostname='0.0.0.0', port=1025, loop=loop,
        tls_context=context,
        authenticator=authenticator_func,
        auth_required=True,
        auth_require_tls=os.environ.get('REQUIRE_TLS') == 'true'
    )
    server = await controller._create_server()
    await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
