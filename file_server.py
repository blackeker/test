#!/usr/bin/env python3

import os
import sys
import socket
import json
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
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
    """Cihazın yerel ağdaki (Hotspot dahil, SIM kartsız/çevrimdışı) tüm IP adreslerini bulur."""
    ips = set()

    # 1. Platforma özel komutlar ile tara
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
        # Linux / Android (Termux)
        try:
            import subprocess, re
            out = subprocess.check_output(["ip", "-4", "addr"], text=True, errors="ignore")
            for match in re.finditer(r"inet (\d+\.\d+\.\d+\.\d+)", out):
                ip = match.group(1)
                if not ip.startswith("127."):
                    ips.add(ip)
        except Exception:
            pass

        try:
            import subprocess, re
            out = subprocess.check_output(["ifconfig"], text=True, errors="ignore")
            for match in re.finditer(r"inet (?:addr:)?(\d+\.\d+\.\d+\.\d+)", out):
                ip = match.group(1)
                if not ip.startswith("127."):
                    ips.add(ip)
        except Exception:
            pass

        # Android /proc/net/fib_trie parsing (Hat/İnternet yokken bile IP bulur)
        try:
            import re
            if os.path.exists("/proc/net/fib_trie"):
                with open("/proc/net/fib_trie", "r") as f:
                    content = f.read()
                    for match in re.finditer(r"/32 host LOCAL\s+30\s+1\s+0\s+(\d+\.\d+\.\d+\.\d+)", content):
                        ip = match.group(1)
                        if not ip.startswith("127."):
                            ips.add(ip)
        except Exception:
            pass

    # 2. Çevrimdışı UDP Broadcast Soket Taraması (SIM kart / İnternet yokken IP bulur)
    for target in [("255.255.255.255", 1), ("192.168.255.255", 1), ("10.255.255.255", 1), ("172.31.255.255", 1)]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.connect(target)
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                ips.add(ip)
            s.close()
        except Exception:
            pass

    # 3. Aktif rota soketi
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass

    # 4. Hostname çözümü
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith("127."):
                ips.add(ip)
    except Exception:
        pass

    # 5. Android Hotspot için bilinen varsayılan IP'leri ekle (Varsa)
    if sys.platform != "win32":
        # Samsung / Android Hotspot standart IP'si 192.168.43.1 veya 192.168.49.1
        ips.add("192.168.43.1")

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
    <title>Dosya Aktarımı</title>
    <style>
        :root {
            --bg: #0f1117;
            --card-bg: #1a1d24;
            --border: #2a2e39;
            --accent: #2563eb;
            --accent-hover: #1d4ed8;
            --text: #f3f4f6;
            --text-muted: #9ca3af;
            --danger: #dc2626;
            --danger-hover: #b91c1c;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }

        body {
            background-color: var(--bg);
            color: var(--text);
            padding: 16px;
            display: flex;
            justify-content: center;
            min-height: 100vh;
        }

        .container {
            width: 100%;
            max-width: 640px;
            display: flex;
            flex-direction: column;
            gap: 16px;
        }

        header {
            text-align: center;
            padding: 4px 0;
        }

        .network-badge {
            display: inline-flex;
            align-items: center;
            background: var(--card-bg);
            border: 1px solid var(--border);
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 0.85rem;
            color: var(--text-muted);
            gap: 8px;
        }

        .dot {
            width: 8px;
            height: 8px;
            background: #22c55e;
            border-radius: 50%;
        }

        .card {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 16px;
        }

        .dropzone {
            border: 2px dashed var(--border);
            border-radius: 8px;
            padding: 24px 16px;
            text-align: center;
            cursor: pointer;
            transition: border-color 0.15s;
        }

        .dropzone:hover, .dropzone.dragover {
            border-color: var(--accent);
        }

        .dropzone svg {
            width: 40px;
            height: 40px;
            fill: var(--text-muted);
            margin-bottom: 8px;
        }

        .dropzone input[type="file"] {
            display: none;
        }

        .upload-btn {
            background: var(--accent);
            color: #ffffff;
            font-weight: 500;
            border: none;
            padding: 8px 18px;
            border-radius: 6px;
            margin-top: 10px;
            cursor: pointer;
            font-size: 0.9rem;
            display: inline-block;
        }

        .upload-btn:hover {
            background: var(--accent-hover);
        }

        .progress-box {
            display: none;
            margin-top: 14px;
        }

        .progress-bar-bg {
            width: 100%;
            height: 6px;
            background: var(--border);
            border-radius: 3px;
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

        .file-list-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }

        .file-list-header h2 {
            font-size: 1.05rem;
            font-weight: 600;
        }

        .refresh-btn {
            background: transparent;
            border: 1px solid var(--border);
            color: var(--text-muted);
            padding: 4px 10px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.85rem;
        }

        .refresh-btn:hover {
            color: var(--text);
            border-color: var(--text-muted);
        }

        .file-list {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .file-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 10px 12px;
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 6px;
        }

        .file-info {
            display: flex;
            align-items: center;
            gap: 10px;
            overflow: hidden;
        }

        .file-icon {
            font-size: 1.2rem;
            line-height: 1;
        }

        .file-details {
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        .file-name {
            font-size: 0.9rem;
            font-weight: 500;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 280px;
        }

        .file-meta {
            font-size: 0.75rem;
            color: var(--text-muted);
            margin-top: 2px;
        }

        .file-actions {
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .action-btn {
            padding: 6px 10px;
            border-radius: 4px;
            font-size: 0.8rem;
            font-weight: 500;
            text-decoration: none;
            cursor: pointer;
            border: none;
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }

        .download-btn {
            background: var(--accent);
            color: #ffffff;
        }

        .download-btn:hover {
            background: var(--accent-hover);
        }

        .delete-btn {
            background: var(--danger);
            color: #ffffff;
        }

        .delete-btn:hover {
            background: var(--danger-hover);
        }

        .empty-state {
            text-align: center;
            padding: 20px 10px;
            color: var(--text-muted);
            font-size: 0.85rem;
        }

        @media (max-width: 500px) {
            .file-name {
                max-width: 140px;
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
        <div class="network-badge">
            <span class="dot"></span>
            <span id="network-ip">Sunucu Hazır</span>
        </div>
        <div id="qr-box" style="margin-top: 10px; display: flex; flex-direction: column; align-items: center; gap: 6px;">
            <img id="qr-img" style="width: 130px; height: 130px; border-radius: 8px; background: #ffffff; padding: 4px;" alt="QR Kod">
            <span style="font-size: 0.75rem; color: var(--text-muted);">Müşteri için QR Kodu Tara</span>
        </div>
    </header>

    <div class="card">
        <div class="dropzone" id="dropzone">
            <svg viewBox="0 0 24 24">
                <path d="M19.35 10.04C18.67 6.59 15.64 4 12 4 9.11 4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96zM14 13v4h-4v-4H7l5-5 5 5h-3z"/>
            </svg>
            <h3 style="font-size: 0.95rem; font-weight: 500; color: var(--text-muted);">Dosya Yükle</h3>
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
            <h2>Dosyalar</h2>
            <button class="refresh-btn" onclick="loadFiles()">↻ Yenile</button>
        </div>
        <div class="file-list" id="fileList">
            <div class="empty-state">Henüz dosya yok.</div>
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

    const currentUrl = 'http://' + window.location.host;
    document.getElementById('network-ip').textContent = currentUrl;
    document.getElementById('qr-img').src = 'https://api.qrserver.com/v1/create-qr-code/?size=150x150&data=' + encodeURIComponent(currentUrl);

    dropzone.addEventListener('click', () => fileInput.click());

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

            let lastUpdate = 0;
            xhr.upload.onprogress = (e) => {
                if (e.lengthComputable) {
                    const now = Date.now();
                    if (now - lastUpdate > 100 || e.loaded === e.total) {
                        lastUpdate = now;
                        const percent = Math.round((e.loaded / e.total) * 100);
                        progressBar.style.width = percent + '%';
                        progressPercent.textContent = percent + '%';
                        progressFile.textContent = `[${index}/${total}] ${file.name}`;
                    }
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
                fileList.innerHTML = '<div class="empty-state">Henüz dosya yok.</div>';
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
            console.error('Hata:', err);
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

    loadFiles();
</script>

</body>
</html>
"""

class FileTransferHandler(BaseHTTPRequestHandler):
    rbufsize = 256 * 1024
    wbufsize = 256 * 1024

    def setup(self):
        super().setup()
        try:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass

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

                # Parça parça gönder (256 KB tampon ile yüksek aktarım hızı)
                CHUNK_SIZE = 256 * 1024
                with open(filepath, "rb") as f:
                    while chunk := f.read(CHUNK_SIZE):
                        self.wfile.write(chunk)
                return
            else:
                self.send_error(404, "Dosya bulunamadi")
                return

        else:
            self.send_error(404, "Bulunamadi")

    def do_POST(self):
        # Mobil tarayıcılar (Chrome/Safari) büyük yüklemelerde Expect: 100-continue gönderir
        if self.headers.get("Expect", "").lower() == "100-continue":
            self.send_response_only(100)
            self.end_headers()

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

            # Doğrudan diske anlık akış (streaming)
            CHUNK_SIZE = 128 * 1024
            bytes_left = content_length
            with open(target_path, "wb") as f:
                while bytes_left > 0:
                    read_chunk = min(bytes_left, CHUNK_SIZE)
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
    httpd = ThreadingHTTPServer(server_address, FileTransferHandler)
    
    # Soket tampon boyutunu büyüt (daha yüksek Wi-Fi aktarım hızı için)
    try:
        httpd.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        httpd.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
        httpd.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024 * 1024)
    except Exception:
        pass

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
