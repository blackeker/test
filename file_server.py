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

# Klasör yolu komut satırından girildiyse (veya kısayollar: /sdcard, download, dcim vb.) kullan
if len(sys.argv) > 1 and sys.argv[1]:
    target = sys.argv[1].strip()
    if target.lower() in ["/sdcard", "sdcard", "storage"]:
        target = "/storage/emulated/0"
    elif target.lower() in ["download", "downloads", "/sdcard/download"]:
        target = "/storage/emulated/0/Download"
    elif target.lower() in ["dcim", "camera", "photos"]:
        target = "/storage/emulated/0/DCIM"
    SHARE_DIR = os.path.abspath(target)
else:
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
            max-width: 680px;
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
            padding: 20px 16px;
            text-align: center;
            cursor: pointer;
            transition: border-color 0.15s;
        }

        .dropzone:hover, .dropzone.dragover {
            border-color: var(--accent);
        }

        .dropzone svg {
            width: 36px;
            height: 36px;
            fill: var(--text-muted);
            margin-bottom: 6px;
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
            margin-top: 8px;
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

        .nav-bar {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 12px;
            padding: 8px 12px;
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 6px;
            font-size: 0.85rem;
            color: var(--text-muted);
            overflow-x: auto;
        }

        .back-btn {
            background: var(--border);
            color: var(--text);
            border: none;
            padding: 4px 10px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.8rem;
            font-weight: 500;
            display: inline-flex;
            align-items: center;
            gap: 4px;
            white-space: nowrap;
        }

        .back-btn:hover {
            background: #374151;
        }

        .path-text {
            color: var(--text);
            font-weight: 500;
            word-break: break-all;
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
            gap: 12px;
        }

        .folder-item {
            cursor: pointer;
            transition: background 0.15s;
        }

        .folder-item:hover {
            background: #171a23;
            border-color: var(--accent);
        }

        .file-info {
            display: flex;
            align-items: center;
            gap: 12px;
            flex: 1;
            min-width: 0;
        }

        .file-icon {
            font-size: 1.4rem;
            line-height: 1;
            flex-shrink: 0;
        }

        .media-thumb {
            width: 52px;
            height: 52px;
            object-fit: cover;
            border-radius: 6px;
            border: 1px solid var(--border);
            flex-shrink: 0;
            cursor: pointer;
            background: #000;
        }

        .file-details {
            display: flex;
            flex-direction: column;
            flex: 1;
            min-width: 0;
        }

        .file-name {
            font-size: 0.9rem;
            font-weight: 500;
            color: var(--text);
            word-break: break-word;
            white-space: normal;
            line-height: 1.35;
        }

        .file-meta {
            font-size: 0.75rem;
            color: var(--text-muted);
            margin-top: 3px;
        }

        .file-actions {
            display: flex;
            align-items: center;
            gap: 6px;
            flex-shrink: 0;
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

        /* Lightbox Modal */
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.88);
            justify-content: center;
            align-items: center;
            padding: 16px;
        }

        .modal-content {
            max-width: 95%;
            max-height: 90vh;
            border-radius: 8px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
        }

        .modal-close {
            position: absolute;
            top: 16px;
            right: 20px;
            font-size: 2rem;
            color: #fff;
            cursor: pointer;
            user-select: none;
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
            <div id="qrcode" style="width: 130px; height: 130px; border-radius: 8px; background: #ffffff; padding: 6px; display: flex; justify-content: center; align-items: center;"></div>
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
            <button class="refresh-btn" onclick="loadFiles(currentPath)">↻ Yenile</button>
        </div>
        <div class="nav-bar" id="navBar">
            <span class="path-text" id="pathText">📁 /</span>
        </div>
        <div class="file-list" id="fileList">
            <div class="empty-state">Henüz dosya yok.</div>
        </div>
    </div>
</div>

<div class="modal" id="mediaModal" onclick="closeModal()">
    <span class="modal-close" onclick="closeModal()">&times;</span>
    <div id="modalBody" onclick="event.stopPropagation()"></div>
</div>

<script>
    /* Standalone 100% Offline QR Code Generator */
    var QRCode;!function(){function a(a,b){this._el=a,this._htOption=b}function b(a,b){this.mode=c.MODE_8BIT_BYTE,this.data=a,this.parsedData=[];for(var d=0,e=a.length;e>d;d++){var f=[],g=a.charCodeAt(d);g>65536?(f[0]=240|(1835008&g)>>>18,f[1]=128|(258048&g)>>>12,f[2]=128|(4032&g)>>>6,f[3]=128|63&g):g>2048?(f[0]=224|(61440&g)>>>12,f[1]=128|(4032&g)>>>6,f[2]=128|63&g):g>128?(f[0]=192|(1984&g)>>>6,f[1]=128|63&g):f[0]=g,this.parsedData=this.parsedData.concat(f)}this.parsedData.length!=this.data.length&&(this.parsedData.unshift(191),this.parsedData.unshift(187),this.parsedData.unshift(239))}var c=function(a,b){this.typeNumber=a,this.errorCorrectLevel=b,this.modules=null,this.moduleCount=0,this.dataCache=null,this.dataList=[]};c.prototype={addData:function(a){var c=new b(a);this.dataList.push(c),this.dataCache=null},isDark:function(a,b){if(0>a||this.moduleCount<=a||0>b||this.moduleCount<=b)throw new Error(a+","+b);return this.modules[a][b]},getModuleCount:function(){return this.moduleCount},make:function(){this.makeImpl(!1,this.getBestMaskPattern())},makeImpl:function(a,b){this.moduleCount=4*this.typeNumber+17,this.modules=new Array(this.moduleCount);for(var c=0;c<this.moduleCount;c++){this.modules[c]=new Array(this.moduleCount);for(var d=0;d<this.moduleCount;d++)this.modules[c][d]=null}this.setupPositionProbePattern(0,0),this.setupPositionProbePattern(this.moduleCount-7,0),this.setupPositionProbePattern(0,this.moduleCount-7),this.setupPositionAdjustPattern(),this.setupTimingPattern(),this.setupTypeInfo(a,b),this.typeNumber>=7&&this.setupTypeNumber(a),null==this.dataCache&&(this.dataCache=c.createData(this.typeNumber,this.errorCorrectLevel,this.dataList)),this.mapData(this.dataCache,b)},setupPositionProbePattern:function(a,b){for(var c=-1;7>=c;c++)if(!(-1>=a+c||this.moduleCount<=a+c))for(var d=-1;7>=d;d++)-1>=b+d||this.moduleCount<=b+d||(this.modules[a+c][b+d]=c>=0&&6>=c&&(0==d||6==d)||d>=0&&6>=d&&(0==c||6==c)||c>=2&&4>=c&&d>=2&&4>=d?!0:!1)},getBestMaskPattern:function(){for(var a=0,b=0,c=0;8>c;c++){this.makeImpl(!0,c);var d=f.getLostPoint(this);(0==c||b>d)&&(b=d,a=c)}return a},setupTimingPattern:function(){for(var a=8;a<this.moduleCount-8;a++)null==this.modules[a][6]&&(this.modules[a][6]=a%2==0);for(var b=8;b<this.moduleCount-8;b++)null==this.modules[6][b]&&(this.modules[6][b]=b%2==0)},setupPositionAdjustPattern:function(){for(var a=f.getPatternPosition(this.typeNumber),b=0;b<a.length;b++)for(var c=0;c<a.length;c++){var d=a[b],e=a[c];if(null==this.modules[d][e])for(var g=-2;2>=g;g++)for(var h=-2;2>=h;h++)this.modules[d+g][e+h]=-2==g||2==g||-2==h||2==h||0==g&&0==h?!0:!1}},setupTypeNumber:function(a){for(var b=f.getBCHTypeNumber(this.typeNumber),c=0;18>c;c++){var d=!a&&1==(1&b>>c);this.modules[Math.floor(c/3)][c%3+this.moduleCount-8-3]=d}for(var c=0;18>c;c++){var d=!a&&1==(1&b>>c);this.modules[c%3+this.moduleCount-8-3][Math.floor(c/3)]=d}},setupTypeInfo:function(a,b){for(var c=this.errorCorrectLevel<<3|b,d=f.getBCHTypeInfo(c),e=0;15>e;e++){var g=!a&&1==(1&d>>e);8>e?this.modules[8][this.moduleCount-1-e]=g:this.modules[8][15-e-1+1]=g}for(var e=0;15>e;e++){var g=!a&&1==(1&d>>e);8>e?this.modules[this.moduleCount-1-e][8]=g:this.modules[15-e-1][8]=g}this.modules[this.moduleCount-8][8]=!a},mapData:function(a,b){for(var c=-1,d=this.moduleCount-1,e=7,g=0,h=this.moduleCount-1;h>0;h-=2){6==h&&h--;for(;;){for(var i=0;2>i;i++)if(null==this.modules[d][h-i]){var j=!1;g<a.length&&(j=1==(1&a[g]>>>e)),f.getMask(b,d,h-i)&&(j=!j),this.modules[d][h-i]=j,e--,-1==e&&(g++,e=7)}if(d+=c,0>d||this.moduleCount<=d){d-=c,c=-c;break}}}}},c.PAD0=236,c.PAD1=17,c.createData=function(a,b,d){for(var e=g.getRSBlocks(a,b),h=new h,i=0;i<d.length;i++){var j=d[i];h.put(j.mode,4),h.put(j.getLength(),f.getLengthInBits(j.mode,a)),j.write(h)}for(var k=0,i=0;i<e.length;i++)k+=e[i].dataCount;if(h.getLengthInBits()>8*k)throw new Error("code length overflow. ("+h.getLengthInBits()+">"+8*k+")");for(h.getLengthInBits()+4<=8*k&&h.put(0,4);h.getLengthInBits()%8!=0;)h.putBit(!1);for(;;){if(h.getLengthInBits()>=8*k)break;if(h.put(c.PAD0,8),h.getLengthInBits()>=8*k)break;h.put(c.PAD1,8)}return c.createBytes(h,e)},c.createBytes=function(a,b){for(var c=0,d=0,e=0,g=new Array(b.length),h=new Array(b.length),i=0;i<b.length;i++){var j=b[i].dataCount,k=b[i].totalCount-j;d=Math.max(d,j),e=Math.max(e,k),g[i]=new Array(j);for(var l=0;l<g[i].length;l++)g[i][l]=255&a.buffer[l+c];c+=j;var m=f.getErrorCorrectPolynomial(k),n=new i(g[i],m.getLength()-1),o=n.mod(m);h[i]=new Array(m.getLength()-1);for(var l=0;l<h[i].length;l++){var p=l+o.getLength()-h[i].length;h[i][l]=p>=0?o.get(p):0}}for(var q=0,l=0;l<b.length;l++)q+=b[l].totalCount;for(var r=new Array(q),s=0,l=0;d>l;l++)for(var i=0;i<b.length;i++)l<g[i].length&&(r[s++]=g[i][l]);for(var l=0;e>l;l++)for(var i=0;i<b.length;i++)l<h[i].length&&(r[s++]=h[i][l]);return r};for(var d={MODE_NUMBER:1,MODE_ALPHA_NUM:2,MODE_8BIT_BYTE:4,MODE_KANJI:8},e={L:1,M:0,Q:3,H:2},f={PATTERN_POSITION_TABLE:[[],[6,18],[6,22],[6,26],[6,30],[6,34],[6,22,38],[6,24,42],[6,26,46],[6,28,50],[6,30,54],[6,32,58],[6,34,62],[6,26,46,66],[6,28,48,68],[6,30,50,70],[6,30,52,74],[6,30,54,78],[6,32,56,82],[6,34,58,86],[6,28,50,72,94],[6,26,50,74,98],[6,30,54,78,102],[6,28,54,80,106],[6,32,58,84,110],[6,30,58,86,114],[6,34,62,90,118],[6,26,50,74,98,122],[6,30,54,78,102,126],[6,26,52,78,104,130],[6,30,56,82,108,134],[6,34,60,86,112,138],[6,30,58,86,114,142],[6,34,62,90,118,146],[6,30,54,78,102,126,150],[6,24,50,76,102,128,154],[6,28,54,80,106,132,158],[6,32,58,84,110,136,162],[6,26,54,82,110,138,166],[6,30,58,86,114,142,170]],G15:1335,G18:7973,G15_MASK:21522,getBCHTypeInfo:function(a){for(var b=a<<10;f.getBCHDigit(b)-f.getBCHDigit(f.G15)>=0;)b^=f.G15<<f.getBCHDigit(b)-f.getBCHDigit(f.G15);return(a<<10|b)^f.G15_MASK},getBCHTypeNumber:function(a){for(var b=a<<12;f.getBCHDigit(b)-f.getBCHDigit(f.G18)>=0;)b^=f.G18<<f.getBCHDigit(b)-f.getBCHDigit(f.G18);return a<<12|b},getBCHDigit:function(a){for(var b=0;0!=a;)b++,a>>>=1;return b},getPatternPosition:function(a){return f.PATTERN_POSITION_TABLE[a-1]},getMask:function(a,b,c){switch(a){case 0:return(b+c)%2==0;case 1:return b%2==0;case 2:return c%3==0;case 3:return(b+c)%3==0;case 4:return(Math.floor(b/2)+Math.floor(c/3))%2==0;case 5:return b*c%2+b*c%3==0;case 6:return(b*c%2+b*c%3)%2==0;case 7:return(b*c%3+(b+c)%2)%2==0;default:throw new Error("bad maskMode:"+a)}},getErrorCorrectPolynomial:function(a){for(var b=new i([1],0),c=0;a>c;c++)b=b.multiply(new i([1,g.gexp(c)],0));return b},getLengthInBits:function(a,b){if(b>=1&&10>b)switch(a){case d.MODE_NUMBER:return 10;case d.MODE_ALPHA_NUM:return 9;case d.MODE_8BIT_BYTE:return 8;case d.MODE_KANJI:return 8;default:throw new Error("mode:"+a)}else if(27>b)switch(a){case d.MODE_NUMBER:return 12;case d.MODE_ALPHA_NUM:return 11;case d.MODE_8BIT_BYTE:return 16;case d.MODE_KANJI:return 16;default:throw new Error("mode:"+a)}else{if(!(41>b))throw new Error("type:"+b);switch(a){case d.MODE_NUMBER:return 14;case d.MODE_ALPHA_NUM:return 13;case d.MODE_8BIT_BYTE:return 16;case d.MODE_KANJI:return 12;default:throw new Error("mode:"+a)}}},getLostPoint:function(a){for(var b=a.getModuleCount(),c=0,d=0;b>d;d++)for(var e=0;b>e;e++){for(var f=0,g=a.isDark(d,e),h=-1;1>=h;h++)if(!(0>d+h||d+h>=b))for(var i=-1;1>=i;i++)0>e+i||e+i>=b||(0!=h||0!=i)&&g==a.isDark(d+h,e+i)&&f++;f>5&&(c+=3+f-5)}for(var d=0;b-1>d;d++)for(var e=0;b-1>e;e++){var j=0;a.isDark(d,e)&&j++,a.isDark(d+1,e)&&j++,a.isDark(d,e+1)&&j++,a.isDark(d+1,e+1)&&j++,(0==j||4==j)&&(c+=3)}for(var d=0;b>d;d++)for(var e=0;b-6>e;e++)a.isDark(d,e)&&!a.isDark(d,e+1)&&a.isDark(d,e+2)&&a.isDark(d,e+3)&&a.isDark(d,e+4)&&!a.isDark(d,e+5)&&a.isDark(d,e+6)&&(c+=40);for(var e=0;b>e;e++)for(var d=0;b-6>d;d++)a.isDark(d,e)&&!a.isDark(d+1,e)&&a.isDark(d+2,e)&&a.isDark(d+3,e)&&a.isDark(d+4,e)&&!a.isDark(d+5,e)&&a.isDark(d+6,e)&&(c+=40);for(var k=0,e=0;b>e;e++)for(var d=0;b>d;d++)a.isDark(d,e)&&k++;var l=Math.abs(100*k/(b*b)-50)/5;return c+=10*l}},g={RS_BLOCK_TABLE:[[1,26,19],[1,26,16],[1,26,13],[1,26,9],[1,44,34],[1,44,28],[1,44,22],[1,44,16],[1,70,55],[1,70,44],[2,35,17],[2,35,13],[1,100,80],[2,50,32],[2,50,24],[4,25,9],[1,134,108],[2,67,43],[2,33,15,2,34,16],[2,33,11,2,34,12],[2,86,68],[4,43,27],[4,43,19],[4,43,15],[2,98,78],[4,49,31],[2,32,14,4,33,15],[4,39,13,1,40,14],[2,121,97],[2,60,38,2,61,39],[4,40,18,2,41,19],[4,40,14,2,41,15],[2,146,116],[3,58,36,2,59,37],[4,36,16,4,37,17],[4,36,12,4,37,13],[2,86,68,2,87,69],[4,69,43,1,70,44],[6,43,19,2,44,20],[6,43,15,2,44,16]],getRSBlocks:function(a,b){var c=g.getRsBlockTable(a,b);if(void 0===c)throw new Error("bad rs block @ typeNumber:"+a+"/errorCorrectLevel:"+b);for(var d=c.length/3,e=[],f=0;d>f;f++)for(var h=c[3*f+0],i=c[3*f+1],j=c[3*f+2],k=0;h>k;k++)e.push(new g(i,j));return e},getRsBlockTable:function(a,b){switch(b){case e.L:return g.RS_BLOCK_TABLE[4*(a-1)+0];case e.M:return g.RS_BLOCK_TABLE[4*(a-1)+1];case e.Q:return g.RS_BLOCK_TABLE[4*(a-1)+2];case e.H:return g.RS_BLOCK_TABLE[4*(a-1)+3];default:return void 0}},glog:function(a){if(1>a)throw new Error("glog("+a+")");return g.LOG_TABLE[a]},gexp:function(a){for(;0>a;)a+=255;for(;a>=256;)a-=255;return g.EXP_TABLE[a]},EXP_TABLE:new Array(256),LOG_TABLE:new Array(256)},h=0;8>h;h++)g.EXP_TABLE[h]=1<<h;for(var h=8;256>h;h++)g.EXP_TABLE[h]=g.EXP_TABLE[h-4]^g.EXP_TABLE[h-5]^g.EXP_TABLE[h-8]^g.EXP_TABLE[h-1];for(var h=0;255>h;h++)g.LOG_TABLE[g.EXP_TABLE[h]]=h;function i(a,b){if(void 0===a.length)throw new Error(a.length+"/"+b);for(var c=0;c<a.length&&0==a[c];)c++;this.num=new Array(a.length-c+b);for(var d=0;d<a.length-c;d++)this.num[d]=a[d]}i.prototype={get:function(a){return this.num[a]},getLength:function(){return this.num.length},multiply:function(a){for(var b=new Array(this.getLength()+a.getLength()-1),c=0;c<this.getLength();c++)for(var d=0;d<a.getLength();d++)b[c+d]^=g.gexp(g.glog(this.get(c))+g.glog(a.get(d)));return new i(b,0)},mod:function(a){if(this.getLength()-a.getLength()<0)return this;for(var b=g.glog(this.get(0))-g.glog(a.get(0)),c=new Array(this.getLength()),d=0;d<this.getLength();d++)c[d]=this.get(d);for(var d=0;d<a.getLength();d++)c[d]^=g.gexp(g.glog(a.get(d))+b);return new i(c,0).mod(a)}};function j(a,b,c){this._el=a,this._htOption=b,this._htOption.correctLevel=c||e.M}j.prototype.draw=function(a){var b=this._htOption,c=this._el,d=a.getModuleCount(),e=Math.floor(b.width/d),f=Math.floor(b.height/d);c.innerHTML="";var g=document.createElement("canvas");g.width=b.width,g.height=b.height;var h=g.getContext("2d");h.fillStyle=b.colorLight,h.fillRect(0,0,b.width,b.height),h.fillStyle=b.colorDark;for(var i=0;d>i;i++)for(var j=0;d>j;j++)if(a.isDark(i,j)){var k=j*e,l=i*f;h.fillRect(k,l,e,f)}c.appendChild(g)},a.prototype.makeCode=function(a){this._oQRCode=new c(4,this._htOption.correctLevel),this._oQRCode.addData(a),this._oQRCode.make(),this._oDrawing=new j(this._el,this._htOption,this._htOption.correctLevel),this._oDrawing.draw(this._oQRCode)},QRCode=a}();

    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('fileInput');
    const progressBox = document.getElementById('progressBox');
    const progressBar = document.getElementById('progressBar');
    const progressFile = document.getElementById('progressFile');
    const progressPercent = document.getElementById('progressPercent');
    const fileList = document.getElementById('fileList');
    const navBar = document.getElementById('navBar');
    const mediaModal = document.getElementById('mediaModal');
    const modalBody = document.getElementById('modalBody');

    let currentPath = '';

    const currentUrl = 'http://' + window.location.host;
    document.getElementById('network-ip').textContent = currentUrl;
    
    // 100% Çevrimdışı QR Kod Üreteci
    try {
        new QRCode(document.getElementById('qrcode'), {
            text: currentUrl,
            width: 118,
            height: 118
        });
    } catch(e) { console.error(e); }

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
            loadFiles(currentPath);
            fileInput.value = '';
        }, 1000);
    }

    function uploadSingleFile(file, index, total) {
        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            const url = `/api/upload?path=${encodeURIComponent(currentPath)}&filename=${encodeURIComponent(file.name)}`;

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
        if (['mp4', 'mkv', 'mov', 'avi', 'webm'].includes(ext)) return '🎬';
        if (['mp3', 'wav', 'ogg', 'flac'].includes(ext)) return '🎵';
        if (['zip', 'rar', '7z', 'tar', 'gz'].includes(ext)) return '📦';
        if (['pdf', 'doc', 'docx', 'txt', 'md'].includes(ext)) return '📄';
        if (['apk'].includes(ext)) return '🤖';
        return '📄';
    }

    async function loadFiles(targetPath = '') {
        try {
            const res = await fetch(`/api/files?path=${encodeURIComponent(targetPath)}`);
            const data = await res.json();

            currentPath = data.current_path || '';
            const parentPath = data.parent_path !== null && data.parent_path !== undefined ? data.parent_path : null;

            // Navigasyon Çubuğu (Geri Butonu + Klasör Yolu)
            let navHtml = '';
            if (currentPath !== '') {
                navHtml += `<button class="back-btn" onclick="loadFiles('${encodeURIComponent(parentPath !== null ? parentPath : '')}')">⬅️ Geri</button> `;
            }
            navHtml += `<span class="path-text">📂 /${currentPath}</span>`;
            navBar.innerHTML = navHtml;

            const folders = data.folders || [];
            const files = data.files || [];

            if (folders.length === 0 && files.length === 0) {
                fileList.innerHTML = '<div class="empty-state">Bu klasör boş.</div>';
                return;
            }

            let html = '';

            // Klasörler
            folders.forEach(folder => {
                html += `
                    <div class="file-item folder-item" onclick="loadFiles('${encodeURIComponent(folder.path)}')">
                        <div class="file-info">
                            <span class="file-icon">📁</span>
                            <div class="file-details">
                                <span class="file-name">${folder.name}</span>
                                <span class="file-meta">Klasör</span>
                            </div>
                        </div>
                        <div class="file-actions">
                            <span style="color: var(--text-muted); font-size: 0.8rem;">Aç ➔</span>
                        </div>
                    </div>
                `;
            });

            // Dosyalar (Tam İsim + Resim/Video Önizleme)
            files.forEach(file => {
                let thumbHtml = `<span class="file-icon">${getFileIcon(file.name)}</span>`;
                if (file.is_img) {
                    thumbHtml = `<img src="/view/${encodeURIComponent(file.path)}" class="media-thumb" alt="Önizleme" onclick="openMediaModal('/view/${encodeURIComponent(file.path)}', 'image')">`;
                } else if (file.is_vid) {
                    thumbHtml = `<video src="/view/${encodeURIComponent(file.path)}#t=0.5" class="media-thumb" preload="metadata" muted onclick="openMediaModal('/view/${encodeURIComponent(file.path)}', 'video')"></video>`;
                }

                html += `
                    <div class="file-item">
                        <div class="file-info">
                            ${thumbHtml}
                            <div class="file-details">
                                <span class="file-name">${file.name}</span>
                                <span class="file-meta">${file.size} • ${file.mtime}</span>
                            </div>
                        </div>
                        <div class="file-actions">
                            <a href="/download/${encodeURIComponent(file.path)}" class="action-btn download-btn" download="${file.name}">
                                ⬇️ <span>İndir</span>
                            </a>
                            <button class="action-btn delete-btn" onclick="deleteFile('${encodeURIComponent(file.path)}')">
                                🗑️
                            </button>
                        </div>
                    </div>
                `;
            });

            fileList.innerHTML = html;
        } catch (err) {
            console.error('Hata:', err);
        }
    }

    async function deleteFile(encodedPath) {
        if (!confirm('Bu dosyayı silmek istediğinize emin misiniz?')) return;
        try {
            const res = await fetch('/api/delete?filename=' + encodedPath, { method: 'DELETE' });
            if (res.ok) {
                loadFiles(currentPath);
            } else {
                alert('Dosya silinemedi.');
            }
        } catch (err) {
            alert('Hata: ' + err);
        }
    }

    function openMediaModal(src, type) {
        if (type === 'image') {
            modalBody.innerHTML = `<img src="${src}" class="modal-content" alt="Önizleme">`;
        } else if (type === 'video') {
            modalBody.innerHTML = `<video src="${src}" class="modal-content" controls autoplay style="max-width: 95vw; max-height: 85vh;"></video>`;
        }
        mediaModal.style.display = 'flex';
    }

    function closeModal() {
        mediaModal.style.display = 'none';
        modalBody.innerHTML = '';
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
            query = urllib.parse.parse_qs(parsed.query)
            subpath = query.get("path", [""])[0]

            target_dir = os.path.abspath(os.path.join(SHARE_DIR, subpath))
            if not target_dir.startswith(os.path.abspath(SHARE_DIR)) or not os.path.exists(target_dir):
                target_dir = os.path.abspath(SHARE_DIR)
                subpath = ""

            rel_current = os.path.relpath(target_dir, SHARE_DIR).replace("\\", "/")
            if rel_current == ".":
                rel_current = ""

            parent_path = os.path.dirname(rel_current).replace("\\", "/") if rel_current else None
            if parent_path == ".":
                parent_path = ""

            folders = []
            files_info = []

            if os.path.isdir(target_dir):
                for entry in sorted(os.listdir(target_dir)):
                    if entry.startswith("."):
                        continue
                    entry_path = os.path.join(target_dir, entry)
                    rel_item_path = (rel_current + "/" + entry) if rel_current else entry

                    if os.path.isdir(entry_path):
                        folders.append({
                            "name": entry,
                            "type": "dir",
                            "path": rel_item_path
                        })
                    elif os.path.isfile(entry_path):
                        try:
                            stat = os.stat(entry_path)
                            ext = entry.split(".")[-1].lower() if "." in entry else ""
                            is_img = ext in ["jpg", "jpeg", "png", "gif", "webp", "svg"]
                            is_vid = ext in ["mp4", "webm", "mov", "mkv", "avi"]

                            files_info.append({
                                "name": entry,
                                "type": "file",
                                "size": format_size(stat.st_size),
                                "bytes": stat.st_size,
                                "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%d.%m.%Y %H:%M"),
                                "path": rel_item_path,
                                "is_img": is_img,
                                "is_vid": is_vid
                            })
                        except Exception:
                            pass

            files_info.sort(key=lambda x: x["mtime"], reverse=True)

            res_payload = {
                "current_path": rel_current,
                "parent_path": parent_path,
                "folders": folders,
                "files": files_info
            }

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            content = json.dumps(res_payload).encode("utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        elif path.startswith("/view/"):
            raw_filename = urllib.parse.unquote(path[len("/view/"):])
            filepath = os.path.abspath(os.path.join(SHARE_DIR, raw_filename))

            if os.path.isfile(filepath) and filepath.startswith(os.path.abspath(SHARE_DIR)):
                file_size = os.path.getsize(filepath)
                self.send_response(200)
                ext = filepath.split(".")[-1].lower() if "." in filepath else ""
                content_type = "application/octet-stream"
                if ext in ["jpg", "jpeg"]: content_type = "image/jpeg"
                elif ext == "png": content_type = "image/png"
                elif ext == "gif": content_type = "image/gif"
                elif ext == "webp": content_type = "image/webp"
                elif ext == "svg": content_type = "image/svg+xml"
                elif ext == "mp4": content_type = "video/mp4"
                elif ext == "webm": content_type = "video/webm"
                elif ext == "mov": content_type = "video/quicktime"

                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(file_size))
                self.end_headers()

                CHUNK_SIZE = 256 * 1024
                with open(filepath, "rb") as f:
                    while chunk := f.read(CHUNK_SIZE):
                        self.wfile.write(chunk)
                return
            else:
                self.send_error(404, "Bulunamadi")
                return

        elif path.startswith("/download/"):
            raw_filename = urllib.parse.unquote(path[len("/download/"):])
            filepath = os.path.abspath(os.path.join(SHARE_DIR, raw_filename))

            if os.path.isfile(filepath) and filepath.startswith(os.path.abspath(SHARE_DIR)):
                file_size = os.path.getsize(filepath)
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                filename_only = os.path.basename(filepath)
                filename_encoded = urllib.parse.quote(filename_only)
                self.send_header("Content-Disposition", f'attachment; filename="{filename_encoded}"; filename*=UTF-8\'\'{filename_encoded}')
                self.send_header("Content-Length", str(file_size))
                self.end_headers()

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
        if self.headers.get("Expect", "").lower() == "100-continue":
            self.send_response_only(100)
            self.end_headers()

        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/upload":
            query = urllib.parse.parse_qs(parsed.query)
            subpath = query.get("path", [""])[0]
            filename = query.get("filename", ["uploaded_file"])[0]
            filename = os.path.basename(urllib.parse.unquote(filename))

            target_dir = os.path.abspath(os.path.join(SHARE_DIR, subpath))
            if not target_dir.startswith(os.path.abspath(SHARE_DIR)) or not os.path.exists(target_dir):
                target_dir = os.path.abspath(SHARE_DIR)

            if not filename:
                filename = f"file_{int(datetime.now().timestamp())}"

            target_path = os.path.join(target_dir, filename)

            base, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(target_path):
                target_path = os.path.join(target_dir, f"{base}_{counter}{ext}")
                counter += 1

            content_length = int(self.headers.get("Content-Length", 0))

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
            raw_filename = query.get("filename", [""])[0]
            raw_filename = urllib.parse.unquote(raw_filename)
            target_path = os.path.abspath(os.path.join(SHARE_DIR, raw_filename))

            if os.path.exists(target_path) and target_path.startswith(os.path.abspath(SHARE_DIR)):
                try:
                    if os.path.isdir(target_path):
                        import shutil
                        shutil.rmtree(target_path)
                    else:
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
