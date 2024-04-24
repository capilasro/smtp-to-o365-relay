import asyncio
import email
import os
import ssl

import aiosmtpd
from O365 import Account
from aiosmtpd.controller import UnthreadedController
from aiosmtpd.smtp import SMTP, AuthResult, LoginPassword


class O365RelayHandler:

    def __init__(self):
        credentials = (
            os.environ.get('AZURE_CLIENT_ID'),
            os.environ.get('AZURE_CLIENT_SECRET')
        )
        self.account = Account(credentials, auth_flow_type='credentials', tenant_id=os.environ.get('AZURE_TENANT_ID'))
        self.account.authenticate()

    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        envelope.rcpt_tos.append(address)
        return '250 OK'

    async def handle_DATA(self, server, session, envelope):
        content = envelope.content.decode('utf8', errors='replace')
        b = email.message_from_string(content)
        body = ""

        if b.is_multipart():
            for part in b.walk():
                ctype = part.get_content_type()
                cdispo = str(part.get('Content-Disposition'))

                if ctype == 'text/plain' and 'attachment' not in cdispo:
                    body = part.get_payload(decode=True)  # decode
                    break
        else:
            body = b.get_payload(decode=True)

        mailbox = self.account.mailbox(envelope.mail_from)
        m = mailbox.new_message()
        m.to.add(envelope.rcpt_tos)
        m.subject = b.get('Subject')
        m.body = body.decode('utf-8', errors='replace')
        m.save_message()
        m.send()

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
