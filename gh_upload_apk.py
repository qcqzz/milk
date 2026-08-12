#!/usr/bin/env python3
""" 下载 artifact zip -> 解压 apk -> 上传到 release assets """
import json, os, sys, urllib.request, urllib.parse, zipfile, time, subprocess
from pathlib import Path

TOKEN = os.environ["GH_TOKEN"]
REPO = "qcqzz/chat"
RUN_ID = "31515292748"
RELEASE_ID = "368720752"
OUT_DIR = Path("/workspace/apk_out")
OUT_DIR.mkdir(exist_ok=True)

def gh(method, url, data=None, extra_headers=None, raw=False, json_resp=True):
    hdrs = {
        "Authorization": f"token {TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    if extra_headers:
        hdrs.update(extra_headers)
    body = None
    if data is not None:
        if isinstance(data, (bytes, bytearray)):
            body = bytes(data)
        else:
            body = json.dumps(data).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            content = r.read()
            if raw:
                return r.status, r.headers, content
            if json_resp:
                return json.loads(content.decode("utf-8", errors="replace"))
            return content.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code} on {method} {url}\n{body[:2000]}", file=sys.stderr)
        raise

# 1. list artifacts
print("1. list run artifacts")
arts = gh("GET", f"https://api.github.com/repos/{REPO}/actions/runs/{RUN_ID}/artifacts")
print(json.dumps(arts, ensure_ascii=False, indent=2)[:600])
art_id = arts["artifacts"][0]["id"]
art_name = arts["artifacts"][0]["name"]
print(f"selected artifact id={art_id} name={art_name}")

class NoAuthRedirectHandler(urllib.request.HTTPRedirectHandler):
    """ 第一次请求带 Authorization，但跟随 302/303 到 storage 域名时剥离 auth，防止签名校验冲突（Azure storage 报 403） """
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req is None:
            return None
        new_hdrs = dict(new_req.header_items())
        new_hdrs.pop("Authorization", None)
        new_hdrs.pop("Proxy-Authorization", None)
        return urllib.request.Request(
            new_req.full_url,
            data=new_req.data,
            headers=new_hdrs,
            origin_req_host=new_req.origin_req_host,
            unverifiable=new_req.unverifiable,
            method=new_req.get_method(),
        )

_no_auth_redirect_opener = None

def urlopen_no_auth_on_redirect(req, timeout=600):
    global _no_auth_redirect_opener
    if _no_auth_redirect_opener is None:
        _no_auth_redirect_opener = urllib.request.build_opener(NoAuthRedirectHandler)
    return _no_auth_redirect_opener.open(req, timeout=timeout)

# 2. download zip
zip_path = OUT_DIR / "artifact.zip"
print(f"2. downloading artifact zip -> {zip_path}")
# artifact download 是 302 重定向到 storage（Azure Blob 签名 URL），重定向后不能带 Authorization
url = f"https://api.github.com/repos/{REPO}/actions/artifacts/{art_id}/zip"
print(f"   fetching {url} ...")
req = urllib.request.Request(url, headers={"Authorization": f"token {TOKEN}"})
t0 = time.time()
with urlopen_no_auth_on_redirect(req, timeout=600) as r:
    total = int(r.headers.get("Content-Length") or 0)
    data = bytearray()
    chunk = 64 * 1024
    read = 0
    while True:
        buf = r.read(chunk)
        if not buf:
            break
        data.extend(buf)
        read += len(buf)
        if total:
            pct = read * 100 // total
            sys.stdout.write(f"\r   {read}/{total} bytes ({pct}%) elapsed {int(time.time()-t0)}s")
        else:
            sys.stdout.write(f"\r   read {read} bytes elapsed {int(time.time()-t0)}s")
        sys.stdout.flush()
print(f"\n   done. elapsed {int(time.time()-t0)}s size={len(data)}")
zip_path.write_bytes(bytes(data))
print(f"   saved {zip_path} size={zip_path.stat().st_size}")
if len(data) < 1024 * 1024:
    print(f"   WARNING: zip size {len(data)} < 1MB, probably error response. dump first 500 bytes:", file=sys.stderr)
    try:
        print(bytes(data[:500]).decode("utf-8", errors="replace"), file=sys.stderr)
    except Exception:
        pass
    sys.exit(3)

# 3. unzip
print("3. unzip")
with zipfile.ZipFile(zip_path) as z:
    z.extractall(OUT_DIR)
apk_files = list(OUT_DIR.glob("*.apk"))
print(f"   apk list: {[p.name for p in apk_files]}")
if not apk_files:
    print("ERROR: no apk inside zip", file=sys.stderr)
    sys.exit(1)
apk = apk_files[0]
print(f"   selected apk={apk} size={apk.stat().st_size}")

# 4. list existing assets, delete same-named ones
print("4. list existing release assets")
assets = gh("GET", f"https://api.github.com/repos/{REPO}/releases/{RELEASE_ID}/assets")
target_name = "app-v1.5.0-signed.apk"
for a in assets:
    print(f"   existing: id={a['id']} name={a['name']} size={a['size']}")
    if a["name"] == target_name or a["name"] == apk.name:
        print(f"   -> deleting existing {a['name']}")
        try:
            gh("DELETE", f"https://api.github.com/repos/{REPO}/releases/assets/{a['id']}", json_resp=False)
        except Exception as e:
            print(f"   delete warning: {e}")

# 5. upload apk as asset
# rename local apk copy to target_name
final_apk = OUT_DIR / target_name
import shutil
shutil.copyfile(apk, final_apk)
apk_bytes = final_apk.read_bytes()
up_url = (
    f"https://uploads.github.com/repos/{REPO}/releases/{RELEASE_ID}/assets"
    f"?name={urllib.parse.quote(target_name)}&label={urllib.parse.quote('Android APK (v1.5.0 已签名)')}"
)
print(f"5. uploading {target_name} ({len(apk_bytes)} bytes)")
t0 = time.time()
req = urllib.request.Request(
    up_url,
    data=apk_bytes,
    headers={
        "Authorization": f"token {TOKEN}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/vnd.android.package-archive",
    },
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=1200) as r:
        resp = json.loads(r.read().decode("utf-8"))
    print(f"   upload done. elapsed {int(time.time()-t0)}s")
    print(f"   asset id={resp.get('id')} name={resp.get('name')} download={resp.get('browser_download_url')}")
except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8", errors="replace")
    print(f"UPLOAD FAIL HTTP {e.code}\n{body[:3000]}", file=sys.stderr)
    sys.exit(2)

print("\nALL DONE")
print(f"Release page: https://github.com/{REPO}/releases/tag/v1.5.0")
print(f"APK direct download: https://github.com/{REPO}/releases/download/v1.5.0/{urllib.parse.quote(target_name)}")
