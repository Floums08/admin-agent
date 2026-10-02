# Déployer et maintenir une instance isolée

Procédure destinée à la personne qui administre le serveur. Le chemin de référence est `/opt/admin-agent` sur un serveur Linux avec systemd. **Une VM et une adresse publique par client** est l'architecture initiale ; Caddy écoute les ports 80/443. Ne pas lancer plusieurs stacks clientes sur la même adresse en changeant seulement le nom Compose : les ports entreraient en conflit et cela modifierait le modèle d'isolation.

Les commandes suivantes sont à exécuter dans un terminal autorisé du serveur choisi. Elles n'ont pas provisionné d'hébergement dans cette livraison. `acme` et `admin.example.com` sont des exemples à remplacer. Aucun client réel ne doit être lancé avant la [recette](04-RECETTE-CLIENT.md) et la [décision finale](06-GO-NO-GO.md).

## 1. Préparer l'hébergement

Choisir un hébergeur et une région conformes au dossier de traitement. Prévoir chiffrement du disque, sauvegarde distante indépendante, administrateurs nominatifs avec MFA et accès SSH par clés. Un utilisateur ayant accès à Docker doit être considéré comme administrateur du serveur. Restreindre SSH aux administrateurs et au réseau convenu. Seuls HTTPS, HTTP nécessaire au certificat/redirection et les ports d'administration explicitement retenus doivent être exposés ; jamais le port 8765.

Installer une version maintenue de Docker Engine et Compose, Git, Python 3.11+ avec venv, restic et les utilitaires Linux `findmnt`/`flock`. Synchroniser l'horloge par NTP : les codes TOTP dépendent de l'heure. Définir une supervision de l'espace disque, du service, des échecs de sauvegarde et du certificat. Les ressources du conteneur sont plafonnées dans Compose ; dimensionner la VM après mesure, sans promesse de débit déduite de ces plafonds.

Créer le DNS du domaine vers la VM ; vérifier les enregistrements IPv4 et IPv6 présents. Un enregistrement IPv6 erroné peut empêcher l'accès ou l'obtention du certificat. Caddy gère HTTPS pour le domaine configuré, mais il faut vérifier le certificat réel après lancement.

## 2. Installer une version revue

Dans un répertoire de travail autorisé :

```bash
sudo git clone https://github.com/Floums08/admin-agent.git /opt/admin-agent
cd /opt/admin-agent
sudo git switch --detach SHA_DU_COMMIT_VALIDE
sudo python3 -m venv .venv
sudo .venv/bin/python -m pip install -r requirements-production.txt
```

Remplacer `SHA_DU_COMMIT_VALIDE` par le hash complet d'une version dont la CI et le rapport QA ont été examinés. Ne pas garder `main` en mise à jour automatique. Le venv sert aux opérations sur l'hôte ; le conteneur dispose de ses propres dépendances verrouillées. Enregistrer la version du code, de Python, des paquets, du moteur Docker, de restic et les digests d'images dans le dossier privé de livraison.

## 3. Créer la configuration d'un client

```bash
sudo .venv/bin/python -m admin_agent.ops init-client \
  --client-id acme \
  --name "Entreprise Exemple" \
  --domain admin.example.com \
  --directory /opt/admin-agent/runtime/acme
```

L'identifiant utilise 3 à 40 lettres minuscules, chiffres ou tirets et commence par une lettre. Le répertoire doit être nouveau : le script refuse d'écraser un client existant. Il crée :

| Chemin | Contenu | Précaution |
|---|---|---|
| `runtime/acme/client.json` | Configuration de référence pour la CLI | Privée ; chemins absolus ; une seule identité cliente |
| `runtime/acme/client.env` | Variables de déploiement Compose | Ne pas publier ; ne pas modifier l'identité sans nouvelle instance |
| `runtime/acme/data/` | Base SQLite et fichiers associés | Droits réservés au processus ; sauvegarde cohérente via CLI |
| `runtime/acme/secrets/session_secret` | Secret principal utilisé pour sessions et chiffrement TOTP | Sauvegarde/récupération sécurisée ; jamais dans logs ou Git |
| `runtime/acme/secrets/restic_password` | Mot de passe du dépôt de sauvegarde | Copie de récupération séparée de la VM et accès limité |
| `runtime/acme/evidence/` | Preuves d'exploitation | Pas de preuve fictive ; accès protégé |

L'initialisation règle les permissions privées. Avec `sudo`, les données et le secret de session sont rendus accessibles à l'UID applicatif prévu. Ne pas régler un problème de droits par `chmod 777`. Les sauvegardes contiennent des données clientes et des empreintes de comptes ; elles sont confidentielles même sans les secrets en clair. Le paquet de sauvegarde SQLite n'inclut ni le fichier `session_secret` ni `restic_password` : leur récupération séparée doit être organisée. La perte du mot de passe restic empêche de déchiffrer le dépôt. Le secret principal peut être remplacé dans un parcours de reprise avec ré-enrôlement de tous les facteurs.

## 4. Créer les personnes et enrôler leur MFA

Dans un terminal privé, sans enregistrement ni partage d'écran non autorisé :

```bash
sudo .venv/bin/python -m admin_agent.ops user-add \
  --config runtime/acme/client.json --username prenom.nom --role admin
```

Saisir deux fois un mot de passe unique de 14 à 128 caractères. La commande affiche l'information d'enrôlement TOTP une seule fois dans ce terminal ; la personne l'enregistre dans son application d'authentification. Ce secret est aussi sensible qu'un mot de passe. Ne pas le copier dans la documentation de recette. Une exécution sans terminal interactif doit utiliser `--enrollment-file CHEMIN_NOUVEAU_PRIVE` ; ce fichier temporaire reçoit des permissions 0600 et doit être supprimé après enrôlement selon la procédure interne.

Créer de la même manière les comptes `operator` et `reader` nécessaires. Ne pas créer un compte partagé appelé « client ». Pour un premier service opéré, seuls les opérateurs internes nominatifs peuvent suffire ; si le dirigeant accède à l'application, choisir explicitement son rôle. L'export global est réservé au rôle `admin`.

```bash
sudo .venv/bin/python -m admin_agent.ops user-disable \
  --config runtime/acme/client.json --username prenom.nom
sudo .venv/bin/python -m admin_agent.ops user-reset-password \
  --config runtime/acme/client.json --username prenom.nom
sudo .venv/bin/python -m admin_agent.ops user-reset-mfa \
  --config runtime/acme/client.json --username prenom.nom
sudo .venv/bin/python -m admin_agent.ops user-role \
  --config runtime/acme/client.json --username prenom.nom --role reader
sudo .venv/bin/python -m admin_agent.ops user-enable \
  --config runtime/acme/client.json --username prenom.nom
```

Ces commandes sont des opérations distinctes : ne pas exécuter toute la séquence pour une simple création. Vérifier l'identité de la personne avant une récupération. Aucun mail n'est envoyé. La désactivation et les réinitialisations retirent l'accès aux anciennes sessions ; le test réel de retrait fait partie de la recette.

## 5. Construire et ouvrir la stack

Avant le build, remplacer `APP_IMAGE=admin-agent:local` dans `client.env` par une étiquette de livraison propre, par exemple `admin-agent:release-20261002`. Ne pas réutiliser cette étiquette pour une autre image ; conserver aussi son digest.

```bash
sudo docker compose --env-file runtime/acme/client.env -p admin-acme config --quiet
sudo docker compose --env-file runtime/acme/client.env -p admin-acme build --pull
sudo docker compose --env-file runtime/acme/client.env -p admin-acme up -d
sudo docker compose --env-file runtime/acme/client.env -p admin-acme ps
sudo docker compose --env-file runtime/acme/client.env -p admin-acme logs --tail=100 app proxy
```

Compose utilise le serveur de production Flask/Waitress, le reverse proxy Caddy, un système de fichiers applicatif en lecture seule et une base persistante. Le service applicatif ne publie aucun port sur l'hôte et son réseau Docker est interne. Le profil de production refuse l'IA externe. Le serveur local `python -m admin_agent` reste un outil de démonstration et ne doit pas être utilisé pour ce déploiement.

Depuis un poste autorisé, ouvrir `https://admin.example.com`, vérifier le certificat et se connecter avec mot de passe + TOTP. Tester le nom du client, les rôles et la déconnexion. `/healthz` sert de signal minimal de vie ; `/readyz` contrôle la disponibilité prévue du service. Ne pas interpréter un HTTP 200 comme une recette métier ou une preuve de sauvegarde.

## 6. Configurer une sauvegarde chiffrée indépendante

Créer un dépôt distant **distinct pour ce client**, avec accès de stockage limité à son périmètre. Choisir sa région et ses conditions contractuelles. Le script accepte les destinations distantes restic prévues ; un chemin local n'est pas une sauvegarde indépendante. Les données sont préparées en mémoire temporaire `tmpfs`, puis chiffrées dans restic.

```bash
sudo install -d -m 700 /etc/admin-agent
sudo install -m 600 deploy/backup.env.example /etc/admin-agent/acme-backup.env
sudoedit /etc/admin-agent/acme-backup.env
sudo install -d -m 700 /var/cache/admin-agent-acme/restic
sudo install -d -m 700 /run/admin-agent-backup-acme
```

Dans ce fichier privé, renseigner les chemins, le dépôt, les identifiants limités du fournisseur et le fichier de mot de passe restic. Ne jamais utiliser `source` sur un fichier fourni par un client. Le fichier est interprété comme configuration par systemd, pas comme script shell. Vérifier que `/run/admin-agent-backup-acme` repose sur `tmpfs` ; le script refuse sinon. Protéger ou désactiver le swap non chiffré selon la configuration de l'hôte.

Initialiser une seule fois le nouveau dépôt distant, depuis le serveur autorisé :

```bash
sudo systemd-run --wait --pipe \
  --property=EnvironmentFile=/etc/admin-agent/acme-backup.env \
  /usr/bin/restic init
```

`restic init` ne doit pas remplacer la récupération d'un dépôt déjà existant. Si le dépôt existe, vérifier son accès avec `restic cat config` dans le même environnement. Ne jamais perdre le mot de passe de chiffrement : le stocker aussi dans le coffre de récupération prévu.

Installer le service et le timer fournis :

```bash
sudo chmod 755 deploy/backup.sh deploy/restore-drill.sh
sudo install -m 644 deploy/systemd/admin-agent-backup@.service /etc/systemd/system/
sudo install -m 644 deploy/systemd/admin-agent-backup@.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start admin-agent-backup@acme.service
sudo systemctl status admin-agent-backup@acme.service
sudo systemctl enable --now admin-agent-backup@acme.timer
sudo systemctl list-timers admin-agent-backup@acme.timer
```

Le timer fourni vise 02 h 30 UTC avec décalage aléatoire maximal de dix minutes et rattrapage d'une échéance manquée. Cette cadence est un exemple technique à adapter au RPO convenu. Un `last_success` est écrit dans `runtime/acme/evidence/backup-status.json` après sauvegarde et contrôle du dépôt. Le statut indique explicitement qu'une restauration reste à vérifier. Installer une alerte si la tâche échoue ou si ce fichier devient trop ancien ; aucun système d'alerte externe n'est configuré automatiquement.

Le dépôt ne lance pas de `forget`/`prune` automatiquement. Définir une politique approuvée, commencer par une simulation, vérifier ce qui serait supprimé puis faire exécuter la purge par une personne habilitée. Évaluer les protections contre effacement malveillant et leur compatibilité avec les durées convenues.

## 7. Prouver une restauration

Lister les snapshots du dépôt avec les mêmes variables privées ; choisir un identifiant explicite. Ne pas utiliser un `latest` ambigu provenant d'un autre client.

```bash
sudo systemd-run --wait --pipe \
  --property=EnvironmentFile=/etc/admin-agent/acme-backup.env \
  /usr/bin/restic snapshots
sudo .venv/bin/python -m admin_agent.ops init-client \
  --client-id acme --name "Entreprise Exemple" \
  --domain recovery.example.com \
  --directory /opt/admin-agent/runtime/acme-recovery
sudo install -d -m 700 /run/admin-agent-backup-acme
sudo systemd-run --wait --pipe \
  --property=EnvironmentFile=/etc/admin-agent/acme-backup.env \
  /opt/admin-agent/deploy/restore-drill.sh SNAPSHOT_HEXADECIMAL \
  /opt/admin-agent/runtime/acme-recovery/data/admin-agent.sqlite3
```

Remplacer `SNAPSHOT_HEXADECIMAL` par l'identifiant du snapshot testé. Le chemin cible doit être nouveau. Le script récupère la copie, vérifie empreinte, intégrité et identité client puis restaure en quarantaine. Il ne remplace jamais la base active. Éviter de lancer ce test pendant la fenêtre de sauvegarde ; les fichiers temporaires restent protégés.

**Une restauration invalide tous les comptes restaurés et leurs anciennes sessions.** La commande `init-client` ci-dessus prépare une configuration de reprise du même client et un nouveau secret principal, dans un répertoire distinct ; elle ne crée aucun DNS et ne démarre aucun serveur. Garder cette instance sans accès public pendant les contrôles. Avec cette configuration, réinitialiser le mot de passe et le MFA de chaque personne encore autorisée, puis appeler `user-enable`. Le script refuse la réactivation sans les deux réinitialisations.

```bash
sudo .venv/bin/python -m admin_agent.ops user-reset-password \
  --config runtime/acme-recovery/client.json --username prenom.nom
sudo .venv/bin/python -m admin_agent.ops user-reset-mfa \
  --config runtime/acme-recovery/client.json --username prenom.nom
sudo .venv/bin/python -m admin_agent.ops user-enable \
  --config runtime/acme-recovery/client.json --username prenom.nom
```

Ne pas exécuter ces commandes avec la configuration de production par erreur. Pour chaque personne, vérifier l'autorisation actuelle avant réactivation. Ne pas réutiliser un répertoire de reprise déjà existant : choisir un nouveau nom pour chaque exercice.

Pour une reprise complète, recréer l'environnement de déploiement isolé, affecter les droits de la nouvelle base à l'UID applicatif, vérifier le secret, les chemins et l'origine HTTPS. Les opérations `user-*` exécutées en root réappliquent les droits de la base selon la configuration. Comparer les dossiers et l'audit à l'export attendu, tester une connexion, un contrôle et une revue. Mesurer la durée totale, pas seulement la copie SQLite. Une restauration sur une VM de recette utilise son propre domaine et son propre certificat ; ne pas pointer le DNS de production avant décision de bascule. Sur la VM active, ne pas lancer une deuxième stack Caddy sur les mêmes ports pour l'exercice : utiliser une VM de recette isolée pour l'essai complet.

La CLI fournit aussi les primitives locales suivantes pour tests et opérations encadrées :

```bash
sudo .venv/bin/python -m admin_agent.ops backup \
  --db runtime/acme/data/admin-agent.sqlite3 --client-id acme \
  --destination /run/admin-agent-backup-acme/bundle-nouveau
sudo .venv/bin/python -m admin_agent.ops verify-backup \
  --source /run/admin-agent-backup-acme/bundle-nouveau --client-id acme
sudo .venv/bin/python -m admin_agent.ops restore \
  --source /run/admin-agent-backup-acme/bundle-nouveau --client-id acme \
  --target runtime/acme-recovery/autre-base-nouvelle.sqlite3
```

Ces primitives produisent une copie en clair locale ; elles ne remplacent pas le transfert chiffré indépendant. Leur sortie ne justifie aucune case de sauvegarde distante. Effacer la copie temporaire selon la procédure, après en avoir vérifié la cible.

## 8. Contrôle préalable et preuves

```bash
sudo .venv/bin/python -m admin_agent.ops preflight \
  --config runtime/acme/client.json \
  --backup /run/admin-agent-backup-acme/bundle-nouveau
```

Le paramètre `--backup` attend un paquet local déjà vérifié ; pour prouver la chaîne distante, utiliser un paquet effectivement récupéré depuis restic. La commande contrôle configuration, secret, permissions, identité/intégrité de base, présence d'un admin et paquet fourni. Elle laisse **`launch_ready: false`** et les validations manuelles en attente, même quand `technical_ready` vaut `true`.

Conserver le rapport technique, la preuve du snapshot distant, la restauration, la recette, les digests et le dossier de décision. Les répertoires temporaires sont retirés par les scripts ; garder des rapports sans secrets, pas nécessairement toutes les copies de bases.

## 9. Mise à jour, retour arrière et secrets

Avant une mise à jour : réserver une fenêtre, passer les tests sur une préproduction, relever la version courante et produire une sauvegarde vérifiée. Construire une nouvelle image avec une nouvelle étiquette. Arrêter l'application pendant tout changement de schéma qui l'exige. Faire un test de santé puis connexion/MFA, lecture, création, analyse, revue et export. Garder l'ancienne image et la sauvegarde jusqu'à la fin de la période de retour convenue.

Si les données et le schéma restent compatibles, le retour d'image peut suffire après vérification. Sinon restaurer vers une nouvelle base et suivre tout le parcours de récupération des comptes. Un retour à une copie ancienne peut perdre des opérations récentes : le client doit connaître le point de reprise, et les dossiers à rejouer doivent être identifiés. Ne pas écraser la base active avec `cp`.

En cas de compromission du secret principal : isoler l'instance, conserver les preuves, préparer un nouveau secret aléatoire protégé, reconfigurer la stack et réinitialiser les facteurs TOTP de tous les comptes autorisés. Le secret protège aussi le chiffrement des facteurs : sa rotation n'est pas transparente. Révoquer les sessions et tester l'ancien accès refusé avant réouverture. Aucun secret ne doit être imprimé par les commandes de diagnostic.

Pour arrêter temporairement le service, utiliser `docker compose ... stop app` avec le même fichier d'environnement et le même nom de projet. Une erreur de projet peut viser la mauvaise stack ; vérifier `ps` avant toute action. Ne pas ajouter `-v` lors d'un arrêt : l'effacement de volumes n'est pas un mécanisme de retour arrière.
