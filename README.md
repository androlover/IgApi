# 📥 Instagram Reel Downloader API

A lightweight Flask API that downloads Instagram Reels using `yt-dlp` and serves them via a temporary download link — ready to integrate with your Android app.

---

## 🚀 Deploy on Render (Free Tier)

1. Push this project to a **GitHub repo**
2. Go to [render.com](https://render.com) → **New Web Service**
3. Connect your GitHub repo
4. Render auto-detects `render.yaml` — just click **Deploy**
5. Your API will be live at: `https://your-service.onrender.com`

> ⚠️ **Free tier note:** Render spins down after 15 min of inactivity. First request after sleep takes ~30s. Downloads are kept for **1 hour** then auto-deleted.

---

## 📡 API Endpoints

### `POST /download`
Start a download job.

**Request:**
```json
{ "url": "https://www.instagram.com/reel/XXXXXXX/" }
```

**Response `202`:**
```json
{ "job_id": "abc-123-uuid", "status": "queued" }
```

---

### `GET /status/{job_id}`
Poll until status is `done`.

**Response (pending):**
```json
{ "job_id": "abc-123", "status": "downloading" }
```

**Response (done):**
```json
{
  "job_id": "abc-123",
  "status": "done",
  "title": "Reel title here",
  "download_url": "https://your-service.onrender.com/file/abc-123.mp4"
}
```

**Response (error):**
```json
{ "job_id": "abc-123", "status": "error", "error": "reason here" }
```

---

### `GET /file/{filename}`
Direct download of the MP4 file. Use this URL in your Android app.

---

## 📱 Android Integration (Kotlin)

```kotlin
// 1. Start download
val client = OkHttpClient()
val json = JSONObject().put("url", instagramUrl).toString()
val body = json.toRequestBody("application/json".toMediaType())
val request = Request.Builder()
    .url("https://your-service.onrender.com/download")
    .post(body)
    .build()

val response = client.newCall(request).execute()
val jobId = JSONObject(response.body!!.string()).getString("job_id")

// 2. Poll status
fun pollStatus(jobId: String): String {
    while (true) {
        Thread.sleep(2000)
        val req = Request.Builder()
            .url("https://your-service.onrender.com/status/$jobId")
            .build()
        val res = client.newCall(req).execute()
        val data = JSONObject(res.body!!.string())
        when (data.getString("status")) {
            "done" -> return data.getString("download_url")
            "error" -> throw Exception(data.getString("error"))
        }
    }
}

// 3. Use the download URL (stream or download)
val downloadUrl = pollStatus(jobId)
// Pass to DownloadManager, ExoPlayer, or VideoView
```

---

## 📂 Project Structure

```
insta-dl-api/
├── app.py            # Flask API
├── requirements.txt  # Dependencies
├── render.yaml       # Render deployment config
└── README.md
```

---

## ⚙️ Local Development

```bash
pip install -r requirements.txt
python app.py
# API runs at http://localhost:5000
```

Test with curl:
```bash
curl -X POST http://localhost:5000/download \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.instagram.com/reel/YOUR_REEL_ID/"}'
```
