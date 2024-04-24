import os
import smtplib
from email.message import EmailMessage

smtp_server = "127.0.0.1"
port = 1025
sender_email = os.environ.get('SMTP_USERNAME')
password = os.environ.get('SMTP_PASSWORD')

server = smtplib.SMTP(smtp_server, port)
if os.environ.get('REQUIRE_TLS') == 'true':
    server.starttls()
server.set_debuglevel(True)
server.login(sender_email, password)

msg = EmailMessage()
msg['Subject'] = 'Test subject'
msg['From'] = os.environ.get('SMTP_USERNAME')
msg['To'] = [os.environ.get('TARGET_EMAIL')]
msg.set_content('Hello there! This is email body')

server.send_message(msg)
