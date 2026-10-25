# Akciófigyelő és Intelligens Bevásárlólista Optimalizáló

Magyarországi áruházláncok (**Aldi, Lidl, Spar, Penny, Tesco, Auchan, dm, Rossmann, Müller**) napi árainak és akcióinak automatikus gyűjtése, valamint intelligens bevásárlólista optimalizáló motor.

## 🚀 Főbb funkciók
- **Automatikus napi árszinkronizáció:** A hivatalos GVH Árfigyelő 161 termékkategóriájának összesített adatbázisából minden reggel (és manuálisan gombnyomásra is) frissülnek az árak.
- **Bevásárlólista összehasonlítás:** Tetszőleges szöveges lista (pl. "1 l tej, 10 db tojas, trappista sajt") alapján kiszámolja:
  - Hol a legolcsóbb a kosár egyetlen boltban megvásárolva?
  - Melyik boltban mennyi tétel található meg?
  - Mennyit lehet spórolni egy optimális, multi-boltos vásárlással?
- **Élő termék- és akciókereső:** Bármely termékre gyorskeresés a napi kedvezményes és normál árakkal.
- **Traefik & SSL integráció:** Elérhető a https://akciofigyelo.localhost címen.

## 🛠 Telepítés és futtatás
```bash
docker compose up -d --build
```
Logok megtekintése:
```bash
docker compose logs -f akciofigyelo
```
Elérhetőség a böngészőből:
- `https://akciofigyelo.localhost` vagy `http://localhost:8097`
