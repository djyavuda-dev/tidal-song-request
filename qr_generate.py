"""
Generates a QR code pointing at your deployed request page.
Usage: python qr_generate.py https://your-domain.com
"""
import sys
import qrcode

if len(sys.argv) != 2:
    print("Kullanım: python qr_generate.py https://your-domain.com")
    sys.exit(1)

url = sys.argv[1]
img = qrcode.make(url)
img.save("tidal_song_request_qr.png")
print(f"QR kod kaydedildi: tidal_song_request_qr.png -> {url}")
