# Admin Agent — marché, concurrence et architecture proposée

Recherche au 2 octobre 2026. Périmètre : entrepreneurs et TPE en France et en Espagne. Les capacités ci-dessous sont décrites par les éditeurs ; elles n'ont pas été testées sur des comptes clients. Les recommandations, priorités et prix sont des hypothèses de conception à valider, pas des résultats commerciaux.

## 1. Décision produit recommandée

Créer un **service de préparation administrative avec un cockpit d'exceptions** : chaque dossier arrive avec ses pièces, ses contrôles, les informations manquantes et la prochaine décision à prendre. L'entrepreneur retrouve un résultat exploitable ; son expert-comptable ou sa gestoría garde son rôle sur les sujets relevant de son expertise.

La collecte de factures, les justificatifs, la facturation et la collaboration comptable sont déjà largement couverts par Pennylane, Indy, Tiime et Holded [M01, M03, M04, M05]. Qonto expose ses données et certaines actions à des assistants IA via MCP [M02]. Odoo documente des agents utilisant des outils et des sources [M06]. **« Nous avons de l'OCR et un chatbot » ne constitue donc pas une différence suffisante.** C'est une inférence stratégique à partir des fonctionnalités observées, pas la preuve qu'aucun concurrent ne gère les exceptions.

L'opportunité à tester est le travail entre les outils : comprendre une demande reçue, retrouver la bonne pièce, repérer ce qui manque, réconcilier les statuts et préparer un dossier pour décision. Il faut mesurer ce travail chez les futurs utilisateurs ; les pages marketing ne prouvent ni son volume ni leur volonté de payer.

## 2. Comparaison de la concurrence

| Solution | Capacités vérifiées dans une source éditeur | Conséquence pour Admin Agent | Limite de la recherche |
|---|---|---|---|
| Pennylane | Facturation, gestion des achats, centralisation de justificatifs, trésorerie, comptabilité et intégrations [M01]. | S'intégrer à la source financière ; apporter la préparation de dossiers et le suivi des exceptions. | Aucun test des plans, de la disponibilité par compte ou de la qualité d'extraction. |
| Qonto | MCP pour consulter les dépenses, les factures clients et les retards ; certaines actions sont accessibles avec confirmation et permissions du rôle [M02]. | Connecteur ou partenaire potentiel, mais concurrence directe sur l'assistant financier. Une interface conversationnelle seule sera facile à substituer. | La présence d'un MCP ne garantit pas que toutes les opérations souhaitées sont exposées. |
| Indy | Devis/factures, comptabilité, notes de frais, justificatifs et déclarations ; certaines fonctions sont gratuites [M03]. | Éviter une proposition coûteuse de simple facturation pour indépendants peu complexes. | Accès API et conditions d'intégration non établis par cette recherche. |
| Tiime | Centralisation des achats et justificatifs, accès partagé et collaboration avec le comptable [M04]. | Le dossier comptable doit réduire les exceptions et s'adapter aux habitudes du cabinet. | Ne pas promettre un connecteur natif sans vérifier les possibilités réelles. |
| Holded | Facturation, comptabilité, banques, CRM, projets, inventaire et RH dans une même plateforme ; accès de l'asesoría [M05]. | Pour l'Espagne, choisir quelques processus incomplets dans l'installation du client au lieu de répliquer l'ERP. | Ni performance des automatismes ni disponibilité de chaque fonction selon offre vérifiées. |
| Odoo | Agents IA configurables, consignes, sujets, sources et interaction avec les outils Odoo [M06]. | Une bibliothèque de SKILLs génériques ne suffit pas ; privilégier les preuves, les tests et une installation accompagnée. | Version, modules et droits doivent être contrôlés pour chaque instance. |
| Lindy | Assistant transversal, routines, brouillons, comptes rendus, intégrations et compétences réutilisables présentés par l'éditeur [M12]. | Concurrence horizontale sur l'assistant généraliste. La spécialisation opérationnelle FR/ES doit être concrète. | Aucune conformité administrative locale spécifique démontrée ici ; absence de preuve n'est pas preuve d'absence. |

Aucun tarif concurrent n'est figé dans ce rapport : offres, promotions, crédits, périmètres et options rendent les comparaisons rapides trompeuses. Comparer à terme le coût total du processus : abonnement existant + intégration + contrôle humain + traitement des erreurs.

## 3. Segment initial et promesse à tester

**Hypothèse de départ :** entreprises de services B2B de 1 à 10 personnes, sans responsable administratif dédié, déjà équipées d'une messagerie et d'un logiciel de facturation/comptabilité. Exemple adapté au réseau du fondateur : agences, cabinets de conseil, petits bureaux d'études et prestataires techniques.

Ce choix réduit la variété opérationnelle initiale. Les restaurateurs, commerces à stocks, entreprises multi-pays et secteurs nécessitant de nombreuses données sensibles pourront être étudiés ensuite. Il s'agit d'une décision de périmètre proposée, pas d'une conclusion statistique sur leur attractivité.

Promesse proposée : **« Vos dossiers administratifs sont préparés ; vous voyez ce qui est prêt, ce qui manque et ce qui demande votre décision. »** Mesure centrale : minutes actives réellement économisées par dossier correctement préparé, après déduction du temps de vérification et de correction.

Deux packs de contexte distincts : France et Espagne. Ils contiennent pays de l'entité, forme juridique, régime fourni et validé, périodicités, calendrier établi, comptable référent et sources datées. Ne pas traduire mécaniquement les règles françaises pour les appliquer à une entreprise espagnole.

## 4. Processus spécialisés à développer par priorité

Priorités de conception, à confirmer par observation de dossiers réels consentis. L'importance perçue n'est pas encore mesurée.

| Ordre | SKILL / processus | Entrées | Résultat utile | Frontière de décision |
|---|---|---|---|---|
| P0 | Qualifier la demande administrative | Message ou document importé, profil entreprise | Type, urgence expliquée, entité, références, propriétaire proposé | Doute sur l'entité ou document illisible : demander clarification |
| P0 | Contrôler les pièces fournisseurs | Facture, commande, preuve de livraison si disponible | Extraction sourcée, doublon possible, écarts et pièces manquantes | Aucune approbation de paiement ; changement d'IBAN à contrôler humainement |
| P0 | Préparer le dossier mensuel du comptable | Factures, justificatifs, export transactions | Inventaire, rapprochements proposés, liste des exceptions et export | Pas de qualification fiscale définitive ou de comptabilisation autonome |
| P0 | Surveiller échéances et contrats | Contrat fourni, échéancier validé | Événement avec clause/page source, date et action proposée | Ambiguïté sur préavis ou date : escalade |
| P1 | Préparer les suivis d'impayés | Factures, paiements à jour, litiges | Priorisation et brouillon avec montant restant vérifié | Aucun envoi ; litige/avoir/paiement récent bloque la relance standard |
| P1 | Préparer devis et factures | Bon de commande, prestation validée, tarifs | Brouillon contrôlé dans un format exploitable | Validation de prix, TVA et engagement commercial par responsable |
| P1 | Préparer notes de frais | Reçus et politique de dépenses | Pièces classées, contrôles et exceptions | Remboursement et cas fiscaux non évidents soumis à validation |
| P1 | Préparer renouvellements et abonnements | Contrats, factures, dates | Liste échéances, variations de montant, brouillons de résiliation | Aucune résiliation exécutée automatiquement |
| P2 | Préparer variables de paie | Données validées et autorisations dédiées | Fichier de préparation et incohérences | Accès restreint ; aucune paie calculée ou transmise sans spécialiste |
| P2 | Préparer dossiers assurance, financement, aide ou appel d'offres | Checklist versionnée et documents | Dossier de pièces et écarts de complétude | Éligibilité, déclarations sur l'honneur et dépôt restent humains |

Pour cette session et le socle initial : **aucun e-mail, aucun message client, aucun contact externe**, même si un texte est prêt. Un brouillon est un artefact local, pas un brouillon créé implicitement dans une messagerie connectée.

## 5. Architecture d'agents recommandée

Un orchestrateur de dossiers choisit une compétence étroite ; un moteur déterministe gère les règles de statut, les contrôles chiffrés et les permissions. Éviter que plusieurs agents réécrivent librement le même dossier.

États proposés : `received`, `needs_information`, `prepared`, `needs_review`, `approved_internal`, `exported`, `failed`. `approved_internal` signifie validation du dossier dans le produit, jamais paiement, signature, envoi ou déclaration effectuée. Chaque transition possède une raison et une trace.

Chaque exécution doit conserver : entreprise, dossier, compétence/version, sources/version, horodatage, données extraites, contrôles réalisés, anomalies, permissions utilisées, coût mesuré, sortie et corrections humaines. Distinguer un fait extrait, une règle appliquée, une proposition et une donnée manquante dans le schéma de résultat.

**Contrat minimal d'une SKILL :** déclencheurs ; exclusions ; entrées typées ; préconditions ; sources requises ; outils autorisés ; étapes ; critères d'arrêt ; résultat structuré ; cas limites ; scénarios d'évaluation ; responsable de validation ; date de révision. Les permissions doivent être contrôlées en code côté serveur, pas uniquement décrites en prose.

Séparer les responsabilités techniques :

- Extraction et classement assistés par modèle ; réponse JSON validée contre un schéma.
- Montants, taxes configurées, dates, comparaisons et doublons contrôlés par fonctions déterministes.
- Documents, e-mails et pages externes traités comme données non fiables ; leurs instructions ne deviennent pas des autorisations.
- Aucune clé ou donnée personnelle dans les SKILLs, journaux publics ou dépôt ; secrets propres au connecteur et au locataire.
- Un identifiant d'idempotence et un verrou de dossier empêchent qu'un réessai crée deux actions ou deux exports.
- Factures et écritures officielles restent dans le logiciel métier qui les gère. La base du produit conserve les références et l'état de préparation.

Ces points sont des exigences proposées pour ce produit, non une description d'une implémentation déjà terminée.

## 6. Connecteurs : ordre et preuve de faisabilité

| Étape | Connecteur | Ce qui est établi | Ce qui reste à vérifier avant activation |
|---|---|---|---|
| MVP | Imports JSON/CSV et documents fournis | Aucun compte externe nécessaire ; permet de tester le contrat de données | Formats, erreurs, limites de volume et protection des fichiers |
| Pilote FR | Pennylane en lecture seule | Documentation de scopes distincts pour factures clients/fournisseurs et transactions [M07] | Consentement OAuth, droits exacts, abonnement, pagination, limites et fraîcheur |
| Pilote FR/ES selon client | Qonto | Offre MCP documentée, liée aux permissions du rôle [M02] | Liste effective des outils ; filtrage strict en lecture ; possibilités API si nécessaire |
| Pilote ES | Holded | Référence REST publique pour factures, pièces jointes, contacts et autres objets [M08] | Version réellement disponible au compte, mode d'authentification, scopes, limites et compte de test |
| Après validation demande | Odoo | JSON-2 documenté à partir de la version 19 ; accès API externe lié à l'offre Custom dans la documentation tarifaire citée par Odoo [M09] | Hébergement, version, modules, règles d'accès et contrat exact du client |
| Après cadrage données | Messagerie + stockage du client | Connecteurs à sélectionner et documenter spécifiquement | OAuth en lecture seule, sous-dossier autorisé, isolation, rétention et pièces jointes |
| Opportunité ultérieure | Indy / Tiime | Fonctionnalités produit confirmées [M03, M04] | Aucun accès API supposé ; commencer par un export autorisé si nécessaire |

Pas de scraping de portails ni de simulation de clics pour contourner un manque d'API. Le connecteur retourne toujours l'heure de récupération, l'identifiant de source et les éventuelles limites. Un état « payé » ou « ouvert » périmé ne doit pas déclencher une conclusion ferme.

## 7. Context engineering et coût maîtrisé

Anthropic recommande de traiter le contexte comme une ressource limitée : outils précis, références légères, récupération au moment utile et conservation structurée de l'état [M10]. Application proposée ici :

1. Charger en permanence seulement le contrat global de sécurité et les métadonnées des compétences.
2. Sélectionner une compétence avec type de document, pays, état du dossier et objectif ; ne pas charger toute la bibliothèque.
3. Charger uniquement le profil de l'entreprise et les règles nécessaires au dossier courant.
4. Retrouver les passages utiles avec leur page, identifiant et version ; conserver le document complet hors contexte.
5. Résumer l'avancement dans un état structuré avec décisions, inconnues et références ; éviter l'historique conversationnel illimité.
6. Cacher les résultats d'extraction par hash documentaire et version du parseur ; recalculer si l'un change.
7. Confier les contrôles simples au code ; ne solliciter le modèle plus coûteux que pour les ambiguïtés qui le justifient.

Budgets initiaux proposés, à mesurer plutôt qu'à promettre : une limite d'entrée par compétence, une limite de sortie, un maximum de deux tentatives et une limite de dépense par dossier configurée. En dépassement : dossier incomplet visible et reprise humaine, pas boucle silencieuse infinie. Le budget monétaire doit être calculé avec le modèle et son tarif effectifs au moment de l'exécution. Aucun coût de modèle n'a été estimé sur une exécution réelle ici.

## 8. Boucle de développement, tests et QA

La documentation d'Anthropic recommande de combiner des évaluations déterministes, des évaluateurs par modèle lorsque nécessaire et des contrôles humains [M11]. Le plan ci-dessous est notre proposition de validation :

1. Constituer un premier jeu de 50 cas synthétiques FR/ES avec réponses attendues, puis un lot séparé de cas réels consentis et anonymisés.
2. Tester chaque correction sur le cas d'échec et sur la suite existante ; figer un lot de réserve pour éviter l'ajustement aux seuls exemples connus.
3. Vérifier les montants et identifiants exactement ; mesurer les erreurs de dates, les doublons manqués, les preuves manquantes et les escalades injustifiées.
4. Tester les fautes OCR, factures multi-pages, devis pris pour factures, avoirs, paiements partiels, formats de dates FR/ES, documents contradictoires et pièces hors entité.
5. Tester injections dans les documents, accès entre entreprises, faux destinataires, manipulation d'IBAN et demandes explicites d'envoi interdites.
6. Réviser humainement les dossiers et compter les minutes de correction. Une extraction correcte mais inutilisable n'est pas un succès opérationnel.
7. Prioriser par gravité × fréquence × effort évité ; réparer d'abord fuite de données/action interdite, puis erreur monétaire, puis blocage fréquent, puis ergonomie.

Gates proposés avant pilote connecté : zéro action externe interdite dans la suite ; zéro accès inter-entreprises ; référence justificative pour chaque donnée critique affichée ; blocage explicite des champs critiques inconnus ; restauration et reprise des dossiers après échec. **Zéro échec observé dans des tests ne prouve pas un risque nul en production.**

Indicateurs : taux de dossiers utilisables après revue, taux d'erreurs critiques, minutes nettes économisées, proportion d'exceptions, coût complet par dossier, latence au 95e percentile et volume de corrections par compétence/version. Les objectifs chiffrés métier seront définis après la première mesure de référence.

## 9. Offre et économie : hypothèses à valider

Vendre un pilote limité au processus complet, puis une récurrence à volume défini. Les prix ci-dessous sont des propositions de test, sans validation de disposition à payer :

| Offre expérimentale | Hypothèse HT | Périmètre à contractualiser |
|---|---:|---|
| Pilote de 4 semaines | 390–690 € | Un processus, une entité, jusqu'à 50 dossiers, revue et bilan |
| Mise en place | 600–1 500 € | Une source métier, import initial, configuration, contrôles et formation |
| Suivi mensuel | 149–349 €/mois | Volume et minutes de revue inclus plafonnés, supplément connu à l'avance |

Ne pas promettre de traitement illimité. À titre purement illustratif, à 249 €/mois, 100 dossiers nécessitant chacun 2 minutes de contrôle représentent 3 h 20 ; à une hypothèse de coût interne de 35 €/h, cela consomme 116,67 € avant modèles, hébergement, support et acquisition. À 5 minutes par dossier, la revue seule atteint 291,67 € : l'offre n'est plus viable. Cette simulation montre que la métrique économique décisive est le temps humain résiduel, pas uniquement le coût des tokens.

Pour un fondateur seul, commencer avec 3 à 5 pilotes, un seul connecteur financier et deux compétences stabilisées. Le support, les demandes hors périmètre et les variantes documentaires doivent être comptés. Ne pas transformer une bibliothèque de compétences en engagement de prise en charge de toute l'administration.

## 10. Sources primaires et traçabilité

Toutes consultées le 2 octobre 2026. « Vérifié » signifie contenu lu dans une source de l'éditeur, pas fonctionnalité testée. Les affirmations commerciales de productivité et les nombres d'utilisateurs ne sont pas utilisés comme preuve indépendante.

| ID | Source et URL exacte | Usage dans le rapport |
|---|---|---|
| M01 | [Pennylane — plateforme française](https://www.pennylane.com/fr) | Périmètre financier et gestion documentaire |
| M02 | [Qonto — MCP](https://qonto.com/fr/ai/mcp) | Assistant financier, connexion IA et permissions |
| M03 | [Indy — présentation officielle](https://wikicompta.indy.fr/fr/articles/9786735-indy-c-est-quoi) | Périmètre produit pour indépendants, article daté du 10 août 2026 |
| M04 | [Tiime — achats](https://www.tiime.fr/achats) | Justificatifs et collaboration comptable |
| M05 | [Holded — fonctionnalités](https://www.holded.com/es/funcionalidades) | Périmètre de gestion en Espagne |
| M06 | [Odoo — source officielle des agents IA, version 19](https://github.com/odoo/documentation/blob/19.0/content/applications/productivity/ai/agents.rst) | Agents, sources et configuration ; dépôt officiel lu en remplacement de la page documentaire non accessible lors de l'ouverture |
| M07 | [Pennylane — scopes API](https://pennylane.readme.io/docs/v2-scopes) | Lecture seule par type de ressource |
| M08 | [Holded — référence API](https://www.holded.com/developers/api-reference) | Faisabilité documentaire des intégrations |
| M09 | [Odoo — source officielle JSON-2, version 19](https://github.com/odoo/documentation/blob/19.0/content/developer/reference/external_api.rst) | API externe, droits et conditions de disponibilité ; dépôt officiel lu en remplacement de la page documentaire non accessible lors de l'ouverture |
| M10 | [Anthropic — Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | Principes de contexte et récupération progressive, publié le 29 septembre 2025 |
| M11 | [Anthropic — Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) | Principes d'évaluation, publié le 9 janvier 2026 |
| M12 | [Lindy — présentation produit](https://www.lindy.ai/) | Concurrence des assistants transversaux et compétences |

Questions encore ouvertes : préférence des utilisateurs entre logiciel et service géré ; fréquence réelle des dossiers pénibles ; coût de leur solution actuelle ; coût d'acquisition ; accès aux API selon les contrats ; prise en charge FR/ES exacte des connecteurs ; responsabilités de revue ; exigences de conservation et d'hébergement de chaque client. Ces inconnues sont des entrées du pilote, pas des fonctionnalités à annoncer comme acquises.
