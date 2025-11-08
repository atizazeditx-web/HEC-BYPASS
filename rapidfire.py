import sys
sys.path.append(".local/lib/python3.13/site-packages")
import binascii
from mitmproxy import http
import yourdadrapidfirenigga
from decrypter_paneluserop import AESUtils
from proto_pure import ProtobufUtils
import requests
import time
from mitmproxy.tools.main import mitmdump
import threading
import os

# ==== CONFIG (remote UID server) ====
UID_CHECK_URL = os.getenv("UID_CHECK_URL", "http://localhost:1800/api/check/{}")
UID_CHECK_TIMEOUT = float(os.getenv("UID_CHECK_TIMEOUT", "5.0"))
# =====================================

# Use pure Python implementations
aesUtils = AESUtils()
protoUtils = ProtobufUtils()

def hexToOctetStream(hex_str: str) -> bytes:
    return bytes.fromhex(hex_str)

# --- (legacy kept for compatibility) ---
def fetchUIDsFromServer():
    """Deprecated: kept only for compatibility. Now using per-request /api/check/<uid>."""
    try:
        response = requests.get("http://localhost:1800/api/list", timeout=10)
        response.raise_for_status()
        uids = []
        for line in response.text.strip().split('\n'):
            line = line.strip()
            if line and line.isdigit():
                uids.append(line)
        return uids
    except Exception:
        return []
# ---------------------------------------

# NEW: per-request remote check (real-time)
def checkUIDStatus(uid: str) -> dict:
    """
    Ask remote UID server about a UID.
    Returns: {"ok": bool, "message": str}
    """
    try:
        url = UID_CHECK_URL.format(uid.strip())
        r = requests.get(url, timeout=UID_CHECK_TIMEOUT)
        try:
            data = r.json()
        except Exception:
            data = {}
        ok = bool(data.get("ok", False))
        msg = data.get("message", f"HTTP {r.status_code}")
        return {"ok": ok, "message": msg}
    except Exception as e:
        return {"ok": False, "message": f"UID check error: {e}"}

def checkUIDExists(uid: str) -> bool:
    return checkUIDStatus(uid).get("ok", False)

class MajorLoginInterceptor:
    def request(self, flow: http.HTTPFlow) -> None:
        if flow.request.method.upper() == "POST" and "/MajorLogin" in flow.request.path:
            enc_body = flow.request.content.hex()
            dec_body = aesUtils.decrypt_aes_cbc(enc_body)
            body = protoUtils.decode_protobuf(dec_body.hex(), yourdadrapidfirenigga.LoginReq)

            body.deviceData = "KqsHTxnXXUCG8sxXFVB2j0AUs3+0cvY/WgLeTdfTE/KPENeJPpny2EPnJDs8C8cBVMcd1ApAoCmM9MhzDDXabISdK31SKSFSr06eVCZ4D2Yj/C7G"
            body.reserved20 = b"\u0013RFC\u0007\u000e\\Q1"

            binary_data = body.SerializeToString()
            finalEncContent = aesUtils.encrypt_aes_cbc(
                hexToOctetStream(binary_data.hex())
            )
            flow.request.content = bytes.fromhex(finalEncContent.hex())

    def response(self, flow: http.HTTPFlow) -> None:
        if (
            flow.request.method.upper() == "POST"
            and "MajorLogin".lower() in flow.request.path.lower()
        ):
            respBody = flow.response.content.hex()
            decodedBody = protoUtils.decode_protobuf(respBody, yourdadrapidfirenigga.getUID)

            # ---- NEW: realtime check against remote server ----
            result = checkUIDStatus(str(decodedBody.uid))
            msg_lower = result['message'].lower()

            # status + uid color mapping
            if result.get("ok"):
                status_color = "[00FF00]"   # green
                uid_color = "[FFFFFF]"      # white
            elif "banned" in msg_lower:
                status_color = "[FF0000]"   # red
                uid_color = "[FF0000]"      # red
            elif "paused" in msg_lower or "expired" in msg_lower:
                status_color = "[FFFF00]"   # yellow
                uid_color = "[FFFF00]"      # yellow
            else:
                status_color = "[AAAAAA]"   # gray fallback
                uid_color = "[AAAAAA]"      # gray fallback

            if not result["ok"]:
                flow.response.content = (
                    f"[1E90FF]┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                    f"[1E90FF]┃   [00FF00]★  UID VERIFICATION  ★   [1E90FF]┃   [AAAAAA]{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}\n"
                    f"[1E90FF]┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫\n"
                    f"[FFD700]  ➜ UID    : {uid_color}{decodedBody.uid}\n"
                    f"[00FFFF]──────────────────────────────────────────────────────\n"
                    f"[FFD700]  ➜ STATUS : {status_color}{result['message']}\n"
                    f"[1E90FF]┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n"
                    f"[00FFFF]━━━━━━━━━━━━━━━━━━ </>HEC CORPORATION ━━━━━━━━━━━━━━━━━━\n"
                ).encode()
                flow.response.status_code = 400
                return None
            # ---------------------------------------------------

addons = [MajorLoginInterceptor()]

if __name__ == "__main__":
    mitmdump([
        "-s", "rapidfire.py",
        "-p", "30249",
        "--set", "block_global=false"
    ])
