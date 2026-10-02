# OCR local et connecteurs gratuits

Version du 2 octobre 2026. Cette extension prépare l'entrée des documents et des données dans Admin Agent sans abonnement à une API OCR payante. Elle conserve les quatre workflows exécutables et les huit skills guidées : lire une pièce ne rend pas automatiquement fiables ses montants, ses dates ou son statut de paiement.

## Choisir le chemin adapté

| Source disponible chez le client | Outil livré | Résultat dans Admin Agent | À prévoir |
|---|---|---|---|
| Facture PDF, scan PNG/JPEG | Import dans Documents + Poppler/Tesseract/Pillow | Original conservé, texte par page, propositions sourcées et confirmation humaine | Instance avec worker OCR, langue et qualité vérifiées |
| Dossier de fichiers sur l'hôte | Connecteur de dossier local | Documents collectés, prêts pour extraction et revue | Chemin dédié, droits de lecture et lot maîtrisé |
| Export tabulaire de facturation | Connecteur CSV | Dossiers de contrôle de facture au statut nouveau | Colonnes, séparateur, décimales et format de date configurés |
| Espace Nextcloud/WebDAV existant | Connecteur WebDAV en lecture seule | Copies des documents autorisés, puis extraction séparée | Compte limité au dossier, mot de passe d'application et URL HTTPS |
| Dolibarr existant | Connecteur REST en lecture seule | Dossiers nouveaux à partir des factures, sans création d'écriture distante | Module REST, compte avec droits de lecture et clé dédiée |

Le logiciel Tesseract est libre sous Apache 2.0 [S1], Pillow sous MIT-CMU [S3], et Poppler fournit les outils de lecture PDF [S2]. Nextcloud et Dolibarr peuvent être auto-hébergés ; Dolibarr indique ne pas facturer de licence d'utilisation du logiciel [S4, S6]. **Gratuit concerne ici les briques logicielles et l'absence d'appel OCR facturé.** Hébergement, stockage, sauvegardes, maintenance, supervision et temps de revue restent à chiffrer. Aucun fournisseur, compte gratuit tiers ou forfait d'hébergement n'est créé automatiquement.

Pour un premier client, commencer par l'import manuel et un petit CSV représentatif. Ajouter Nextcloud si les pièces y sont déjà classées, ou Dolibarr si l'outil détient déjà les factures du client. Il n'est pas nécessaire de migrer son organisation vers un nouvel ERP pour utiliser l'OCR.

## 1. Parcours documentaire et contrôle humain

1. Se connecter à l'instance de la bonne entreprise avec un compte `operator` ou `admin`.
2. Ouvrir Documents, sélectionner la langue du document et importer un PDF, PNG ou JPEG autorisé. Un original identique est reconnu par son empreinte ; renommer le fichier ne crée pas une nouvelle pièce.
3. Lancer l'extraction. Un PDF contenant du texte exploitable utilise d'abord sa couche texte ; les pages qui en ont besoin passent par le rendu et Tesseract. Les langues prévues sont français, espagnol, anglais et leur combinaison.
4. Lire chaque page et comparer les propositions avec la pièce. Les propositions conservent une page, une citation et, quand disponible, une zone. Un score OCR mesure la confiance du moteur sur la reconnaissance ; il ne démontre pas la vérité comptable du champ.
5. Corriger les valeurs, compléter les informations réellement connues et confirmer les champs utilisés. Un statut de paiement ou de litige absent du document reste inconnu. Les mots d'un document sont des données à examiner, jamais des instructions à exécuter.
6. Créer le dossier depuis la version d'extraction confirmée. La provenance, les corrections et l'identité de la personne restent traçables. Le dossier commence au statut nouveau ; il doit encore être analysé et relu.
7. Faire réaliser toute suite métier par la personne habilitée dans son outil : la création du dossier n'envoie aucun message et ne met pas à jour la source.

Une nouvelle extraction ne remplace pas silencieusement le dossier déjà créé. Si un document ou un état change, traiter la divergence explicitement et refaire la revue concernée. Un PDF numériquement signé n'est pas authentifié par cet OCR. Le texte natif d'un PDF peut différer de son apparence : vérifier la page rendue, notamment les montants, même quand le résultat est lisible.

Les téléchargements d'originaux sont réservés aux utilisateurs autorisés de l'instance ; les pièces ne deviennent pas des liens publics. L'export global JSON des dossiers n'est pas un paquet complet de restitution documentaire. Pour rendre les originaux, les télécharger séparément et rapprocher l'inventaire de leurs empreintes ; la sauvegarde de base contient aussi les données d'authentification et ne doit pas être transmise comme un export métier ordinaire.

## 2. Limites visibles et conservation

| Limite | Valeur / comportement |
|---|---|
| Formats | PDF, PNG, JPEG ; pas DOCX/XLSX/ZIP/TIFF, PDF chiffré ou image multivue |
| Taille d'un original | 5 Mio maximum ; enveloppe HTTP d'import limitée à 6 Mio |
| PDF | 5 pages maximum ; pas de traitement silencieux de la seule première partie |
| Image d'entrée | 20 millions de pixels maximum ; validation avant traitement |
| Charge OCR | Une extraction active ; traitement borné à 60 secondes et sous-processus bornés |
| Texte / résultat | Texte limité à 64 Kio et réponse d'extraction à 1 Mio ; dépassement explicite |
| Capacité documentaire | 100 documents et 100 Mio d'originaux cumulés par instance |
| Historique | 20 Mio d'extractions cumulées, cinq extractions réussies maximum par document |
| Dossiers métier | 100 dossiers cumulés, distincts du nombre de documents |
| Effacement | Pas de purge documentaire automatique ni de suppression sélective proposée dans cette version |

La taille et le temps ne sont pas des garanties de qualité. Manuscrit, scans flous, tableaux complexes, plusieurs devises/taux ou factures avec avoirs et acomptes demandent une revue spécifique ; le contrôle métier reste limité à son périmètre initial. En cas d'ambiguïté, conserver le blocage et revenir à la source.

Les octets originaux, leurs empreintes, le texte, les propositions et les confirmations sont stockés dans la même base SQLite que les dossiers. La sauvegarde cohérente existante les inclut. Les quotas sont cumulatifs et n'expirent pas en fin de mois. Définir la conservation des copies de travail avec le client ; elle n'est pas automatiquement identique à sa conservation légale des factures. Surveiller la capacité et développer une évolution testée avant saturation, sans supprimer directement des lignes SQL.

## 3. Déploiement du worker OCR

Le [guide principal de déploiement](03-DEPLOIEMENT.md) construit les deux images et configure HTTPS, utilisateurs et sauvegardes. Renseigner `APP_IMAGE` et `OCR_IMAGE` avec des étiquettes de livraison distinctes. Le service `ocr` écoute le port 8766 uniquement sur le réseau Docker interne `documents`. Seule l'application partage ce réseau ; le proxy n'y est pas connecté. Aucun port OCR n'est publié sur l'hôte.

| Protection | Configuration fournie |
|---|---|
| Accès et persistance | Utilisateur UID/GID 10002, racine en lecture seule, aucun volume de base, clé ni secret |
| Réseau | Réseau interne sans accès Internet ; adresse du worker fixée côté application |
| Ressources | 768 Mio RAM, 1 CPU, 64 processus ; `/tmp` en mémoire limité à 128 Mio |
| Privilèges | Capacités supprimées, élévation interdite, `noexec/nosuid/nodev` sur l'espace temporaire |
| Sous-processus | Exécutables à chemins fixes, aucun shell, durée et ressources bornées |
| Contenu de l'image | Python 3.12.15, dépendances Python verrouillées, paquets Debian Poppler/Tesseract et langues FR/ES/EN |

Les temporaires du worker sont retirés après traitement ; un redémarrage supprime aussi le contenu de son `tmpfs`. Protéger le swap de l'hôte selon la procédure de déploiement. L'isolation réduit les conséquences d'une pièce malformée mais ne remplace pas les mises à jour de sécurité des moteurs de parsing.

La limite de 64 tâches appartient au cgroup Docker du service, pas à l'ensemble des processus du même utilisateur sur l'hôte. Les commandes locales de développement ne reproduisent pas cette isolation : le lancement client doit conserver le conteneur et ses limites Compose.

`GET /health` est un signal de vie ; la recette doit également réussir une extraction de chaque format/langue retenu. Le port n'a pas d'authentification destinée à Internet : ne pas le publier et ne pas le connecter à un réseau partagé avec d'autres applications. La CLI et le serveur de démonstration restent utilisables sans moteur OCR ; cette option ne rend pas le serveur de démonstration publiable.

Relever `/app/ocr-packages.txt`, le digest et les notices de l'image. Les versions Debian se résolvent au build depuis les dépôts maintenus ; le digest et le manifeste identifient le résultat exact. Lors d'une reconstruction pour correctifs, rejouer les tests OCR puis le lot client, avec mesure de temps et comparaison des champs critiques. Voir [les notices tierces](../../THIRD-PARTY-NOTICES.md).

## 4. Configuration des connecteurs

Les connecteurs sont lancés par un administrateur habilité sur l'hôte. Ils ne donnent pas au serveur web une sortie Internet et ne prennent pas une URL depuis un document ou un champ libre du navigateur. Ils lisent la source distante ; les écritures éventuelles concernent seulement la base locale d'Admin Agent.

Préparer, dans le répertoire privé de l'instance, une copie de [`examples/connectors.example.json`](../../examples/connectors.example.json). Remplacer uniquement les paramètres du connecteur retenu. Le modèle CSV est [`examples/invoices.example.csv`](../../examples/invoices.example.csv). Le dossier client `runtime/acme` ci-dessous est un exemple créé avec `init-client` ; la configuration réelle reste hors Git et ne doit contenir aucune clé en clair.

Pour une source distante, enregistrer le secret dans un fichier séparé : propriétaire de l'opérateur de la CLI, permissions `0600`, répertoire parent protégé. Avec les commandes `sudo` du déploiement de référence, le propriétaire est `root`. Référencer son chemin dans la configuration. Ne passer de secret ni dans une URL, ni dans un argument de commande, ni dans les exemples publics. Vérifier l'identité client de `client.json` avant chaque lot.

### Prévisualiser avant d'importer

Dans `/opt/admin-agent`, avec le venv de production configuré selon le guide de déploiement :

```bash
sudo .venv/bin/python -m admin_agent.connector_cli \
  --client-config /opt/admin-agent/runtime/acme/client.json \
  --connector-config /opt/admin-agent/runtime/acme/connectors.json \
  --connector ID_DU_CONNECTEUR
```

Sans `--import`, la commande lit la source et affiche un aperçu mais n'écrit pas dans la base. Cet aperçu peut contenir des données clientes : utiliser un terminal privé et ne pas copier sa sortie dans GitHub. Vérifier source, quantité, références, colonnes, devise et dates.

### Importer le lot vérifié

```bash
sudo .venv/bin/python -m admin_agent.connector_cli \
  --client-config /opt/admin-agent/runtime/acme/client.json \
  --connector-config /opt/admin-agent/runtime/acme/connectors.json \
  --connector ID_DU_CONNECTEUR --import
```

Les fichiers du dossier local ou de WebDAV sont importés comme documents, sans lancer l'OCR dans la CLI. Ouvrir ensuite Documents pour extraire et confirmer. Les lignes CSV et les factures Dolibarr deviennent des dossiers de `invoice-check` au statut nouveau, pas des résultats approuvés. Relire et compléter les champs avant analyse, puis appliquer le circuit habituel de revue.

Chaque élément est suivi par identifiant source et empreinte : le rejeu du même contenu est idempotent. Un contenu modifié sous le même identifiant donne un conflit à résoudre humainement ; il n'écrase pas un dossier relu. Examiner le résultat de chaque lot avant de continuer : l'import n'est pas atomique à l'échelle du lot. Des éléments peuvent être importés alors que d'autres sont refusés ; `completed: false` et le code de sortie 2 signalent un lot incomplet. Le rejeu retrouve les éléments déjà importés sans les dupliquer. Aucun ordonnanceur ni boucle de synchronisation permanente n'est activé.

## 5. Particularités de chaque source

| Connecteur | Préparation et droits | Limites à connaître |
|---|---|---|
| Dossier local | Répertoire dédié aux pièces de l'entreprise, fichiers lisibles par l'opérateur | Lecture non récursive ; lot limité à 20 éléments ; inventaire de 1 000 entrées maximum ; pas de suivi des dossiers supprimés |
| CSV | Export limité à l'entreprise ; mapping explicite des colonnes, séparateur, décimales et dates | 20 lignes par lot ; chaîne vide ou `unknown` reste inconnue pour paiement/litige ; ne pas deviner la devise ou un taux de TVA |
| Nextcloud/WebDAV | Utilisateur dédié ayant lecture d'un dossier partagé ; mot de passe d'application révocable ; URL du répertoire WebDAV [S5] | HTTPS public sur port 443, pas de redirection ni IP privée ; lot borné ; les permissions de lecture seule doivent être configurées sur la source |
| Dolibarr | Activer le module API REST ; utilisateur dédié autorisé à lire les factures ; clé transmise dans `DOLAPIKEY` [S7] | HTTPS public sur port 443 ; 20 factures par page ; devise de base et fuseau configurés ; paiement, litige, client et taux à compléter manuellement |

Le connecteur WebDAV utilise seulement les opérations de lecture nécessaires à l'inventaire et au téléchargement. Il ne crée ni ne déplace ni ne supprime de fichier dans Nextcloud. La configuration HTTPS refuse les redirections, les proxies hérités et les destinations privées. Une instance uniquement accessible sur un réseau privé ne doit pas être rendue publique pour satisfaire ce connecteur : utiliser un export local autorisé en attendant une intégration réseau adaptée et testée.

Pour Dolibarr, contrôler les droits de l'utilisateur dans l'ERP ; ne pas employer une clé administrateur. L'explorateur REST de l'instance permet au responsable de vérifier la structure disponible. La présence d'une facture dans l'API ne suffit pas à connaître les règlements ultérieurs. Le connecteur n'émet que des lectures et ne prépare pas automatiquement de relance.

La pagination Dolibarr est explicite et commence à zéro. Après examen de la page précédente, appeler par exemple :

```bash
sudo .venv/bin/python -m admin_agent.connector_cli \
  --client-config /opt/admin-agent/runtime/acme/client.json \
  --connector-config /opt/admin-agent/runtime/acme/connectors.json \
  --connector ID_DOLIBARR --page 1
```

L'ordre utilise l'identifiant croissant. Des modifications simultanées dans l'ERP peuvent changer le contenu d'un ensemble paginé : cette collecte ne prouve pas à elle seule l'exhaustivité comptable d'une période. Conserver les références, traiter les conflits et comparer le nombre de factures à l'export faisant foi. Ne jamais augmenter un lot pour contourner la capacité de 100 dossiers de l'instance.

## 6. Recette et fonctionnement en cas d'échec

Exécuter D01 à D06 du [guide de recette](04-RECETTE-CLIENT.md) pour le périmètre choisi. Les tests automatisés du dépôt utilisent des documents synthétiques et des réponses de source contrôlées. **Aucun compte Nextcloud ou Dolibarr réel n'a été connecté ni validé pour un client dans cette livraison.** Les versions et les résultats effectivement testés sont consignés dans [QA](../QA.md).

| Situation | Action attendue |
|---|---|
| OCR indisponible ou occupé | Conserver la pièce ; attendre, examiner la santé et relancer une seule fois après résolution |
| Texte incomplet ou faux | Revenir à l'original, corriger explicitement ou abandonner la proposition ; ne pas présenter la valeur comme certaine |
| HTTP 401/403 d'un connecteur | Faire contrôler le compte, la clé et les droits par le responsable de la source ; ne pas élargir à admin pour contourner |
| Conflit après changement de la source | Comparer les versions et corriger le dossier dans le circuit de revue ; aucune substitution automatique |
| Quota atteint | Suspendre les nouveaux imports, inventorier les besoins et préparer l'évolution de capacité/conservation |
| Fin de service | Arrêter les collectes, restituer les données convenues, révoquer les clés et traiter aussi les copies et sauvegardes |

## Sources officielles consultées le 2 octobre 2026

| Réf. | Source | Ce qu'elle documente |
|---|---|---|
| S1 | [Tesseract — manuel](https://tesseract-ocr.github.io/tessdoc/) et [installation](https://tesseract-ocr.github.io/tessdoc/Installation.html) | Moteur libre, licence Apache 2.0, données de langues |
| S2 | [Poppler — projet officiel](https://poppler.freedesktop.org/) | Utilitaires PDF, code source et maintenance ; licence précise conservée dans le paquet |
| S3 | [Pillow — licence](https://pillow.readthedocs.io/en/stable/about.html#license) | MIT-CMU |
| S4 | [Nextcloud — installation](https://nextcloud.com/install/) et [licences du serveur](https://github.com/nextcloud/server/blob/master/COPYING-README) | Auto-hébergement, fournisseurs distincts, AGPL |
| S5 | [Nextcloud — WebDAV](https://docs.nextcloud.com/server/stable/developer_manual/client_apis/WebDAV/basic.html) | URL, opérations, authentification et mots de passe d'application |
| S6 | [Dolibarr — logiciel gratuit](https://www.dolibarr.org/free.php) et [téléchargement](https://www.dolibarr.org/downloads.php) | Absence de licence payante du logiciel, distinction avec les services |
| S7 | [Dolibarr — module API REST](https://wiki.dolibarr.org/index.php/Module_Web_Services_API_REST_%28developer%29) | Activation, explorateur et en-tête `DOLAPIKEY` |

Les versions serveur supportées et droits disponibles restent à vérifier sur l'instance retenue. Aucune promesse de gratuité d'une offre commerciale externe ou de compatibilité avec tous les modules personnalisés n'est faite.
