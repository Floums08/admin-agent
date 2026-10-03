# Pilote : collecter et contrôler des factures

Guide de la version 0.4.0, du 3 octobre 2026. Ce parcours prépare un pilote limité à **une entreprise et au contrôle de factures**, avec collecte, extraction, vérification des champs, analyse et revue humaine. Il commence par une répétition locale sur dix pièces fictives, puis prévoit un lot de dix pièces clientes autorisées sur une instance qualifiée.

Le dépôt fournit des outils et des cas de travail. Il ne prouve ni qu'un client est déployé, ni que l'OCR sera exact sur ses documents, ni qu'un gain de temps a été obtenu. Les rapports de mesure distinguent les observations renseignées des cas non testés. Ils ne remplacent pas la [décision de lancement](06-GO-NO-GO.md).

## 1. Fixer un périmètre mesurable

| Décision | Valeur de départ |
|---|---|
| Entreprise | Une entité juridique, pays FR ou ES explicitement choisi |
| Processus | Collecte et contrôle de factures ; workflow `invoice-check` |
| Source initiale | Dépôt manuel PDF/PNG/JPEG ou dossier local dédié ; ajouter un connecteur distant seulement après sa recette |
| Livrable | Dossier nouveau, analyse de cohérence, anomalies et résultat relu en interne |
| Personnes | Un opérateur pour préparer ; un réviseur métier pour comparer aux originaux et décider ; un responsable technique pour les accès et la reprise |
| Taille | Dix pièces pour la première recette ; **trente dossiers au maximum pour le pilote opérationnel, première recette incluse** |
| Durée de décision | Bilan de première semaine, puis décision de poursuite à la fin de la deuxième semaine |
| Objectif de temps | Seuil convenu par écrit avant le lot ; aucun pourcentage de gain présumé |

Les rôles `admin` et `operator` peuvent techniquement préparer et relire. **La séparation opérateur/réviseur est une règle d'organisation ; le logiciel n'impose pas deux personnes distinctes.** Utiliser des comptes individuels et désigner qui effectue la seconde lecture. Le rôle `reader` permet la consultation mais pas la revue.

Le pilote ne comprend pas l'envoi de messages, le contact de clients, la création d'écritures comptables, les paiements, les déclarations ou la certification fiscale. Les avoirs, acomptes, retenues, plusieurs taux et régimes particuliers sortent du contrôle simple : documenter le blocage et orienter le dossier vers la personne compétente. Un statut « prêt » ne signifie ni « payé » ni « envoyé ».

## 2. Jour 0 : répéter en local avec des données fictives

### Préparer le poste

Les commandes ci-dessous s'exécutent **depuis la racine du dépôt dans un terminal Linux**. Elles ciblent Linux ; WSL2 avec intégration Docker Desktop est un chemin possible sur Windows, à vérifier sur le poste. L'exécution native PowerShell et macOS n'est pas annoncée comme validée. Le serveur de démonstration `python -m admin_agent` ne remplace pas ce parcours : la répétition utilise le serveur authentifié et le worker OCR isolé.

Prévoir Python 3.11 ou plus, un environnement virtuel, Docker opérationnel et Docker Compose **2.24.4 ou plus**. L'override local remplace la publication des ports avec `!override` ; une version antérieure ne convient pas. Les images Docker contiennent Poppler et Tesseract. La génération des exemples sur l'hôte utilise Pillow, fourni par `requirements-ocr.txt`.

Utiliser un chemin Linux sans espaces, par exemple `~/admin-agent`, et un moteur Docker local accessible par socket Unix. Le script refuse un contexte Docker distant : ce parcours doit rester sur le poste de répétition.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-production.txt -r requirements-ocr.txt
docker version
docker compose version
```

### Initialiser l'espace et créer les accès

```bash
python scripts/pilot_local.py init
python -m admin_agent.ops user-add \
  --config runtime/invoice-pilot/client.json \
  --username pilote.admin --role admin
python -m admin_agent.ops user-add \
  --config runtime/invoice-pilot/client.json \
  --username pilote.operateur --role operator
python -m admin_agent.ops user-add \
  --config runtime/invoice-pilot/client.json \
  --username pilote.reviseur --role operator
```

Choisir les mots de passe lors des demandes interactives, puis enrôler le TOTP de chaque compte dans l'application d'authentification de son titulaire. Les éléments d'enrôlement sont des secrets : ne pas les capturer dans une preuve de recette ou un ticket GitHub. Les noms ci-dessus sont réservés à l'exercice ; les comptes clients seront nominatifs.

L'initialisation prépare `runtime/invoice-pilot`, son identité de test, la configuration et les secrets locaux. Ce répertoire est exclu de Git. Il ne faut pas lui attribuer l'identité d'une entreprise réelle ou y mélanger ses pièces. Une relance d'initialisation doit conserver une configuration compatible ; elle n'est pas une commande de remise à zéro de la base.

### Démarrer et vérifier HTTPS

```bash
python scripts/pilot_local.py up
python scripts/pilot_local.py status
python scripts/pilot_local.py certificate
```

Ouvrir **https://pilot.localhost:8443** sur ce poste. Le seul port publié est lié à `127.0.0.1` ; le worker OCR n'a pas de port public. Aucun domaine Internet ou enregistrement DNS tiers n'est créé.

Caddy utilise une autorité locale pour ce certificat. La commande `certificate` exporte uniquement son certificat public vers `runtime/invoice-pilot/tls/pilot-root-ca.crt` et affiche son empreinte. Faire reconnaître cette autorité dans le navigateur ou le magasin de certificats du poste de recette selon sa procédure d'administration. **Le script n'installe pas automatiquement une autorité de confiance.** Ne pas remplacer cette étape par la désactivation du contrôle TLS. Ce certificat local ne constitue pas un certificat public de production.

Vérifier l'identité de test affichée, la connexion avec MFA et la section Documents. Utiliser `status` pour examiner les services. Si le démarrage ou le certificat échoue, résoudre ce problème avant de charger les exemples ; ne pas ouvrir un autre port public pour contourner le problème.

### Générer les dix pièces et la vérité de référence

```bash
python scripts/pilot_fixtures.py --output runtime/pilot-fixtures
```

Le générateur prépare :

- `documents/` : dix pièces fictives, dont un scan PNG et un PDF de deux pages ;
- `expected/manifest.json` : résultats attendus, champs de référence et contexte fictif de revue ;
- `README.md` : description du lot.

Le générateur refuse d'écraser un répertoire de sortie existant. Choisir un nouveau répertoire si une seconde génération est nécessaire. Les exemples sont synthétiques ; ils n'ont aucune valeur comptable et ne mesurent pas la performance sur les factures d'un client.

| Cas | Situation à vérifier | Comportement métier attendu |
|---|---|---|
| `synthetic-fr-001` | Facture simple en PDF texte | Champs à vérifier, analyse `needs_review` puis revue possible si les informations nécessaires sont confirmées |
| `synthetic-fr-002` | Facture simple scannée en PNG | OCR, comparaison à l'image, corrections éventuelles puis analyse `needs_review` |
| `synthetic-fr-003` | Total TTC incohérent | Anomalie de total et `blocked` ; ne pas corriger l'original pour obtenir un résultat vert |
| `synthetic-fr-004` | Montant de TVA incohérent | Anomalie arithmétique et `blocked` |
| `synthetic-fr-005` | Échéance antérieure à l'émission | Incohérence de dates et `blocked` |
| `synthetic-fr-006` | Date ambiguë | Information à clarifier et `blocked` ; aucune interprétation certaine de la date |
| `synthetic-fr-007` | Paiement partiel | Hors périmètre simple et `blocked`, avec conservation du motif et de sa preuve |
| `synthetic-fr-008` | Avoir | Hors périmètre et `blocked`, sans assimiler la pièce à une facture ordinaire |
| `synthetic-fr-009` | Autoliquidation | Hors périmètre et `blocked` ; aucune conclusion fiscale automatique |
| `synthetic-fr-010` | Plusieurs taux et nouvel IBAN en page 2 | Contexte de la seconde page conservé ; hors périmètre et `blocked` |

Le manifeste fait foi pour les valeurs et identifiants exacts du lot généré. Le réviseur le conserve séparément de la saisie de l'opérateur. L'opérateur compare d'abord les propositions avec l'original ; la vérité de référence sert ensuite à relever les erreurs, pas à prétendre que l'OCR les a reconnues correctement.

### Exécuter le parcours complet

Pour chacune des dix pièces :

1. Déposer la pièce dans Documents, avec la langue adaptée. Relever sa référence et son empreinte dans le relevé privé de recette.
2. Lancer l'extraction. Lire **toutes** les pages et télécharger l'original pour comparaison.
3. Comparer numéro, fournisseur, client, dates, HT, taux, TVA, TTC et devise. Corriger seulement la proposition saisie, en conservant le document original.
4. Confirmer chaque champ réellement vérifié. Pour le paiement, utiliser uniquement le contexte fictif explicitement fourni ; sur un dossier réel, une facture ne suffit pas à prouver son état de règlement.
5. Créer le dossier `invoice-check`. Il doit apparaître comme nouveau, sans analyse ou approbation automatique.
6. Analyser, relever le statut **avant approbation** et comparer au résultat attendu. Un document source incohérent peut rester bloqué même si l'OCR l'a parfaitement lu. Le manifeste attend `needs_review` pour les cas 1 et 2 et `blocked` pour les autres ; une approbation ultérieure constitue une étape distincte.
7. Faire relire par le réviseur. Approuver uniquement les dossiers éligibles. Pour une anomalie ou un cas hors périmètre, conserver le blocage et son explication.
8. Renseigner les observations et les temps réellement mesurés dans le registre décrit ci-dessous.

Rejouer aussi un dépôt identique et une tentative de création répétée : aucun nouveau document ou dossier ne doit apparaître. Vérifier la modification d'un dossier déjà analysé : son ancienne analyse et son ancienne revue sont invalidées. Utiliser les tests U01 à U10 et D01 à D06 de la [recette](04-RECETTE-CLIENT.md) pour les contrôles d'accès, la reprise et les limites.

Pour arrêter les services sans effacer les données :

```bash
python scripts/pilot_local.py stop
```

L'arrêt ne constitue pas une suppression de la base, des secrets ou des volumes. Ne pas réutiliser la base de répétition pour un client réel.

## 3. Consigner les résultats sans fabriquer de mesures

Le registre de mesures est distinct de la base métier. Il n'importe pas les factures et ne déduit pas automatiquement le temps humain, l'exactitude des champs ou la décision du réviseur. Les observations sont enregistrées explicitement, puis agrégées.

Créer son répertoire **hors de tout dépôt Git**, par exemple dans un dossier privé du compte utilisateur :

```bash
mkdir -p "$HOME/admin-agent-pilot"
chmod 700 "$HOME/admin-agent-pilot"
python -m admin_agent.pilot init \
  --directory "$HOME/admin-agent-pilot/repetition" \
  --cohort synthetic \
  --manifest runtime/pilot-fixtures/expected/manifest.json
```

Générer la fiche du premier cas ; utiliser un autre identifiant du manifeste et un autre nom de sortie pour les suivants :

```bash
python -m admin_agent.pilot template \
  --directory "$HOME/admin-agent-pilot/repetition" \
  --case synthetic-fr-001 \
  --output "$HOME/admin-agent-pilot/observation.json"
```

Ouvrir ce JSON dans un éditeur, compléter uniquement les faits observés et conserver la version attendue. Pour chaque champ critique, distinguer le résultat de l'extraction (`correct`, `incorrect`, `missing`, `correct_abstention`, `not_tested`) de sa revue (`confirmed`, `corrected`, `unresolved`, `not_tested`). Une valeur corrigée par l'opérateur ne transforme pas l'extraction initiale en extraction correcte.

Utiliser `correct_abstention` uniquement si le réviseur confirme, preuve à l'appui, qu'une absence ou une ambiguïté justifie de ne pas proposer de valeur. Une donnée lisible dans la facture mais manquée par l'OCR reste `missing`. Les abstentions correctes sont comptées séparément de l'exactitude des valeurs reconnues.

Renseigner une référence de réviseur et une référence de preuve dans l'espace privé. `observed_result` correspond au statut après analyse relevé à l'étape 6. Le statut d'observation `pass` signifie que le scénario a été vérifié, **pas que la facture est prête** : une incohérence attendue peut produire `blocked` et un scénario réussi. Un champ ambigu non résolu reste tel quel ; le réviseur peut confirmer l'abstention sans inventer sa valeur. Les cas hors périmètre ne sont pas ajoutés aux réussites nominales.

Les temps sont facultatifs : une absence de mesure reste une absence de mesure. Pour une comparaison, utiliser `measurement: "observed"` et des durées décimales en secondes. Le temps assisté comprend la revue ; la revue comprend les corrections. **Ne pas additionner une seconde fois ces sous-durées.** Marquer `paired_comparison: true` seulement si la durée manuelle de référence et la durée assistée ont réellement été mesurées sur une comparaison appariée.

Mesurer la référence avant de regarder les propositions, avec le même périmètre de travail. Signaler l'effet d'apprentissage si une même personne traite deux fois la même pièce. Inclure la collecte, la saisie, le contrôle et les corrections nécessaires dans le périmètre convenu ; relever séparément les attentes ou interruptions si elles ne font pas partie du temps actif. Dix documents ne suffisent pas à garantir une économie sur tous les documents futurs.

Enregistrer la fiche, puis produire les rapports :

```bash
python -m admin_agent.pilot record \
  --directory "$HOME/admin-agent-pilot/repetition" \
  --record "$HOME/admin-agent-pilot/observation.json"
python -m admin_agent.pilot report \
  --directory "$HOME/admin-agent-pilot/repetition" \
  --format json --output "$HOME/admin-agent-pilot/rapport-repetition.json"
python -m admin_agent.pilot report \
  --directory "$HOME/admin-agent-pilot/repetition" \
  --format csv --output "$HOME/admin-agent-pilot/rapport-repetition.csv"
```

Les rapports agrégés ne contiennent pas les valeurs de factures, identifiants de dossiers, références privées ou notes individuelles. Ils affichent la couverture et les mesures disponibles ; **un rapport ne donne jamais à lui seul l'autorisation de lancer un client**. Conserver les observations source pour expliquer les agrégats. Utiliser des noms de sortie distincts pour les bilans suivants et respecter les refus d'écrasement et de version signalés par les commandes.

Pour corriger une observation déjà enregistrée, générer un nouveau modèle du même cas sous un autre nom : il porte la version actuelle à reprendre lors du nouvel enregistrement. La cohorte doit être créée dans un répertoire neuf dont le parent existe déjà ; les fiches et rapports restent dans des répertoires privés. Le registre est alimenté par la personne qui mesure et vérifie : ni le manifeste de référence ni une génération réussie des exemples ne remplissent automatiquement les observations.

## 4. Jour 1 : préparer le lot client autorisé

Avant toute pièce réelle, obtenir et consigner dans un espace privé :

| Élément | Décision attendue |
|---|---|
| Identité | Raison sociale, pays FR/ES, entité concernée et interlocuteur habilité |
| Source | Dépôt manuel, dossier local, CSV, Nextcloud ou Dolibarr déjà disponible ; volume et formats représentatifs |
| Autorisation des pièces | Dix documents autorisés et minimisés, avec références stables ; résultats attendus établis par le réviseur avant utilisation du logiciel |
| Accès | Personnes nommées, rôles, MFA ; compte dédié limité à la lecture pour une source distante, révocation prévue |
| Environnement | Hébergement, domaine HTTPS, région, responsables techniques et budget d'exploitation |
| Traitement | Instructions, conservation, fournisseurs, retour des données et procédure d'incident convenus |
| Mesure | Définition des temps, seuil de productivité à examiner, critères d'erreur critique, date de bilan et décideur |

Compléter le [formulaire client](../../examples/client-onboarding.example.json) hors du dépôt. Préparer ensuite **une nouvelle instance** selon le [déploiement de production](03-DEPLOIEMENT.md). Son identité, sa base, ses secrets, son domaine et sa sauvegarde sont propres à ce client. Ne pas publier `compose.pilot.yaml` sur Internet : le lancement réel utilise le parcours de production et sa configuration HTTPS publique.

Avant les dix pièces, réussir la recette technique sur cette instance : comptes et permissions, révocation, disponibilité OCR, original protégé, sauvegarde chiffrée indépendante et restauration. L'autorité TLS locale de la répétition et la sauvegarde restée sur le poste de test ne satisfont pas ces conditions.

Pour une collecte par connecteur, suivre [le guide OCR et connecteurs](07-OCR-ET-CONNECTEURS.md) : aperçu d'abord, examen du lot, puis `--import` explicite. Tester le rejeu et la révocation sur le compte effectivement retenu. Un compte Nextcloud ou Dolibarr doit être limité sur la source ; utiliser un export local autorisé si l'intégration disponible ne convient pas. Aucune collecte automatique, aucun accès bancaire ou mail n'est activé par ce pilote.

Créer un registre client distinct du registre synthétique :

```bash
python -m admin_agent.pilot init \
  --directory "$HOME/admin-agent-pilot/client-recette" \
  --cohort client --cases 10 --country FR
```

Remplacer `FR` par `ES` uniquement selon l'entité choisie. Ce registre ne configure ni le serveur ni son pays : il décrit le lot d'observation. Ne pas réutiliser le manifeste synthétique comme vérité d'un client réel. Garder le relevé des références et valeurs réelles dans l'espace privé autorisé.

## 5. Semaines 1 et 2 : mesurer, corriger et décider

| Moment | Travail | Preuve conservée |
|---|---|---|
| Jour 0 | Répétition fictive, formation et première restauration | Version testée, scénarios exécutés, observations synthétiques et écarts |
| Jour 1 | Qualification, instance client et autorisation des dix pièces | Configuration approuvée, personnes habilitées, accès et recette technique |
| Semaine 1 | Traitement des dix pièces autorisées, comparaison au travail manuel et revue quotidienne des anomalies | Résultats par champ, temps observés, corrections, blocages et causes |
| Fin de semaine 1 | Classer les écarts et décider d'une correction ciblée ou d'un arrêt | Backlog ordonné par risque, fréquence puis temps perdu ; décision datée |
| Semaine 2 | Rejouer les régressions après correction et utiliser des pièces nouvelles ; élargir seulement après accord | Comparaison avant/après à périmètre comparable, lot de réserve et nouveau bilan |
| Fin de semaine 2 | Poursuivre, réduire le périmètre ou arrêter | Décision, preuves, réserves, responsables et prochaine échéance |

Ne pas dépasser **trente dossiers métier cumulés pour ce pilote client**, premier lot de dix inclus. Ce plafond de conduite du pilote est plus bas que la capacité technique de **cent dossiers cumulés par instance** ; il n'est pas un nouveau quota logiciel et ne se réinitialise pas à la semaine. Surveiller également les cent originaux, cent Mio d'originaux et vingt Mio d'extractions : une limite peut arriver avant les trente dossiers. Les données de recette dans l'instance consomment la capacité. Aucun archivage ou effacement automatique ne la libère.

Pour élargir le lot, préparer un registre correspondant aux cas supplémentaires et rapprocher les inventaires sans recompter la même pièce. Les registres sont immuables dans leur périmètre : ne pas réécrire une cohorte passée pour faire disparaître les échecs. Le total du pilote doit additionner les dossiers réellement distincts de tous ses lots, y compris ceux restés bloqués.

## 6. Conditions pour poursuivre avec un client

La poursuite exige des preuves couvrant simultanément :

- **Sécurité et exploitation** : aucun blocage de sécurité, d'isolation, d'accès, de sauvegarde ou de restauration ; tests obligatoires effectivement exécutés sur l'instance retenue.
- **Fidélité et revue** : original disponible, identité client correcte, champs critiques confirmés ou corrigés avec trace ; aucun champ incertain présenté comme certain ; exceptions exclues ou résolues par la personne compétente.
- **Comportement métier** : anomalies connues détectées, dossiers bloquants non approuvés, contexte particulier conservé après correction ; aucune action externe effectuée.
- **Capacité et charge** : volumes compatibles avec les plafonds, responsable de chaque anomalie et temps humain complet mesuré sur les comparaisons disponibles.
- **Valeur** : seuil de temps ou de charge convenu avant le lot, puis examiné à partir des mesures réelles. Un gain absent ou insuffisant entraîne ajustement ou arrêt, pas une garantie rétrospective.
- **Décision** : bilan signé ou accepté selon le processus convenu et [dossier de lancement](06-GO-NO-GO.md) complété. Un test obligatoire non exécuté reste bloquant.

Une erreur critique déclenche arrêt du flux concerné, correction, test de non-régression et nouvelle recette. Prioriser d'abord les mauvais montants, dates, identités, permissions et pertes de preuves ; ensuite la qualité de reconnaissance et le temps de correction ; enfin les améliorations de confort. Le bilan doit montrer aussi les abstentions et exclusions, sans les transformer en réussite d'automatisation.

## Informations nécessaires pour ouvrir le premier vrai pilote

1. **Entreprise et pays** : une entité FR ou ES, activité, volume estimé et responsable métier.
2. **Source des factures** : fichiers disponibles ou logiciel existant, formats, qualité des scans et possibilité d'obtenir dix pièces autorisées.
3. **Hébergement et domaine** : serveur ou fournisseur retenu, domaine souhaité, accès technique et destination indépendante de sauvegarde.
4. **Personnes et mesure** : opérateur, réviseur, responsable technique, disponibilité pour la recette et critère de gain à convenir.

Ces informations permettent de configurer et de qualifier l'instance. Aucun message à un client, compte distant ou achat n'est nécessaire pour la répétition synthétique.

## Références techniques

- [Docker Compose — fusion des fichiers et `!override`](https://docs.docker.com/reference/compose-file/merge/) : remplacement explicite des ports, disponible à partir de Compose 2.24.4.
- [Caddy — HTTPS local](https://caddyserver.com/docs/automatic-https#local-https) : autorité locale et confiance du poste distinctes d'un certificat public.
- [Rapport QA du dépôt](../QA.md) : vérifications effectivement exécutées et limites ; consulter la version correspondant au commit utilisé.
