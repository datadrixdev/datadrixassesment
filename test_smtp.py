import sys
import ssl
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from dotenv import load_dotenv
import os

load_dotenv(".env")

def test_smtp_send(username=None, password=None, to_email=None):
    username = (username or os.getenv("SMTP_USERNAME", "")).strip().strip('"').strip("'")
    password = (password or os.getenv("SMTP_PASSWORD", "")).strip().strip('"').strip("'")
    server_host = os.getenv("SMTP_SERVER", "smtp.gmail.com").strip()
    port = int(os.getenv("SMTP_PORT", 587))
    to_email = (to_email or username).strip()

    print(f"Connecting to SMTP server: {server_host}:{port} ...")
    print(f"Using SMTP Username:       {username}")
    print(f"Destination Recipient:     {to_email}")
    print("-" * 60)

    try:
        context = ssl.create_default_context()
        server = smtplib.SMTP(server_host, port, timeout=15)
        server.set_debuglevel(1)
        
        print("\n[Step 1] Sending initial EHLO...")
        server.ehlo()

        print("\n[Step 2] Initiating TLS encryption...")
        server.starttls(context=context)

        print("\n[Step 3] Re-negotiating EHLO over TLS...")
        server.ehlo()

        print(f"\n[Step 4] Authenticating with user '{username}'...")
        server.login(username, password)
        print(">>> SUCCESS: SMTP Authentication accepted by Google! <<<")

        print(f"\n[Step 5] Sending test evaluation email to '{to_email}'...")
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Datadrix Test Email - Live Delivery Verified"
        msg["From"] = f"Datadrix Assessments <{username}>"
        msg["To"] = to_email
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="datadrix.com")

        html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; padding: 20px; border: 1px solid #e2e8f0; border-radius: 10px;">
          <h2 style="color: #0284c7;">Datadrix Assessment Report Test</h2>
          <p>Congratulations! Your SMTP email connection is working successfully.</p>
          <p>Evaluation reports will now be delivered to candidates automatically.</p>
          <hr style="border: 0; border-top: 1px solid #e2e8f0;">
          <small style="color: #64748b;">Datadrix Automated Evaluation Engine</small>
        </div>
        """
        msg.attach(MIMEText(html, "html", "utf-8"))

        server.send_message(msg)
        server.quit()
        print(">>> SUCCESS: Email transmitted successfully! Check your inbox now! <<<")
        return True
    except smtplib.SMTPAuthenticationError as auth_err:
        print("\n" + "=" * 60)
        print("AUTHENTICATION FAILED (Google rejected the credentials):")
        print(f"Error Code: {auth_err.smtp_code}")
        print(f"Server Message: {auth_err.smtp_error.decode() if isinstance(auth_err.smtp_error, bytes) else auth_err.smtp_error}")
        print("=" * 60)
        return False
    except Exception as e:
        print(f"\nConnection Error: {type(e).__name__}: {e}")
        return False

if __name__ == "__main__":
    u = sys.argv[1] if len(sys.argv) > 1 else None
    p = sys.argv[2] if len(sys.argv) > 2 else None
    t = sys.argv[3] if len(sys.argv) > 3 else None
    test_smtp_send(u, p, t)
