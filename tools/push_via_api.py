# -*- coding: utf-8 -*-
"""用 GitHub REST API 把本地 git 提交推到远端（github.com 的 git-over-HTTPS 在本机被拦）。

用法：
    set GITHUB_TOKEN=ghp_xxx
    python tools\\push_via_api.py --dry
    python tools\\push_via_api.py

思路：以本地 `git ls-tree HEAD` 为准（已尊重 .gitignore 与删除），
逐文件算 git blob sha1 与远端树对比，只上传变化的 blob，最后建树/提交/移动分支。
"""
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = os.environ.get("GITHUB_REPO", "wzf771/image-capture")
BRANCH = os.environ.get("GITHUB_BRANCH", "main")
TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GIT = os.environ.get("GIT_EXE", r"E:\ImageCapture\tools\mingit\cmd\git.exe")
ROOT = os.environ.get("REPO_ROOT", r"D:\image-capture")
API = "https://api.github.com"

if not TOKEN:
    sys.exit("没有 GITHUB_TOKEN")


CURL = r"C:\Windows\System32\curl.exe"


def api(path, method="GET", payload=None):
    """走 curl.exe（本机 Python 的 OpenSSL 握手被中间设备打断，curl 用 schannel 正常）。"""
    url = path if path.startswith("https://") else API + path
    cmd = [CURL, "-sS", "--http1.1", "--retry", "3", "--retry-delay", "1",
           "--retry-all-errors", "--max-time", "180", "-X", method,
           "-H", "Authorization: Bearer " + TOKEN,
           "-H", "Accept: application/vnd.github+json",
           "-H", "X-GitHub-Api-Version: 2022-11-28"]
    if payload is not None:
        cmd += ["-H", "Content-Type: application/json",
                "--data-binary", "@-"]
    cmd.append(url)
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    proc = None
    for attempt in range(1, 12):                # VPN 线路不稳，握手失败就重试
        proc = subprocess.run(cmd, input=body, capture_output=True)
        if proc.returncode == 0:
            break
        time.sleep(1.5 * attempt)
    out = proc.stdout.decode("utf-8", "replace").strip()
    if proc.returncode != 0:
        raise SystemExit("curl 失败(%s): %s" % (proc.returncode, proc.stderr.decode("utf-8", "replace")[:300]))
    if not out:
        return {}
    try:
        data = json.loads(out)
    except Exception:
        raise SystemExit("接口返回不是 JSON: %s" % out[:300])
    if isinstance(data, dict) and data.get("message") and not data.get("sha"):
        raise SystemExit("GitHub 报错: %s" % data.get("message"))
    return data


def local_tree():
    """git ls-tree -r HEAD → [(mode, path)]"""
    out = subprocess.run([GIT, "-C", ROOT, "ls-tree", "-r", "-z", "HEAD"],
                         capture_output=True, check=True).stdout.decode("utf-8")
    items = []
    for rec in out.split("\0"):
        if not rec.strip():
            continue
        meta, path = rec.split("\t", 1)
        mode = meta.split()[0]
        items.append((mode, path))
    return items


def blob_sha(data):
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def main():
    dry = "--dry" in sys.argv
    ref = api("/repos/%s/git/ref/heads/%s" % (REPO, BRANCH))
    head = ref["object"]["sha"]
    commit = api("/repos/%s/git/commits/%s" % (REPO, head))
    base_tree = commit["tree"]["sha"]
    remote = {t["path"]: t for t in
              api("/repos/%s/git/trees/%s?recursive=1" % (REPO, base_tree)).get("tree", [])
              if t["type"] == "blob"}
    print("远端 HEAD=%s，文件 %d 个" % (head[:8], len(remote)))

    cache_path = os.path.join(ROOT, ".git", "api_push_cache.json")
    try:
        blob_cache = json.load(open(cache_path, encoding="utf-8"))
    except Exception:
        blob_cache = {}

    entries, up, same, gone = [], 0, 0, 0
    seen = set()
    for mode, rel in local_tree():
        seen.add(rel)
        full = os.path.join(ROOT, rel.replace("/", os.sep))
        data = open(full, "rb").read()
        sha = blob_sha(data)
        sha_local = sha
        old = remote.get(rel)
        if old and old["sha"] == sha:
            same += 1
            continue
        if dry:
            print("  更新:", rel)
            up += 1
            continue
        cached = blob_cache.get(rel)
        if isinstance(cached, dict) and cached.get("file_sha") == sha:
            sha = cached["blob_sha"]          # 内容没变才复用缓存
        else:
            blob = api("/repos/%s/git/blobs" % REPO, "POST",
                       {"content": base64.b64encode(data).decode("ascii"),
                        "encoding": "base64"})
            sha = blob["sha"]
            blob_cache[rel] = {"file_sha": sha_local, "blob_sha": sha}
            try:
                json.dump(blob_cache, open(cache_path, "w", encoding="utf-8"))
            except Exception:
                pass
        entries.append({"path": rel, "mode": "100755" if mode == "100755" else "100644",
                        "type": "blob", "sha": sha})
        up += 1
        print("  上传:", rel)

    for rel in remote:
        if rel not in seen:
            gone += 1
            print("  删除:", rel)
            if not dry:
                entries.append({"path": rel, "mode": "100644", "type": "blob", "sha": None})

    if dry:
        print("没变 %d，需上传 %d，需删除 %d" % (same, up, gone))
        return
    if not entries:
        print("远端已是最新，无需推送")
        return

    tree = api("/repos/%s/git/trees" % REPO, "POST",
               {"base_tree": base_tree, "tree": entries})
    # 默认提交信息从 app/version.py 里读，别再写死版本号（之前写死 1.0.4，1.0.5 的提交标题还是 1.0.4）
    ver = ""
    try:
        vp = os.path.join(ROOT, "app", "version.py")
        with open(vp, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VERSION"):
                    ver = line.split("=")[1].strip().strip('\"')
                    break
    except OSError:
        pass
    msg = os.environ.get("GITHUB_MSG") or ("release: Image capture %s" % ver if ver else "update")
    new_commit = api("/repos/%s/git/commits" % REPO, "POST",
                     {"message": msg, "tree": tree["sha"], "parents": [head]})
    api("/repos/%s/git/refs/heads/%s" % (REPO, BRANCH), "PATCH",
        {"sha": new_commit["sha"], "force": False})
    print("已推送 https://github.com/%s/commit/%s" % (REPO, new_commit["sha"]))


if __name__ == "__main__":
    main()
