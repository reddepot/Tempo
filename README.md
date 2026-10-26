# Tempo

Notification quotidienne de la couleur **Tempo EDF** (bleu / blanc / rouge) sur téléphone, via **ntfy**, **Telegram** ou **Signal**. Conçu pour tourner en conteneur sur un NAS Synology (testé pour DS224+, Container Manager).

Exemple de message :

```
🔴 Tempo demain : jour ROUGE
Mardi 27/01 (de 6h à 6h le lendemain).
Heures pleines 6h-22h très chères : décaler lave-linge, chauffe-eau, recharge VE.
Restants saison : 14 rouges, 30 blancs.
```

## Fonctionnement

- La couleur de J+1 est publiée par RTE/EDF vers 10h40. Le script vérifie de `CHECK_FROM` à `CHECK_UNTIL` toutes les `CHECK_EVERY_MIN` minutes, et envoie **une seule** notification dès que la couleur est connue.
- Optionnel : rappel le matin (`MORNING_AT`) de la couleur du jour.
- Optionnel : `NOTIFY_ONLY=BLANC,ROUGE` pour n'être prévenu que des jours chers.
- Sources : [api-couleur-tempo.fr](https://www.api-couleur-tempo.fr) (publique, sans clé), puis API EDF en secours.
- Python standard, aucune dépendance. État conservé dans `data/state.json` (pas de doublon après redémarrage).

## Installation sur Synology (DS224+)

1. Installer **Container Manager** (Centre de paquets).
2. Copier ce dépôt dans `/volume1/docker/tempo` (File Station, ou `git clone` en SSH).
3. Copier `.env.example` en `.env` et renseigner au moins un canal (voir ci-dessous).
4. Container Manager → **Projet** → **Créer** → chemin `/volume1/docker/tempo` → utiliser le `docker-compose.yml` existant → Suivant → Terminé.

En SSH, équivalent :

```sh
cd /volume1/docker/tempo
cp .env.example .env && vi .env
sudo docker compose up -d --build
sudo docker compose run --rm tempo python tempo.py test   # notification de test
sudo docker logs -f tempo
```

## Canaux

### ntfy (le plus simple, recommandé)
1. Installer l'appli **ntfy** (Android / iOS).
2. S'abonner à un sujet au nom long et imprévisible (ex. `tempo-radu-8f3k2q`) — sur ntfy.sh, les sujets sont publics pour qui connaît le nom.
3. Mettre ce nom dans `NTFY_TOPIC`.

Priorité : bleu = normale, blanc = haute, rouge = urgente (sonnerie distincte possible dans l'appli).

### Telegram
1. Créer un bot avec `@BotFather` → `TELEGRAM_TOKEN`.
2. Envoyer un message au bot, puis récupérer son identifiant via `@userinfobot` → `TELEGRAM_CHAT_ID`.

### Signal
Signal n'a pas d'API officielle ; on passe par [signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api) :
1. Décommenter le service `signal-api` dans `docker-compose.yml` et relancer le projet.
2. Lier comme appareil secondaire : ouvrir `http://IP_DU_NAS:8080/v1/qrcodelink?device_name=nas` et scanner le QR code depuis Signal → Réglages → Appareils liés.
3. Renseigner `SIGNAL_API_URL=http://signal-api:8080`, `SIGNAL_NUMBER` (votre numéro) et `SIGNAL_RECIPIENTS` (par défaut : vous-même, le message arrive dans « Note à soi-même »).

Plusieurs canaux peuvent être actifs en même temps.

## Commandes

```
python tempo.py run        # démon (par défaut dans le conteneur)
python tempo.py today      # affiche la couleur du jour
python tempo.py tomorrow   # affiche la couleur de demain
python tempo.py test       # envoie une notification de test
```
