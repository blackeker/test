#!/usr/bin/env python3
"""
Yerel Ağ Dosya Paylaşım Sunucusu (Local Wi-Fi File Sharing)
Windows ve Android (Termux) üzerinde ek hiçbir kütüphane (pip) gerektirmeden çalışır.
"""

import os
import sys
import socket
import json
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

# Windows konsolunda Unicode/Türkçe karakter ve emoji hatalarını önleme
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PORT = 8000
SHARE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shared_files")
os.makedirs(SHARE_DIR, exist_ok=True)

def get_local_ips():
    """Cihazın yerel ağdaki (Hotspot dahil) tüm IP adreslerini bulur."""
    ips = set()

    # 1. Platforma özel komutlar ile tüm aktif ağ bağdaştırıcılarını tara (çevrimdışı/hotspot desteği)
    if sys.platform == "win32":
        try:
            import subprocess, re
            out = subprocess.check_output("ipconfig", text=True, errors="ignore")
            for line in out.splitlines():
                if any(k in line for k in ["IPv4", "IP Address", "Adres", "IPv4-Adres"]):
                    match = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
                    if match and not match.group(1).startswith("127."):
                        ips.add(match.group(1))
        except Exception:
            pass
    else:
        try:
            import subprocess, re
            out = subprocess.check_output(["ip", "-4", "addr"], text=True, errors="ignore")
            for match in re.finditer(r"inet (\d+\.\d+\.\d+\.\d+)", out):
                ip = match.group(1)
                if not ip.startswith("127."):
                    ips.add(ip)
        except Exception:
            try:
                out = subprocess.check_output(["ifconfig"], text=True, errors="ignore")
                for match in re.finditer(r"inet (?:addr:)?(\d+\.\d+\.\d+\.\d+)", out):
                    ip = match.group(1)
                    if not ip.startswith("127."):
                        ips.add(ip)
            except Exception:
                pass

    # 2. Soket ile aktif rota tespiti
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass

    # 3. Hostname çözümlemesi
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith("127."):
                ips.add(ip)
    except Exception:
        pass

    if not ips:
        ips.add("127.0.0.1")
    return sorted(list(ips))

def format_size(bytes_size):
    """Bayt cinsinden boyutu okunabilir formata dönüştürür."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} PB"

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>⚡ Yerel Dosya Aktarımı</title>
    <style>
        :root {
            --bg: #0f172a;
            --card-bg: #1e293b;
            --accent: #38bdf8;
            --accent-hover: #0284c7;
            --text: #f8fafc;
            --text-muted: #94a3b8;
            --border: #334155;
            --success: #22c55e;
            --danger: #ef4444;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
        }

        body {
            background-color: var(--bg);
            color: var(--text);
            padding: 20px;
            display: flex;
            justify-content: center;
            min-height: 100vh;
        }

        .container {
            width: 100%;
            max-width: 760px;
            display: flex;
            flex-direction: column;
            gap: 20px;
        }

        header {
            text-align: center;
            padding: 10px 0;
        }

        header h1 {
            font-size: 1.6rem;
            color: var(--accent);
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
        }

        header p {
            color: var(--text-muted);
            font-size: 0.9rem;
            margin-top: 6px;
        }

        .network-badge {
            display: inline-flex;
            align-items: center;
            background: #1e293b;
            border: 1px solid var(--border);
            padding: 6px 14px;
            border-radius: 9999px;
            font-size: 0.85rem;
            color: var(--accent);
            margin-top: 10px;
            gap: 8px;
        }

        .dot {
            width: 8px;
            height: 8px;
            background: var(--success);
            border-radius: 50%;
            box-shadow: 0 0 8px var(--success);
        }

        .card {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
        }

        /* Yükleme Alanı */
        .dropzone {
            border: 2px dashed var(--border);
            border-radius: 10px;
            padding: 30px 20px;
            text-align: center;
            cursor: pointer;
            transition: all 0.2s ease;
            position: relative;
        }

        .dropzone:hover, .dropzone.dragover {
            border-color: var(--accent);
            background: rgba(56, 189, 248, 0.05);
        }

        .dropzone svg {
            width: 48px;
            height: 48px;
            fill: var(--accent);
            margin-bottom: 10px;
        }

        .dropzone input[type="file"] {
            display: none;
        }

        .upload-btn {
            background: var(--accent);
            color: #0f172a;
            font-weight: 600;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            margin-top: 12px;
            cursor: pointer;
            display: inline-block;
            transition: background 0.2s;
        }

        .upload-btn:hover {
            background: var(--accent-hover);
        }

        /* İlerleme Çubuğu */
        .progress-box {
            display: none;
            margin-top: 16px;
        }

        .progress-bar-bg {
            width: 100%;
            height: 8px;
            background: var(--border);
            border-radius: 4px;
            overflow: hidden;
        }

        .progress-bar-fill {
            height: 100%;
            width: 0%;
            background: var(--accent);
            transition: width 0.1s linear;
        }

        .progress-label {
            display: flex;
            justify-content: space-between;
            font-size: 0.8rem;
            color: var(--text-muted);
            margin-top: 6px;
        }

        /* Dosya Listesi */
        .file-list-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 14px;
        }

        .file-list-header h2 {
            font-size: 1.2rem;
            font-weight: 600;
        }

        .refresh-btn {
            background: transparent;
            border: 1px solid var(--border);
            color: var(--text);
            padding: 6px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.85rem;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .refresh-btn:hover {
            background: var(--border);
        }

        .file-list {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .file-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px 14px;
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid var(--border);
            border-radius: 8px;
            transition: transform 0.1s;
        }

        .file-info {
            display: flex;
            align-items: center;
            gap: 12px;
            overflow: hidden;
        }

        .file-icon {
            font-size: 1.5rem;
            line-height: 1;
        }

        .file-details {
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        .file-name {
            font-size: 0.95rem;
            font-weight: 500;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 320px;
        }

        .file-meta {
            font-size: 0.75rem;
            color: var(--text-muted);
            margin-top: 3px;
        }

        .file-actions {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .action-btn {
            padding: 7px 12px;
            border-radius: 6px;
            font-size: 0.82rem;
            font-weight: 500;
            text-decoration: none;
            cursor: pointer;
            border: none;
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }

        .download-btn {
            background: #0284c7;
            color: #fff;
        }

        .download-btn:hover {
            background: #0369a1;
        }

        .delete-btn {
            background: rgba(239, 68, 68, 0.15);
            color: #fca5a5;
            border: 1px solid rgba(239, 68, 68, 0.3);
        }

        .delete-btn:hover {
            background: rgba(239, 68, 68, 0.3);
        }

        .empty-state {
            text-align: center;
            padding: 30px 10px;
            color: var(--text-muted);
            font-size: 0.9rem;
        }

        @media (max-width: 600px) {
            .file-name {
                max-width: 150px;
            }
            .action-btn span {
                display: none;
            }
        }
    </style>
</head>
<body>

<div class="container">
    <header>
        <h1>⚡ Wi-Fi Dosya Aktarımı</h1>
        <p>İnternet kotası harcamadan iki cihaz arasında doğrudan yerel aktarım</p>
        <div class="network-badge">
            <span class="dot"></span>
            <span id="network-ip">Bağlantı Hazır</span>
        </div>
    </header>

    <div class="card">
        <div class="dropzone" id="dropzone">
            <svg viewBox="0 0 24 24">
                <path d="M19.35 10.04C18.67 6.59 15.64 4 12 4 9.11 4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96zM14 13v4h-4v-4H7l5-5 5 5h-3z"/>
            </svg>
            <h3>Dosyaları Buraya Sürükleyin</h3>
            <p style="color: var(--text-muted); font-size: 0.85rem; margin-top: 5px;">veya dosya seçmek için tıklayın</p>
            <button class="upload-btn" type="button">Dosya Seç</button>
            <input type="file" id="fileInput" multiple>
        </div>

        <div class="progress-box" id="progressBox">
            <div class="progress-bar-bg">
                <div class="progress-bar-fill" id="progressBar"></div>
            </div>
            <div class="progress-label">
                <span id="progressFile">Gönderiliyor...</span>
                <span id="progressPercent">0%</span>
            </div>
        </div>
    </div>

    <div class="card">
        <div class="file-list-header">
            <h2>Paylaşılan Dosyalar</h2>
            <button class="refresh-btn" onclick="loadFiles()">
                ↻ Yenile
            </button>
        </div>
        <div class="file-list" id="fileList">
            <div class="empty-state">Henüz dosya yüklenmedi.</div>
        </div>
    </div>
</div>

<script>
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('fileInput');
    const progressBox = document.getElementById('progressBox');
    const progressBar = document.getElementById('progressBar');
    const progressFile = document.getElementById('progressFile');
    const progressPercent = document.getElementById('progressPercent');
    const fileList = document.getElementById('fileList');

    document.getElementById('network-ip').textContent = 'http://' + window.location.host;

    // Tıklama ile dosya seçimi
    dropzone.addEventListener('click', () => fileInput.click());

    // Sürükle-bırak olayları
    ['dragenter', 'dragover'].forEach(name => {
        dropzone.addEventListener(name, (e) => {
            e.preventDefault();
            dropzone.classList.add('dragover');
        });
    });

    ['dragleave', 'drop'].forEach(name => {
        dropzone.addEventListener(name, (e) => {
            e.preventDefault();
            dropzone.classList.remove('dragover');
        });
    });

    dropzone.addEventListener('drop', (e) => {
        if (e.dataTransfer.files.length > 0) {
            uploadFiles(Array.from(e.dataTransfer.files));
        }
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files.length > 0) {
            uploadFiles(Array.from(fileInput.files));
        }
    });

    // Dosyaları sırayla yükle
    async function uploadFiles(files) {
        progressBox.style.display = 'block';

        for (let i = 0; i < files.length; i++) {
            const file = files[i];
            await uploadSingleFile(file, i + 1, files.length);
        }

        setTimeout(() => {
            progressBox.style.display = 'none';
            progressBar.style.width = '0%';
            loadFiles();
            fileInput.value = '';
        }, 1000);
    }

    function uploadSingleFile(file, index, total) {
        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            const url = '/api/upload?filename=' + encodeURIComponent(file.name);

            xhr.open('POST', url, true);

            xhr.upload.onprogress = (e) => {
                if (e.lengthComputable) {
                    const percent = Math.round((e.loaded / e.total) * 100);
                    progressBar.style.width = percent + '%';
                    progressPercent.textContent = percent + '%';
                    progressFile.textContent = `[${index}/${total}] ${file.name}`;
                }
            };

            xhr.onload = () => {
                if (xhr.status === 200) {
                    resolve();
                } else {
                    alert('Hata: ' + file.name + ' yüklenemedi.');
                    reject();
                }
            };

            xhr.onerror = () => {
                alert('Ağ hatası oluştu!');
                reject();
            };

            xhr.send(file);
        });
    }

    function getFileIcon(filename) {
        const ext = filename.split('.').pop().toLowerCase();
        if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'].includes(ext)) return '🖼️';
        if (['mp4', 'mkv', 'mov', 'avi'].includes(ext)) return '🎬';
        if (['mp3', 'wav', 'ogg', 'flac'].includes(ext)) return '🎵';
        if (['zip', 'rar', '7z', 'tar', 'gz'].includes(ext)) return '📦';
        if (['pdf', 'doc', 'docx', 'txt', 'md'].includes(ext)) return '📄';
        if (['apk'].includes(ext)) return '🤖';
        return '📁';
    }

    async function loadFiles() {
        try {
            const res = await fetch('/api/files');
            const files = await res.json();

            if (files.length === 0) {
                fileList.innerHTML = '<div class="empty-state">Henüz paylaşılan dosya yok.</div>';
                return;
            }

            fileList.innerHTML = files.map(file => `
                <div class="file-item">
                    <div class="file-info">
                        <span class="file-icon">${getFileIcon(file.name)}</span>
                        <div class="file-details">
                            <span class="file-name" title="${file.name}">${file.name}</span>
                            <span class="file-meta">${file.size} • ${file.mtime}</span>
                        </div>
                    </div>
                    <div class="file-actions">
                        <a href="/download/${encodeURIComponent(file.name)}" class="action-btn download-btn" download="${file.name}">
                            ⬇️ <span>İndir</span>
                        </a>
                        <button class="action-btn delete-btn" onclick="deleteFile('${encodeURIComponent(file.name)}')">
                            🗑️
                        </button>
                    </div>
                </div>
            `).join('');
        } catch (err) {
            console.error('Dosyalar yüklenirken hata:', err);
        }
    }

    async function deleteFile(encodedName) {
        if (!confirm('Bu dosyayı silmek istediğinize emin misiniz?')) return;
        try {
            const res = await fetch('/api/delete?filename=' + encodedName, { method: 'DELETE' });
            if (res.ok) {
                loadFiles();
            } else {
                alert('Dosya silinemedi.');
            }
        } catch (err) {
            alert('Hata: ' + err);
        }
    }

    // İlk açılışta dosyaları getir
    loadFiles();
</script>

</body>
</html>
"""

class FileTransferHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Sade log formatı
        sys.stdout.write(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]} - {args[1]}\n")

    def send_error(self, code, message=None, explain=None):
        if message:
            tr_map = str.maketrans('ıİşŞğĞöÖüÜçÇ', 'iIsSgGoOuUcC')
            message = message.translate(tr_map).encode('latin-1', 'replace').decode('latin-1')
        super().send_error(code, message, explain)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            content = INDEX_HTML.encode("utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        elif path == "/api/files":
            files_info = []
            if os.path.exists(SHARE_DIR):
                for fname in sorted(os.listdir(SHARE_DIR)):
                    fpath = os.path.join(SHARE_DIR, fname)
                    if os.path.isfile(fpath):
                        stat = os.stat(fpath)
                        files_info.append({
                            "name": fname,
                            "size": format_size(stat.st_size),
                            "bytes": stat.st_size,
                            "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%d.%m.%Y %H:%M")
                        })
            # En son yüklenenler
            files_info.sort(key=lambda x: x["mtime"], reverse=True)

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            content = json.dumps(files_info).encode("utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        elif path.startswith("/download/"):
            filename = urllib.parse.unquote(path[len("/download/"):])
            # Güvenlik kontrolü (path traversal engelleme)
            filename = os.path.basename(filename)
            filepath = os.path.join(SHARE_DIR, filename)

            if os.path.isfile(filepath):
                file_size = os.path.getsize(filepath)
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                filename_encoded = urllib.parse.quote(filename)
                self.send_header("Content-Disposition", f'attachment; filename="{filename_encoded}"; filename*=UTF-8\'\'{filename_encoded}')
                self.send_header("Content-Length", str(file_size))
                self.end_headers()

                # Parça parça gönder (RAM tüketmez, büyük dosyaları destekler)
                with open(filepath, "rb") as f:
                    while chunk := f.read(64 * 1024):
                        self.wfile.write(chunk)
                return
            else:
                self.send_error(404, "Dosya bulunamadi")
                return

        else:
            self.send_error(404, "Bulunamadi")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/upload":
            query = urllib.parse.parse_qs(parsed.query)
            filename = query.get("filename", ["uploaded_file"])[0]
            filename = os.path.basename(urllib.parse.unquote(filename))

            if not filename:
                filename = f"file_{int(datetime.now().timestamp())}"

            target_path = os.path.join(SHARE_DIR, filename)

            # Eğer aynı isimde dosya varsa üzerine yazmamak için numara ekle
            base, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(target_path):
                target_path = os.path.join(SHARE_DIR, f"{base}_{counter}{ext}")
                counter += 1

            content_length = int(self.headers.get("Content-Length", 0))

            # Doğrudan diske akış (streaming)
            bytes_left = content_length
            with open(target_path, "wb") as f:
                while bytes_left > 0:
                    read_chunk = min(bytes_left, 64 * 1024)
                    chunk = self.rfile.read(read_chunk)
                    if not chunk:
                        break
                    f.write(chunk)
                    bytes_left -= len(chunk)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            res_data = json.dumps({"status": "success", "saved": os.path.basename(target_path)}).encode("utf-8")
            self.send_header("Content-Length", str(len(res_data)))
            self.end_headers()
            self.wfile.write(res_data)
            return

        self.send_error(404, "Bulunamadi")

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/delete":
            query = urllib.parse.parse_qs(parsed.query)
            filename = query.get("filename", [""])[0]
            filename = os.path.basename(urllib.parse.unquote(filename))
            target_path = os.path.join(SHARE_DIR, filename)

            if os.path.isfile(target_path):
                try:
                    os.remove(target_path)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    res = json.dumps({"status": "deleted"}).encode("utf-8")
                    self.send_header("Content-Length", str(len(res)))
                    self.end_headers()
                    self.wfile.write(res)
                    return
                except Exception as e:
                    self.send_error(500, f"Silinemedi: {e}")
                    return

            self.send_error(404, "Dosya bulunamadi")
            return

        self.send_error(404, "Bulunamadi")

def run():
    server_address = ("0.0.0.0", PORT)
    httpd = HTTPServer(server_address, FileTransferHandler)
    ips = get_local_ips()

    print("\n" + "=" * 55)
    print(">>> YEREL AG DOSYA AKTARIM SUNUCUSU BASLATILDI <<<")
    print("=" * 55)
    print(f"[*] Paylasilan Klasor: {SHARE_DIR}")
    print("\n[+] Cihazlarinizdan tarayiciyi acip su adrese girin:")
    print("-" * 55)
    print(f"  * Sunucunun calistigi cihaz : http://localhost:{PORT}")
    for ip in ips:
        print(f"  * Diger cihazdan (Wi-Fi)   : http://{ip}:{PORT}")
    print("-" * 55)
    print("[!] Durdurmak icin terminalde Ctrl + C tuslarina basin.\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] Sunucu durduruldu.")
        httpd.server_close()

if __name__ == "__main__":
    run()
