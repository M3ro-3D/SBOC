import smtplib, ssl
from email.message import EmailMessage

def send(settings,subject,body):
    host=settings.get('host',''); port=int(settings.get('port',587)); mode=settings.get('mode','starttls')
    if not host or not 1<=port<=65535 or mode not in ('starttls','ssl'): raise ValueError('SMTP-Einstellungen unvollständig')
    message=EmailMessage(); message['From']=settings['sender']; message['To']=settings['recipient']; message['Subject']=subject; message.set_content(body)
    context=ssl.create_default_context()
    if mode=='ssl': server=smtplib.SMTP_SSL(host,port,timeout=10,context=context)
    else: server=smtplib.SMTP(host,port,timeout=10)
    with server as smtp:
        if mode=='starttls': smtp.starttls(context=context)
        if settings.get('username'): smtp.login(settings['username'],settings.get('password',''))
        smtp.send_message(message)
