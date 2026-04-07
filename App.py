import os
import uuid
import threading
import time
import requests
import urllib.parse
from flask import Flask, jsonify, request, send_from_directory, Response
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

jobs = {}

# ─── Cleanup old files ───────────────────────────────────────────────
def cleanup_old_files():
    while True:
        time.sleep(1800)
        now = time.time()
        for job_id in list(jobs.keys()):
            job = jobs[job_id]
            if job.get("created_at") and now - job["created_at"] > 3600:
                filepath = job.get("filepath")
                if filepath and os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except:
                        pass
                del jobs[job_id]

threading.Thread(target=cleanup_old_files, daemon=True).start()


# ─── Helpers ─────────────────────────────────────────────────────────
def extract_thumbnail(info):
    thumbnail = info.get("thumbnail", "")
    thumbnails = info.get("thumbnails", [])
    if thumbnails:
        thumbnail = thumbnails[-1].get("url", thumbnail)
    return thumbnail


def extract_video_url(info):
    formats = info.get("formats", [])

    for f in formats:
        if (
            f.get("ext") == "mp4"
            and f.get("vcodec") != "none"
            and f.get("acodec") != "none"
            and f.get("url")
        ):
            return f["url"]

    for f in formats:
        if f.get("url"):
            return f["url"]

    return info.get("url", "")


# ─── Background download ─────────────────────────────────────────────
def download_reel(job_id: str, url: str):
    jobs[job_id]["status"] = "downloading"

    output_template = os.path.join(DOWNLOAD_DIR, f"{job_id}.%(ext)s")

    try:
        with yt_dlp.YoutubeDL({
            "outtmpl": output_template,
            "format": "best[ext=mp4]/best",
            "quiet": True,
            "no_warnings": True,
        }) as ydl:
            info = ydl.extract_info(url, download=True)

        ext = info.get("ext", "mp4")
        filepath = os.path.join(DOWNLOAD_DIR, f"{job_id}.{ext}")

        jobs[job_id].update({
            "status": "done",
            "filename": f"{job_id}.{ext}",
            "filepath": filepath,
            "title": info.get("title", ""),
            "thumbnail": extract_thumbnail(info),
        })

    except Exception as e:
        jobs[job_id].update({
            "status": "error",
            "error": str(e),
        })


# ─────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return jsonify({
        "message": "Reel API (Download + Stream)",
        "endpoints": {
            "/info": "Get thumbnail + stream URL",
            "/stream": "Proxy stream video",
            "/download": "Download video (optional)",
            "/status/<job_id>": "Check download status",
        }
    })


# ─── INFO (FIXED 🔥) ─────────────────────────────────────────────────
@app.route("/info", methods=["POST"])
def get_info():
    data = request.get_json(force=True)
    url = (data or {}).get("url", "").strip()

    if not url:
        return jsonify({"error": "url required"}), 400

    try:
        with yt_dlp.YoutubeDL({
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
        }) as ydl:
            info = ydl.extract_info(url, download=False)

        video_url = extract_video_url(info)

        # 🔥 IMPORTANT: encode URL
        encoded_url = urllib.parse.quote(video_url, safe='')

        base_url = request.host_url.rstrip("/")

        return jsonify({
            "title": info.get("title", ""),
            "duration": info.get("duration"),
            "thumbnail": extract_thumbnail(info),
            "video_url": f"{base_url}/stream?url={encoded_url}"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── STREAM (FIXED 🔥) ───────────────────────────────────────────────
@app.route("/stream")
def stream_video():
    encoded_url = request.args.get("url")

    if not encoded_url:
        return "Missing url", 400

    try:
        # 🔥 decode URL
        url = urllib.parse.unquote(encoded_url)

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.instagram.com/"
        }

        r = requests.get(url, headers=headers, stream=True)

        return Response(
            r.iter_content(chunk_size=1024),
            content_type=r.headers.get("content-type", "video/mp4"),
        )

    except Exception as e:
        return str(e), 500


# ─── DOWNLOAD ────────────────────────────────────────────────────────
@app.route("/download", methods=["POST"])
def start_download():
    data = request.get_json(force=True)
    url = (data or {}).get("url", "").strip()

    if not url:
        return jsonify({"error": "url required"}), 400

    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "queued", "created_at": time.time()}

    threading.Thread(
        target=download_reel,
        args=(job_id, url),
        daemon=True
    ).start()

    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
def get_status(job_id):
    job = jobs.get(job_id)

    if not job:
        return jsonify({"error": "not found"}), 404

    base_url = request.host_url.rstrip("/")

    if job["status"] == "done":
        return jsonify({
            "status": "done",
            "download_url": f"{base_url}/file/{job['filename']}",
            "title": job.get("title"),
            "thumbnail": job.get("thumbnail"),
        })

    return jsonify(job)


@app.route("/file/<filename>")
def serve_file(filename):
    return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=True)


# ─── RUN ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)