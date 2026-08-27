import base64,hashlib,hmac
from datetime import datetime,timezone
WSSE="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
WSU="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
def authenticate(root,username,password,tolerance):
    user=root.find(f".//{{{WSSE}}}Username"); pw=root.find(f".//{{{WSSE}}}Password")
    if user is None or pw is None or not hmac.compare_digest(user.text or "",username): return False
    if "PasswordDigest" not in pw.attrib.get("Type",""): return hmac.compare_digest(pw.text or "",password)
    nonce=root.find(f".//{{{WSSE}}}Nonce"); created=root.find(f".//{{{WSU}}}Created")
    if nonce is None or created is None or not nonce.text or not created.text: return False
    try:
        dt=datetime.fromisoformat(created.text.replace("Z","+00:00"))
        if abs((datetime.now(timezone.utc)-dt).total_seconds())>tolerance: return False
        raw=base64.b64decode(nonce.text,validate=True)
    except (ValueError,TypeError): return False
    expected=base64.b64encode(hashlib.sha1(raw+created.text.encode()+password.encode()).digest()).decode()
    return hmac.compare_digest(pw.text or "",expected)
