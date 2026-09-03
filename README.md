# ⚡ Cihazlar Arası Doğrudan Wi-Fi Dosya Aktarım Sistemi (Modemsiz)

Bu sistem, harici bir ev/ofis modemi **olmadan**, cihazların kendi Wi-Fi donanımını (Hotspot / Mobil Etkin Nokta) kullanarak aralarında **yüksek hızda ve internetsiz** dosya aktarımı yapmasını sağlar.

---

## 🎯 Çalışma Mantığı (Modemsiz Doğrudan Bağlantı)

İki seçenekten birini kullanabilirsiniz:

### Seçenek A: Wi-Fi'yi Bilgisayar Paylaşır (En Çok Tercih Edilen)
1. **Bilgisayardan Wi-Fi Açın:**
   - Windows bildirim alanındaki Wi-Fi simgesine tıklayın ve **"Mobil Etkin Nokta"** (Mobile Hotspot) özelliğini açın.
   - *(İsmini ve şifresini Ayarlar -> Ağ ve İnternet -> Mobil Etkin Nokta altından görebilirsiniz).*
2. **Diğer Cihazları Bağlayın:**
   - Tabletinizi, telefonunuzu veya başka bilgisayarları bu Wi-Fi ağına bağlayın.
3. **Sunucuyu Başlatın:**
   - Bilgisayarda `start_server.bat` dosyasına çift tıklayın.
   - Ekranda IP adresi belirecektir (Windows Hotspot için genelde: `http://192.168.137.1:8000`).
4. **Bağlantı:**
   - **Bilgisayarınızdan:** `http://localhost:8000`
   - **Tablet / Diğer cihazlardan:** `http://192.168.137.1:8000`
   - *Not:* Tablet bağlanamazsa klasördeki `guvenlik_duvari_izin_ver.bat` dosyasına sağ tıklayıp "Yönetici olarak çalıştır" deyin.

---

### Seçenek B: Wi-Fi'yi Tablet (veya Telefon) Paylaşır
1. **Tabletten Hotspot Açın:**
   - Tabletin ayarlarından **"Kişisel Erişim Noktası / Taşınabilir Hotspot"**u açın.
   - *(Hücresel veriniz kapalı olsa bile Hotspot yerel Wi-Fi yayını yapar, veri kotanız gitmez).*
2. **Bilgisayarı ve Diğer Cihazları Bağlayın:**
   - Bilgisayarınızın Wi-Fi'sini açıp tabletin oluşturduğu ağa bağlanın.
3. **Sunucuyu Başlatın:**
   - **Eğer sunucu Bilgisayardaysa:** `start_server.bat` çalıştırın. Ekranda çıkan IP'ye (örn. `http://192.168.43.x:8000`) tabletten girin.
   - **Eğer sunucu Tabletteyse (Termux):** Termux'ta `python file_server.py` çalıştırın. Bilgisayardan `http://192.168.43.1:8000` adresine girin.

---

## 📂 Dosyalar Nereye Kaydedilir?
- Yüklenen tüm dosyalar projenin içindeki **`shared_files/`** klasörüne kaydedilir.
- Web sayfasından istediğiniz zaman yeni dosya atabilir veya var olan dosyaları tek tıkla cihazınıza indirebilirsiniz.
