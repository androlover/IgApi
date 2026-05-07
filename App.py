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
                try:
                    del jobs[job_id]
                except:
                    pass

threading.Thread(target=cleanup_old_files, daemon=True).start()


# ─── Format priority list (best se worst tak) ────────────────────────
FORMAT_PRIORITY = [
    "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]",
    "bestvideo[ext=mp4]+bestaudio/best[ext=mp4]",
    "bestvideo+bestaudio/best",
    "best[acodec!=none][vcodec!=none]",
    "best[ext=mp4]",
    "best",
]


# ─── Helpers ─────────────────────────────────────────────────────────
def extract_thumbnail(info):
    thumbnail = info.get("thumbnail", "")
    thumbnails = info.get("thumbnails", [])
    if thumbnails:
        thumbnail = thumbnails[-1].get("url", thumbnail)
    return thumbnail


# ─── URL cache (same URL dobara download na ho) ──────────────────────
url_cache = {}
url_cache_lock = threading.Lock()


# ─── Server-side merge ───────────────────────────────────────────────
def merge_and_cache(job_id: str, url: str):
    """
    yt_dlp + ffmpeg se video+audio merge karke server pe save karo.
    FORMAT_PRIORITY list waterfall: pehla jo kaam kare use karo.
    """
    jobs[job_id]["status"] = "processing"
    output_template = os.path.join(DOWNLOAD_DIR, f"{job_id}.%(ext)s")
    last_error = "No format worked"

    for fmt in FORMAT_PRIORITY:
        try:
            ydl_opts = {
                "outtmpl": output_template,
                "format": fmt,
                "merge_output_format": "mp4",
                "quiet": True,
                "no_warnings": True,
                "postprocessors": [
                    {
                        "key": "FFmpegVideoConvertor",
                        "preferedformat": "mp4",
                    }
                ],
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)

            # File dhundho
            filepath = os.path.join(DOWNLOAD_DIR, f"{job_id}.mp4")
            if not os.path.exists(filepath):
                actual_ext = info.get("ext", "mp4")
                filepath = os.path.join(DOWNLOAD_DIR, f"{job_id}.{actual_ext}")

            if not os.path.exists(filepath):
                raise FileNotFoundError(f"File nahi mili: {filepath}")

            jobs[job_id].update({
                "status": "done",
                "filename": os.path.basename(filepath),
                "filepath": filepath,
                "title": info.get("title", ""),
                "thumbnail": extract_thumbnail(info),
                "format_used": fmt,
                "filesize": os.path.getsize(filepath),
            })
            return  # success, bahar aa jao

        except Exception as e:
            last_error = str(e)
            # Partial files cleanup karo
            for ext in ["mp4", "m4a", "webm", "mkv", "part"]:
                f = os.path.join(DOWNLOAD_DIR, f"{job_id}.{ext}")
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except:
                        pass
            continue

    # Sab formats fail ho gaye
    jobs[job_id].update({
        "status": "error",
        "error": last_error,
    })
    # Cache se hata do taaki user retry kar sake
    with url_cache_lock:
        bad_keys = [k for k, v in url_cache.items() if v == job_id]
        for k in bad_keys:
            del url_cache[k]


def get_or_create_job(url: str) -> str:
    """Same URL ke liye existing job return karo, naya ho to banao."""
    with url_cache_lock:
        if url in url_cache:
            existing_id = url_cache[url]
            if existing_id in jobs and jobs[existing_id]["status"] != "error":
                return existing_id

        job_id = str(uuid.uuid4())
        jobs[job_id] = {"status": "queued", "created_at": time.time()}
        url_cache[url] = job_id

    threading.Thread(
        target=merge_and_cache,
        args=(job_id, url),
        daemon=True
    ).start()

    return job_id


# ─────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return jsonify({
        "message": "Reel API — Server-side merge (Audio Fixed 🔥)",
        "how_it_works": [
            "1. POST /info with url",
            "2. Poll GET /status/<job_id> jab tak status=done",
            "3. stream_url ya download_url use karo",
        ],
        "endpoints": {
            "POST /info": "Metadata + job shuru karo",
            "GET  /status/<job_id>": "Processing status",
            "GET  /stream/<job_id>": "Merged video stream karo",
            "GET  /file/<filename>": "Download karo",
        }
    })


# ─── INFO ────────────────────────────────────────────────────────────
@app.route("/info", methods=["POST"])
def get_info():
    data = request.get_json(force=True)
    url = (data or {}).get("url", "").strip()

    if not url:
        return jsonify({"error": "url required"}), 400

    # Quick metadata (no download)
    title, duration, thumbnail = "", None, ""
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
            meta = ydl.extract_info(url, download=False)
        title = meta.get("title", "")
        duration = meta.get("duration")
        thumbnail = extract_thumbnail(meta)
    except Exception:
        pass

    # Background merge shuru karo
    job_id = get_or_create_job(url)
    base_url = request.host_url.rstrip("/")

    return jsonify({
        "job_id": job_id,
        "title": title,
        "duration": duration,
        "thumbnail": thumbnail,
        "stream_url": f"{base_url}/stream/{job_id}",
        "status_url": f"{base_url}/status/{job_id}",
        "note": "status_url poll karo — jab status=done ho tab stream_url use karo",
    })


# ─── STREAM — Merged file range-aware serve ───────────────────────────
@app.route("/stream/<job_id>")
def stream_video(job_id):
    job = jobs.get(job_id)

    if not job:
        return jsonify({"error": "Job not found"}), 404

    if job["status"] == "error":
        return jsonify({"error": job.get("error", "Processing failed")}), 500

    if job["status"] != "done":
        return jsonify({
            "error": "Abhi processing ho rahi hai, thoda wait karo",
            "status": job["status"],
        }), 202

    filepath = job.get("filepath")
    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "File nahi mili server pe"}), 404

    filesize = os.path.getsize(filepath)
    range_header = request.headers.get("Range")

    if range_header:
        # Seeking support ke liye Range request handle karo
        byte_start, byte_end = 0, filesize - 1
        match = range_header.replace("bytes=", "").split("-")
        if match[0]:
            byte_start = int(match[0])
        if len(match) > 1 and match[1]:
            byte_end = int(match[1])

        length = byte_end - byte_start + 1

        def generate_range():
            with open(filepath, "rb") as f:
                f.seek(byte_start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(8192, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return Response(
            generate_range(),
            status=206,
            headers={
                "Content-Type": "video/mp4",
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes {byte_start}-{byte_end}/{filesize}",
                "Content-Length": str(length),
                "Content-Disposition": f'inline; filename="{job.get("filename", "video.mp4")}"',
            }
        )

    # Full file serve
    def generate_full():
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                yield chunk

    return Response(
        generate_full(),
        status=200,
        headers={
            "Content-Type": "video/mp4",
            "Accept-Ranges": "bytes",
            "Content-Length": str(filesize),
            "Content-Disposition": f'inline; filename="{job.get("filename", "video.mp4")}"',
        }
    )


# ─── STATUS ──────────────────────────────────────────────────────────
@app.route("/status/<job_id>")
def get_status(job_id):
    job = jobs.get(job_id)

    if not job:
        return jsonify({"error": "not found"}), 404

    base_url = request.host_url.rstrip("/")

    if job["status"] == "done":
        return jsonify({
            "status": "done",
            "stream_url": f"{base_url}/stream/{job_id}",
            "download_url": f"{base_url}/file/{job['filename']}",
            "title": job.get("title"),
            "thumbnail": job.get("thumbnail"),
            "filesize": job.get("filesize"),
            "format_used": job.get("format_used"),
        })

    return jsonify({
        "status": job["status"],
        "error": job.get("error"),
    })


# ─── DOWNLOAD trigger (same as /info without metadata) ───────────────
@app.route("/download", methods=["POST"])
def start_download():
    data = request.get_json(force=True)
    url = (data or {}).get("url", "").strip()

    if not url:
        return jsonify({"error": "url required"}), 400

    job_id = get_or_create_job(url)
    base_url = request.host_url.rstrip("/")

    return jsonify({
        "job_id": job_id,
        "status_url": f"{base_url}/status/{job_id}",
    })


# ─── SERVE FILE ──────────────────────────────────────────────────────
@app.route("/file/<filename>")
def serve_file(filename):
    return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=True)


# ─── RUN ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)