import smtplib, ssl
from email.message import EmailMessage


def validate_address(address, label):
    """Reject bare display names before passing them to smtplib."""
    from email.utils import parseaddr
    if not isinstance(address, str) or len(address) > 254:
        raise ValueError(f'{label}: gültige E-Mail-Adresse eingeben')
    name, parsed = parseaddr(address)
    if (name or parsed != address or address.count('@') != 1 or
            any(c.isspace() for c in address) or
            not all(address.split('@')) or '.' not in address.rsplit('@', 1)[1]):
        raise ValueError(f'{label}: vollständige E-Mail-Adresse eingeben')

def mail_error(exc):
    """Return safe user-facing SMTP diagnostics without credentials."""
    import smtplib
    import ssl
    import socket
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return 'SMTP-Anmeldung fehlgeschlagen (Code %s). Benutzername und Passwort prüfen.' % exc.smtp_code
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return 'SMTP-Absender abgelehnt (Code %s). Absender-E-Mail-Adresse prüfen.' % exc.smtp_code
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return 'SMTP-Empfänger abgelehnt. Empfänger-E-Mail-Adresse prüfen.'
    if isinstance(exc, smtplib.SMTPResponseException):
        return 'SMTP-Server meldet Fehler %s. SMTP-Einstellungen prüfen.' % exc.smtp_code
    if isinstance(exc, (ssl.SSLError, smtplib.SMTPNotSupportedError)):
        return 'SMTP-Verschlüsselung fehlgeschlagen. TLS-Einstellung und Port prüfen.'
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return 'Zeitüberschreitung beim SMTP-Server. Server und Port prüfen.'
    if isinstance(exc, (ConnectionError, OSError)):
        return 'SMTP-Server nicht erreichbar. Server, Port und Netzwerk prüfen.'
    return 'E-Mail-Versand fehlgeschlagen. Serverprotokoll prüfen.'

def send(settings,subject,body):
    host=settings.get('host',''); port=int(settings.get('port',587)); mode=settings.get('mode','starttls')
    if not host or not 1<=port<=65535 or mode not in ('starttls','ssl'): raise ValueError('SMTP-Einstellungen unvollständig')
    validate_address(settings['sender'], 'Absender'); validate_address(settings['recipient'], 'Empfänger')
    message=EmailMessage(); message['From']=settings['sender']; message['To']=settings['recipient']; message['Subject']=subject; message.set_content(body)
    context=ssl.create_default_context()
    if mode=='ssl': server=smtplib.SMTP_SSL(host,port,timeout=10,context=context)
    else: server=smtplib.SMTP(host,port,timeout=10)
    with server as smtp:
        if mode=='starttls': smtp.starttls(context=context)
        if settings.get('username'): smtp.login(settings['username'],settings.get('password',''))
        smtp.send_message(message)
