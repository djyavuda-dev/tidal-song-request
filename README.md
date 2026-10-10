# Tidal Şarkı İstek Kiosku

Spotify sürümüyle aynı mantık: misafir QR'ı okutur, şarkı arar, adını yazıp "İste" der;
şarkı sadece TARGET_PLAYLIST_ID'ye eklenir. Misafir Tidal'a giriş yapmaz.
`/admin?key=ADMIN_KEY` sayfasında kim ne istedi görürsün.

Render ortam değişkenleri: TIDAL_CLIENT_ID, TIDAL_CLIENT_SECRET, TIDAL_REDIRECT_URI,
TARGET_PLAYLIST_ID, COUNTRY_CODE, ADMIN_KEY. Deploy sonrası `/login` yapınca çıkan
TIDAL_REFRESH_TOKEN'ı da ekle.

Build: pip install -r requirements.txt   Start: gunicorn app:app
Playlist ID: tidal.com/playlist/<BU-KISIM>  (playlist'i kendi hesabında oluşturmuş olmalısın)
