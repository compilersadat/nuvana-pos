# NEW FILE: posapp/sms.py
import json
import logging
from typing import Optional
from django.conf import settings
from .models import SiteSetting

try:
    import requests
except Exception:
    requests = None

log = logging.getLogger(__name__)

def send_sms_textlocal(api_key: str, sender: str, number: str, message: str) -> bool:
    if not requests:
        log.warning("requests not available; SMS skipped")
        return False
    url = "https://api.textlocal.in/send/"
    data = {
        'apikey': api_key,
        'numbers': number,
        'message': message,
        'sender': sender or 'TXTLCL',
    }
    r = requests.post(url, data=data, timeout=10)
    ok = r.status_code == 200 and '"status":"success"' in r.text.lower()
    if not ok:
        log.warning("Textlocal SMS failed: %s %s", r.status_code, r.text[:200])
    return ok

def send_sms_msg91(api_key: str, sender: str, number: str, message: str) -> bool:
    if not requests:
        log.warning("requests not available; SMS skipped")
        return False
    url = "https://api.msg91.com/api/v5/flow/"
    # Using a simple flow-less payload (MSG91 strongly prefers template/flow in production)
    headers = {"accept":"application/json","content-type":"application/json","authkey":api_key}
    payload = {"sender": sender or "MSGIND", "short_url": "true", "recipients":[{"mobiles": number, "message": message}]}
    r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)
    ok = r.status_code in (200, 202)
    if not ok:
        log.warning("MSG91 SMS failed: %s %s", r.status_code, r.text[:200])
    return ok

def send_credit_alert(number: Optional[str], message: str) -> bool:
    if not number:
        return False
    s = SiteSetting.get()
    if not s.sms_enabled or not s.sms_api_key:
        return False
    if s.sms_provider == 'msg91':
        return send_sms_msg91(s.sms_api_key, s.sms_sender, number, message)
    return send_sms_textlocal(s.sms_api_key, s.sms_sender, number, message)
