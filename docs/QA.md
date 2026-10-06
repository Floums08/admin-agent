# Contrôle qualité — finances et frais, version 0.5

## Complément du 6 octobre 2026 — implantation et amélioration continue en espagnol

Documentation ajoutée : [guide d'implantation](launch/es/GUIA-IMPLEMENTACION.md), [processus d'amélioration](launch/es/MEJORA-CONTINUA.md) et [modèles opérationnels](launch/es/PLANTILLAS-OPERATIVAS.md). Aucun code applicatif, dépendance, skill exécutable, secret ou environnement client n'est modifié.

Base relue : `cf52ccdf7a2297be14ad1ad8b88e5b07d2950e7d`. La [CI de cette base](https://github.com/Floums08/admin-agent/actions/runs/37315977049) est terminée avec succès. Cette observation du 6 octobre est distincte de toute nouvelle exécution locale et ne vaut pas recette d'un hébergement réel.

Contrôles documentaires : commandes rapprochées de la CLI et des runbooks existants ; liens relatifs vérifiés contre l'arbre du dépôt ; blocs de code équilibrés ; distinction entre les deux lots synthétiques, les mesures manuelles et la CI automatique. Deux audits indépendants ont vérifié déploiement/reprise et métriques/limites. La documentation conserve les limites de la source financière figée, des quotas cumulés, des comptes désactivés après restauration et de l'IA externe indisponible en production.

Les cadences, seuils opérationnels de capacité 70 % / 85 % et priorités sont des propositions explicites. Ils n'activent ni surveillance, ni collecte périodique, ni communications. Le lot étendu de 18 pièces n'est pas encore un pas du workflow CI ; son ajout est proposé comme amélioration. Les décisions et preuves clientes sont à compléter en privé.

## Complément du 5 octobre 2026 — documents fictifs

Le [générateur et sa recette](launch/10-JEU-TEST-FICTIF.md) ajoutent un lot téléchargeable de dix factures et huit reçus, leurs CSV et un corrigé indépendant. Aucun fichier du runtime applicatif n'est modifié. La validation du lot réussit sur 18 cas et neuf scénarios financiers, avec 17 originaux uniques extraits par le vrai sous-processus OCR. Sur 127 champs, 125 sont exacts et deux noms de clients demandent une correction O/0 ; les montants et dates présents sont exacts. La revue humaine simulée utilise les valeurs du corrigé et reste distincte de la qualité OCR. La suite existante de 335 tests a été rejouée sans échec ni test ignoré. Les originaux et le guide ont été inspectés visuellement après rendu, et les résultats détaillés accompagnent le lot.

## Livraison du 4 octobre 2026

Date : **4 octobre 2026**. Cette version ajoute le suivi des factures clients/fournisseurs, les paiements partiels, le rapprochement bancaire CSV, l'affacturage indicatif et les reçus de notes de frais. Le [guide opératoire](launch/09-FINANCE-ET-FRAIS.md) définit le périmètre et le [rapport indépendant](QA-FINANCE-2026-10-04.md) détaille les contrôles financiers et de sécurité. Toutes les données de recette sont synthétiques.

La validation locale a réussi : **335 tests Python, aucun ignoré**, avec les dépendances de production et les moteurs OCR réels. Les tests couvrent les centimes, sens et devises, l'ouverture en fin de journée, les imports idempotents, conflits atomiques, paiements partiels, annulations, versions, cessions documentées et absence de paiement lors d'une simulation. Les reçus PDF FR/ES et images EN/FR/ES passent par Poppler/Tesseract ; ces résultats ne mesurent pas la qualité d'un lot client réel.

Les **47 scénarios DOM/API** passent : 12 généraux, 13 d'authentification, 10 documentaires et 12 financiers. Les **27 scénarios Chromium réels** ont également réussi : dix de production/authentification, neuf d'import/OCR documentaire et huit de finance/frais, avec certificat TLS local, service de production réel et worker OCR réel. Les nouveaux parcours couvrent inscription, simulation à 30 jours, import et rejeu CSV, paiement partiel et annulation, litige et cession, reçu OCR, correction/reconfirmation, droits lecteur, mobile et purge après déconnexion. Les captures synthétiques desktop/mobile ont été inspectées ; les notifications simultanées ont été limitées à deux pour conserver la lisibilité.

La [CI de cette version](https://github.com/Floums08/admin-agent/actions/runs/37207358344), commit `b64d58531ee020edbae0f43a99d9c9d0333a3167`, a terminé ses **six jobs avec succès** : Python 3.11/3.12/3.13, interface et Chromium, images de production et audit des dépendances. Les images construites ont exécuté le contrôle MFA/rôles, l'OCR natif, l'inscription d'une facture, la simulation, l'import bancaire avec rejeu et le rapprochement partiel. La recette du Compose pilote avec Caddy/TLS local vérifié et la restauration chiffrée restic ont également réussi. Docker et restic étant absents du poste local, ces deux preuves proviennent de GitHub Actions, avec données synthétiques et stockage de test.

La publication finale ajoute uniquement ce compte rendu au code testé. Elle ne crée aucune instance cliente, aucun accès bancaire et aucun contrat d'affacturage.

Corrections issues de la revue : une base locale contenant seulement des mouvements bancaires ou des documents ne peut plus être attribuée silencieusement à un client de production ; les doublons de frais sont revérifiés au moment de l'approbation ; la reconfirmation d'un reçu corrigé conserve ses preuves et invalide l'ancienne analyse/revue. La révocation d'une session pendant une écriture provoque son annulation transactionnelle.

Limites de livraison : ouverture du registre et instantané de facture immuables, modification ultérieure de la source bloquante, aucun traitement des avoirs ou flux du factor, aucun remboursement salarié rapproché, aucun compte bancaire ni financeur connecté. Le registre n'actualise pas automatiquement le workflow séparé de relance. Le lancement client requiert encore hébergement, HTTPS public, accès nominatifs, restauration hors hôte et recette sur pièces autorisées.

## Historique — pilote factures, version 0.4

Date : **3 octobre 2026**. Le [rapport de revue indépendante du pilote](QA-PILOT-2026-10-03.md) décrit les vérifications du lancement local privé, des dix factures synthétiques et du registre de mesures. Le [guide opératoire](launch/08-PILOTE-FACTURES.md) sépare cette répétition de la qualification du premier client. Aucun résultat de test ne mesure une économie de temps humain ou ne constitue une mise en service cliente.

Vérification locale : **246 tests Python réussis sans test ignoré** sous Python 3.12.14, dont 42 nouveaux tests du kit pilote. Les dix documents synthétiques ont réellement traversé l'extraction native/OCR puis le contrôle avec une revue simulée utilisant le corrigé séparé. Les **35 scénarios DOM/API** existants passent. Les commandes du guide ont été rejouées, sans enregistrer de temps humain inventé ; les originaux, secrets et registres générés restent hors publication.

La [CI du code du pilote](https://github.com/Floums08/admin-agent/actions/runs/37126689622), commit `271fa46cb8380f4786fd2d6a1845b9296ec27ab2`, a terminé ses **six jobs avec succès** : Python 3.11/3.12/3.13, interface et navigateur réel, images de production et audit des dépendances. La recette du Compose pilote complet a réussi avec Caddy, application authentifiée et worker OCR, certificat local vérifié, port effectivement lié à la boucle locale, MFA, original conservé, extraction française et confirmation explicite. La restauration restic chiffrée avec original et empreinte vérifiés a aussi réussi. Ces contrôles Docker ont été exécutés dans GitHub Actions, Docker étant absent de l'environnement local de développement.

## Résultats précédents — OCR et connecteurs, version 0.3

Date : **2 octobre 2026**. Tous les documents, comptes et entreprises utilisés sont synthétiques. Aucun compte Nextcloud/Dolibarr réel, aucune messagerie, banque ou administration n'a été connecté. Aucun message client n'a été envoyé.

## Vérifications de l'extension

**204 tests Python réussis** sous Python 3.12.14, sans test ignoré : 104 antérieurs, 20 OCR, 19 API/stockage documentaire, 33 connecteurs, 20 revue indépendante et 8 risques métier. Les scénarios contenus dans des sous-tests ne s'ajoutent pas à ces nombres. Les résultats historiques plus bas décrivent les versions antérieures.

Interface : **12 parcours DOM/API**, **13 scénarios DOM d'authentification**, **10 scénarios DOM documentaires** ; transport simulé pour les deux dernières suites. **19 parcours Chromium réel 131 réussis** : 10 existants et 9 documentaires, avec Waitress, TLS local temporaire et worker OCR réel. Les captures bureau et mobile 390 px ont été inspectées ; aucune erreur JavaScript ni requête navigateur extérieure à l'origine de test n'a été relevée. Ces captures synthétiques restent hors du dépôt publié.

- **OCR réel** : Poppler sur PDF natifs EN/FR/ES ; Tesseract sur PNG/JPEG, PDF scanné et PDF avec OCR forcé ; modèles officiels français et espagnol. Le worker est aussi exercé dans son sous-processus isolé, avec les mêmes limites de ressources.
- **Revue indépendante** : refus CSRF/RBAC, originaux intègres, fausse provenance, confirmations incomplètes, versions périmées, courses de création/extraction, révocation pendant OCR, réponses malveillantes du worker, sources réseau interdites et secrets protégés.
- **Connecteurs** : protocole HTTPS simulé pour WebDAV et Dolibarr, méthode de lecture, limites, pagination, redirections, DNS public/privé, chemins traversants, statuts inconnus et conflits de contenu/mapping. Huit appels CLI réels sur dossier local et CSV : aperçu sans mutation, import, rejeu, source modifiée refusée, succès partiel explicite et propriété UID de la base conservée.
- **Sauvegarde réelle** : SQLite → dépôt restic local chiffré → contrôle intégral → récupération → restauration en quarantaine. Le BLOB original et son SHA-256 sont comparés après restauration ; les comptes restent désactivés. Ce test ne qualifie pas un fournisseur hors hôte.
- **Dépendances** : audits pip-audit 2.10.1 des requirements production et OCR sans vulnérabilité connue signalée au moment de l'exécution. Aucun audit de dépendances ne garantit l'absence de vulnérabilités.
- **Contrôles statiques** : syntaxe Python/JavaScript/shell, liens internes des guides, configuration d'exemples et diff vérifiés.

## Corrections prioritaires issues de la boucle QA

| Défaut reproduit | Correction et portée |
|---|---|
| Normalisation d'un libellé Unicode décalant la valeur proposée | Abstention quand le mappage au texte original serait ambigu ; citation originale conservée |
| Libellé « Total HT » interprété aussi comme total TTC ; plusieurs devises sur une même valeur | Sélection plus stricte et abstention en cas de contradiction |
| Modèles de langues fournis sans dossier de configuration TSV | Activation explicite de la sortie TSV de Tesseract, sans dépendance implicite aux fichiers auxiliaires |
| Source CSV identique mais mapping ou pays modifié | Empreinte des valeurs mappées distincte de l'empreinte brute ; conflit au réimport |
| Provenance document/connecteur forgeable ou effaçable depuis une édition | Métadonnées réservées au serveur, snapshot immuable et changements ultérieurs signalés |
| Import CLI root créant des fichiers SQLite incompatibles avec l'UID applicatif | Vérification de l'opérateur et remise des permissions/propriétaires selon la configuration client |
| Chargement tardif de la liste effaçant le fichier sélectionné | Conservation du formulaire réel et de son objet File ; régression asynchrone |
| Nouvelle extraction échouée laissant d'anciennes propositions utilisables | Anciennes preuves consultables, création bloquée jusqu'à une extraction réussie |
| Mention d'acompte, avoir ou régime particulier perdue entre texte source et dossier | Signaux de risque sourcés, conservés dans la provenance et blocage du traitement simple pour revue spécialisée |
| Solde restant accepté sans rapprochement ; paiement partiel importé retiré du formulaire | Champs de solde bloquants et vérification du snapshot importé immuable avant préparation financière |
| Texte de demande triée ignoré quand envoyé uniquement par payload | Moteur lisant explicitement la demande vérifiée avec le contexte séparé |
| Temporaire trop petit pour les doubles tampons d'upload concurrents | Connexions Waitress ramenées à huit, tmpfs applicatif à 128 Mio ; pas de certification de charge soutenue |
| Premier smoke Docker supposant un port publié sur un réseau interne | Test depuis l'hôte Linux vers l'adresse privée du bridge ; application et OCR gardés sans port publié |
| OCR en CI bloqué par les threads Chromium du même UID | Cause reproduite sous UID non privilégié avec 90 threads : RLIMIT_NPROC produisait EAGAIN. Suppression de cette limite globale à l'UID ; limite de 64 tâches maintenue par le cgroup du conteneur OCR, limites CPU/mémoire/fichiers/délai inchangées |

## Limites qui restent à qualifier

Une image française synthétique propre a réellement donné « TIC » à la place de « TTC ». Le moteur s'abstient sur ce libellé ; il ne corrige pas silencieusement le montant. Les fixtures et régressions vérifient le fonctionnement et les refus, **pas un taux d'exactitude représentatif sur un corpus client indépendant**. Mesurer les erreurs de champs critiques et le temps de correction avant engagement commercial.

Les droits, versions et schémas des comptes Nextcloud/Dolibarr réels restent à tester chez le client. L'aperçu d'un connecteur relit la source lors de l'import ; ce n'est pas une transaction distante figée. Les imports ne prouvent ni un solde actuel ni l'exhaustivité d'une période. Les quotas initiaux restent cumulatifs ; la purge et l'archivage opérationnels ne sont pas livrés.

L'environnement de rédaction ne dispose pas de Docker : les deux images et Caddy sont vérifiés par le job GitHub `production-image`. Le résultat de référence est toujours celui du commit exact dans [GitHub Actions](https://github.com/Floums08/admin-agent/actions). Un test TLS local ne prouve pas un certificat public ni le bon fonctionnement du pare-feu de l'hôte client.

Commandes ajoutées : `npm run test:documents-ui`, `npm run test:documents-browser`, `python scripts/container_smoke.py --image admin-agent:ci --ocr-image admin-agent-ocr:ci`. Installer `requirements-production.txt`, `requirements-ocr.txt`, Poppler/Tesseract et les trois modèles avant la QA complète. Les tests ignorés pour dépendances absentes ne valent pas validation.

---

Les résultats suivants sont conservés comme **historique de la version 0.2**, avant l'extension OCR/connecteurs.

# Contrôle qualité — préparation de production

Date : **2 octobre 2026**. Les vérifications utilisent exclusivement des entreprises, comptes et dossiers synthétiques. Aucun hébergement client ni fournisseur de sauvegarde réel n'a été provisionné ; aucun message client, paiement ou dépôt n'a été exécuté.

## Résultats de cette livraison

| Vérification réellement exécutée | Résultat et portée |
|---|---|
| Python 3.12.14, dépendances production installées | **104 méthodes de test réussies** : 62 existantes, 18 production, 13 opérations, 11 revue de sécurité indépendante |
| DOM/API local | **12 parcours réussis** avec serveur local réel |
| DOM authentification | **13 scénarios réussis**, transport simulé : rôles, CSRF, purge après expiration, refus des réponses tardives, communication de déconnexion entre onglets |
| Chromium réel 131, Waitress réel, TLS local temporaire | **10 parcours réussis**, bureau 1280 px et mobile 390 px, création/analyse/revue/correction, MFA, permissions, révocation, absence d'erreur JS et de requête externe |
| Sauvegarde chiffrée réelle restic 0.19.1 | Snapshot SQLite → dépôt local chiffré → contrôle complet des données → récupération → restauration en quarantaine, identifiants historiques inutilisables |
| Audit des requirements Python via pip-audit 2.10.1 | Aucune vulnérabilité connue signalée au moment de l'exécution ; cela ne certifie pas l'absence de vulnérabilités |
| Contrôles statiques | Syntaxe Python/JavaScript/shell, JSON d'intégration client, liens de documentation et diff vérifiés |

Les 24 scénarios métier déterministes existants restent des sous-tests inclus dans les 62 méthodes initiales ; ils ne s'ajoutent pas aux 104. Les tests fournisseur IA restent simulés. Les captures navigateur synthétiques ont été inspectées et restent hors des fichiers publiés.

## Corrections issues de la revue

| Risque reproduit ou vérifié | Correction livrée |
|---|---|
| Ancien accès réactivé par une restauration | Désactivation des comptes, destruction des anciens moyens d'accès, renouvellement password + MFA avant réactivation |
| Quota de pré-sessions empêchant la déconnexion | Révocation garantie même quand le renouvellement de pré-session échoue |
| Deux connexions utilisant le même code TOTP simultanément | Consommation atomique du pas TOTP ; une seule connexion réussit |
| Révocation pendant une écriture | Autorisation recontrôlée dans la transaction métier |
| Réponse tardive ou autre onglet conservant un dossier après logout | Génération de session UI, purge des données et signal inter-onglets sans contenu métier |
| Petit input générant un résultat et des listes démesurés | Résultat borné à 32 Kio, 100 dossiers maximum, listes compactes, export en flux, détail limité aux 200 derniers événements avec indication explicite |
| Mauvais catalogue dans l'image | Dockerfile corrigé pour copier le fichier réellement lu |
| Premier smoke du conteneur : attente HTTP incorrecte dans le test | La route de démo absente refuse le POST avec 405 ; le test vérifie ce refus et l'absence de nouveaux dossiers |
| Droits et frontières HTTP | Tests lecteur, origine/CSRF, cookie/session, Host/proxy, JSON dupliqué/invalide/trop volumineux et identité de base |
| Tableau difficile à lire sur mobile | État du dossier rendu entièrement visible à 390 px ; dialogues et parcours revérifiés |

La revue indépendante n'a pas observé d'autre blocage matériel dans ce périmètre de première instance isolée. Ce constat n'est pas un audit de sécurité exhaustif ni une certification.

## CI et reproductibilité

Le workflow [Production and local QA](../.github/workflows/qa.yml) installe les dépendances et rejoue les tests sur Python 3.11, 3.12 et 3.13. Il exécute les parcours DOM et Chromium, construit l'image Docker, vérifie le runtime non-root/lecture seule et les flux MFA/permissions sur le conteneur réel, valide Caddy/Compose et rejoue la restauration restic. Un job distinct audite les dépendances.

**Le statut de référence est celui du commit concerné dans [GitHub Actions](https://github.com/Floums08/admin-agent/actions)**. Les tests Docker ne peuvent pas être exécutés dans l'environnement local de rédaction, qui ne fournit pas Docker ; ils sont confiés au runner GitHub. Le test navigateur local utilise un certificat autosigné accepté uniquement dans son contexte de test. Il ne prouve pas la validité d'un certificat public.

Commandes : `python scripts/qa.py`, `npm run test:ui`, `npm run test:auth-ui`, `npm run test:browser`, `python scripts/container_smoke.py --image admin-agent:ci`, `PYTHON=python RESTIC_BINARY=restic sh tests/restic_smoke.sh`. Installer d'abord les dépendances indiquées dans le README. Ne pas interpréter des tests marqués skipped faute de dépendances comme une validation de production.

## Vérifications encore propres à chaque client

- Domaine/DNS, vrai certificat HTTPS, pare-feu, accès administrateurs, chiffrement des volumes et supervision sur l'hôte retenu.
- Dépôt de sauvegarde réellement indépendant, credentials restreints, récupération des clés, restauration depuis cet emplacement et temps de reprise mesuré.
- Accord de traitement, conservation, identité des personnes habilitées et recette métier sur un lot autorisé.
- Absence d'OCR/import documentaire/connecteur réel dans cette version. L'IA externe est refusée en production ; aucune qualité réelle de modèle n'est certifiée.
- Capacité initiale de 100 dossiers cumulés : pas de charge soutenue, haute disponibilité ou déploiement multi-tenant validés. Pas de séparation préparateur/relecteur imposée par le code.

Le [dossier de décision de lancement](launch/06-GO-NO-GO.md) doit rassembler ces preuves. Le préflight conserve volontairement `launch_ready:false` : un contrôle technique ne signe pas le lancement du client.

---

Les éléments ci-dessous décrivent **la livraison locale antérieure** et ses limites à cette étape ; ils ne remplacent pas le bilan de production ci-dessus.

# Historique — version locale initiale

Date : **2 octobre 2026**. Environnement local : Python **3.12.14**, Node **24.19.0**, Linux. Les données utilisées sont synthétiques. Aucun client contacté, aucun e-mail envoyé, aucun paiement ni dépôt exécuté.

## Résultats automatisés

**62 tests Python réussis** avec `python3 -m unittest discover -s tests -q`. La suite inclut :

- 51 tests du moteur, du stockage et du serveur, avec appels HTTP réels sur localhost.
- 7 tests du module IA avec fournisseur simulé.
- 1 test de refus d'instructions de skill absentes ou tronquées avant appel IA.
- 3 tests catalogue/fixtures, dont un rejoue **24 scénarios métier déterministes** via sous-tests. Les 24 ne sont pas à additionner aux 62 comme s'il s'agissait de méthodes de test supplémentaires.

Les 16 scénarios comportementaux présents dans le fichier de fixtures sont des spécifications à évaluer séparément. Deux essais indépendants supplémentaires ont été exécutés sur les skills : [résultats et limites](SKILL-VALIDATION.md).

**12 parcours DOM/API réussis** avec `npm run test:ui` (LinkeDOM 0.18.12, serveur Python réel démarré sur un port local temporaire). Ils couvrent le tableau de bord vide, la démo idempotente, la recherche dans les données, les filtres des skills, la création/analyse, l'échappement d'un titre contenant du HTML, l'approbation, l'invalidation après correction, la conservation des données de paiement non affichées, les états de paiement inconnus, le conflit de version entre onglets, l'activation IA, un réessai après réponse réseau perdue et l'export. Plusieurs assertions sont regroupées dans un même parcours. Les API de formulaire/dialogue sont adaptées dans le simulateur ; il ne reproduit pas le rendu d'un navigateur.

## Boucles d'amélioration réellement réalisées

| Cycle | Défaut ou risque observé | Modification et vérification |
|---|---|---|
| 1 — construction | Risque de confondre analyse et action | Contrôles Decimal, statuts persistés, approbation interne, aucun endpoint d'envoi/paiement/dépôt |
| 1 — contrôle | Doublons au réessai et mises à jour concurrentes | Clé d'idempotence avec empreinte, transactions SQLite, conflits de version et tests multi-threads |
| 2 — revue indépendante | Un onglet pouvait approuver une analyse modifiée ailleurs | Version obligatoire à la revue ; le scénario reproduit retourne désormais 409 et reste à réviser |
| 2 — module IA | Une clé mal formée pouvait apparaître dans une exception de bibliothèque HTTP | Validation de la clé, erreurs neutralisées et test avec message d'erreur contenant un secret fictif |
| 2 — module IA | Réponse fournisseur avec contenu null/non textuel | Erreur contrôlée, aucun résultat appliqué ; scénarios de refus/incomplétude et appels d'outils inattendus |
| 2 — entrée | Unicode invalide et type de décision inattendu | Rejet 400 contrôlé ; aucun détail interne exposé |
| 2 — métier | Paiement partiel signalé avec indicateur paid=false | Blocage sur champs ou signaux textuels reconnus ; aucun brouillon réclamant le total initial |
| 2 — métier | Une facture nulle pouvait produire une relance à zéro | Suppression du brouillon, explication explicite et test de régression |
| 2 — contexte | Instructions absentes ou trop longues | Appel IA refusé, sans troncature silencieuse des instructions |
| 2 — traçabilité | Des guides pouvaient être interprétés comme fonctions achevées | Huit compétences étiquetées guided ; leur analyse reste bloquée pour revue spécialisée |
| 3 — interface | Une correction de titre supprimait les champs non affichés, notamment l'acompte | Fusion conservatrice du payload ; les preuves supplémentaires restent visibles et le test garde le blocage |
| 3 — interface | Une case décochée assimilait un paiement non vérifié à une absence de paiement | Sélecteurs à trois états ; les inconnues ne sont pas envoyées comme false |
| 3 — réessai | Une réponse perdue pouvait provoquer une création en double | Clé conservée pour un formulaire identique ; simulation d'une réponse perdue après écriture et réessai sans doublon |
| 3 — cohérence | Limites de texte et noms d'événements divergents du serveur | Champs alignés sur 180/2 000 caractères ; historique traduit ; messages de conflit conservés |

La revue indépendante a contrôlé les frontières HTTP et le stockage : Host/origine, requêtes de formulaire, JSON invalide/doublonné, taille des entrées, traversées de fichiers, états avant approbation, idempotence et gestion des erreurs. Elle n'a trouvé aucun blocage confirmé restant dans ce périmètre après corrections. Cela ne constitue pas un audit de sécurité exhaustif.

## Limites de validation

- **IA réelle non testée :** pas d'appel à un compte fournisseur, pas de mesure de qualité, coût ou latence réelle. Les mocks vérifient seulement le protocole et les contrôles locaux.
- **Connecteurs non testés :** aucun compte mail, bancaire, comptable ou fiscal n'est connecté.
- **Affichage visuel non vérifié :** le navigateur disponible bloque localhost et les téléchargements Chromium n'ont pas fourni une archive exploitable. Ne pas déduire une validation visuelle desktop/mobile d'une inspection de code ou de DOM.
- **Mono-entreprise locale :** pas de validation de production, multi-utilisateur ou multi-tenant, pas d'authentification ni chiffrement applicatif de SQLite.
- **Portée documentaire :** données structurées manuelles, aucun OCR, original PDF, image ou relevé bancaire réellement importé.
- **Périmètre arithmétique :** facture simple à un taux, montants non négatifs à deux décimales. Les avoirs, taux multiples et cas particuliers exigent un traitement spécialisé.
- **Règles réglementaires :** recherche datée et procédures de qualification ; aucun calendrier fiscal universel implémenté ni certification de conformité.

## Rejouer

```bash
python3 scripts/qa.py
npm ci --ignore-scripts
npm run test:ui
```

Le script Python vérifie aussi le catalogue, la présence des trois fichiers web et la syntaxe JS lorsque Node est disponible. La CI dans `.github/workflows/qa.yml` utilise Python 3.11, 3.12 et 3.13, puis un job DOM/API sous Node 24. Le résultat du workflow GitHub doit être consulté après publication ; sa présence ne prouve pas son exécution.

Avant un pilote connecté, appliquer les gates du [backlog](ROADMAP.md) : données isolées, comptes de test, jeux de documents consentis, mesure de revue, qualité réelle du modèle et restauration vérifiée.
