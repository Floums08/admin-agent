# Admin Agent

**Un atelier administratif pour entrepreneurs et TPE : préparer les dossiers, montrer ce qui manque et garder la décision humaine.**

Premier socle développé le 2 octobre 2026, à partir d'une recherche France / Espagne / UE : **38 fonctions administratives, 36 références documentées, 12 skills et 6 familles de spécialistes**. Les recommandations et prix éventuels sont des hypothèses de validation, distinctes des faits sourcés.

**Préparer un premier client : commencer par le [guide de lancement](docs/launch/00-START-HERE.md).** Le dépôt contient maintenant un mode production distinct, ses outils d'exploitation et un parcours d'intégration client. Une instance et une base sont dédiées à une seule entreprise. La publication du code ne signifie pas qu'un hébergement client est déployé ou que la recette de cet environnement est terminée.

**Premier pilote proposé : [collecte et contrôle de factures](docs/launch/08-PILOTE-FACTURES.md).** Le parcours prépare une répétition locale HTTPS avec dix pièces synthétiques, un registre de mesures séparé, puis dix pièces clientes autorisées sur une instance qualifiée. Il précise les étapes des deux premières semaines et la décision de poursuite ; aucun gain de temps ni lancement client n'est déduit des seuls tests techniques.

## Préparer le lancement en production

Le [guide de déploiement](docs/launch/03-DEPLOIEMENT.md) détaille les commandes, dans l'ordre. Il s'adresse au responsable technique d'un serveur Linux dédié au client, avec Docker Compose, un domaine HTTPS et une destination de sauvegarde indépendante.

| Livré dans le dépôt | Fonctionnement |
|---|---|
| Serveur de production | Flask + Waitress, derrière Caddy pour HTTPS ; aucun port applicatif public dans Compose |
| Comptes nominatifs | Mot de passe haché + code TOTP obligatoire ; création et récupération via administration du serveur |
| Permissions | Administrateur : dossiers et export ; opérateur : préparation et revue ; lecteur : consultation |
| Protection des sessions | Cookies Secure/HttpOnly/SameSite, CSRF, expiration, révocation et limitation des tentatives |
| Isolation | Identité client liée à la base ; refus d'une base appartenant à une autre instance |
| Exploitation | Initialisation, contrôle préalable, sauvegarde SQLite cohérente, scripts restic chiffrés et restauration vers une nouvelle cible |
| Reprise sûre | Comptes restaurés désactivés ; renouvellement du mot de passe et du MFA avant réactivation |
| Contrôles | Tests métier, permissions, restauration, parcours navigateur et construction du conteneur dans la CI |

La production utilise les **cinq workflows déterministes**, dont la préparation de notes de frais, complétés par le registre financier, l'import documentaire, l'OCR local et les connecteurs en lecture seule décrits ci-dessous. L'IA externe et les données de démonstration y sont désactivées. Les sept autres skills restent guidées. Le lancement initial est borné à **100 dossiers cumulés par instance**, avec des limites sur la taille des résultats et le nombre d'événements ; une capacité supérieure nécessite une évolution validée.

## Suivre les factures, préparer le financement et les frais

La version **0.5** ajoute une section **Finances** et un parcours **Notes de frais**. Le [guide d'utilisation](docs/launch/09-FINANCE-ET-FRAIS.md) décrit les étapes et la [recherche FR/ES](docs/research/04-finance-expenses.md) explique les choix de contrôle.

**Pour tester :** le [jeu de documents fictifs](docs/launch/10-JEU-TEST-FICTIF.md) génère dix factures, huit reçus de frais, deux relevés CSV et un guide avec corrigé. Il couvre les cas normaux, erreurs de total/date, doublons, paiements partiels, litiges et affacturage indicatif. Aucun import automatique n'est effectué.

| Fonction | Fonctionnement |
|---|---|
| Suivi clients et fournisseurs | Enregistrer une facture contrôlée et validée en interne, confirmer le solde d'ouverture, suivre échéance, solde et règlements partiels ; signaler une source modifiée |
| Rapprochement bancaire | Charger un CSV, examiner l'aperçu puis confirmer l'import ; rapprocher explicitement les opérations et les factures, avec contrôle du sens, de la devise et du disponible ; annulation tracée |
| Affacturage | Préparer les éléments à examiner et simuler avance, réserve, commissions, intérêts et trésorerie nette selon les paramètres saisis ; aucune offre ou éligibilité de financeur présumée |
| OCR de notes de frais | Extraire les propositions du reçu, confirmer les champs et le contexte professionnel, contrôler la politique fournie et les risques de double remboursement ; aucune TVA récupérable ou exécution de remboursement calculée automatiquement |

Les mouvements et allocations restent dans la base propre à l'entreprise. **Une suggestion de rapprochement n'est pas une confirmation et une avance du factor n'est pas un règlement du client.** L'import utilise un export bancaire fourni par l'utilisateur, sans abonnement d'agrégation ni connexion à une banque. Le [CSV fictif](examples/finance-bank.example.csv) permet de préparer un essai ; ses montants ne correspondent à aucune opération réelle. La connexion bancaire directe, les formats bancaires supplémentaires et les écritures dans un logiciel comptable restent à développer.

## Documents, OCR et connecteurs sans API payante

Le [guide OCR et connecteurs](docs/launch/07-OCR-ET-CONNECTEURS.md) contient les prérequis, la configuration privée et les commandes de recette.

| Outil livré | Fonctionnement et limite |
|---|---|
| Import PDF, PNG et JPEG | Original conservé dans la base client, empreinte SHA-256, déduplication ; 5 Mio par fichier, 100 originaux et 100 Mio cumulés |
| Extraction PDF + OCR local | Poppler pour le texte natif ; Tesseract français, espagnol et anglais pour les scans ; 5 pages maximum, option OCR forcé |
| Revue des champs | Proposition avec page, extrait et coordonnées ; correction et confirmation explicites avant création d'un dossier à analyser |
| Dossier local | Collecte bornée de fichiers depuis un répertoire autorisé, sans liens symboliques |
| Import CSV | Correspondance explicite des colonnes ; montants et états inconnus restent à vérifier |
| Nextcloud / WebDAV | Liste et téléchargement en lecture seule avec mot de passe d'application ; serveur HTTPS public autorisé dans la configuration privée |
| Dolibarr | Lecture de factures par API REST et clé dédiée ; import structuré, sans modification distante |

Les connecteurs s'exécutent par **CLI sur l'hôte** : aperçu par défaut, import explicite, aucun envoi ni synchronisation automatique. Les accès à un compte Nextcloud/Dolibarr réel restent à configurer et à tester pour chaque client. L'OCR ne transmet pas les documents à un fournisseur IA ; son service isolé n'a ni accès à Internet, ni base client, ni secrets. Les valeurs reconnues peuvent être fausses : elles ne prouvent ni un paiement ni l'absence de litige.

Ces composants sont des logiciels libres sans facturation API à l'appel dans ce montage. **Serveur, stockage, sauvegardes et maintenance restent à financer.** Les formats XML de facturation électronique, les calculs fiscaux multi-taux et l'OCR de relevés bancaires ne sont pas pris en charge. Le rapprochement utilise le CSV structuré décrit ci-dessus. Voir aussi les [licences et notices](THIRD-PARTY-NOTICES.md).

Documents d'intégration : [qualification et informations à obtenir](docs/launch/01-QUALIFICATION-CLIENT.md), [données et responsabilités](docs/launch/02-DONNEES-ET-RESPONSABILITES.md), [recette client](docs/launch/04-RECETTE-CLIENT.md), [exploitation quotidienne et reprise](docs/launch/05-EXPLOITATION.md), [décision de lancement](docs/launch/06-GO-NO-GO.md). Le [formulaire fictif](examples/client-onboarding.example.json) est à compléter dans un espace privé, jamais dans ce dépôt public.

## Essayer en local — sans clé API

Prérequis : **Python 3.11 ou plus récent**. Aucune bibliothèque Python à installer.

1. Télécharger le dépôt avec **Code → Download ZIP**, puis extraire le dossier ; ou utiliser `git clone https://github.com/Floums08/admin-agent.git`.
2. Ouvrir un terminal dans le dossier contenant ce README.
3. Lancer :

```bash
python3 -m admin_agent --port 8765
```

Sur Windows, si `python3` n'est pas reconnu :

```powershell
py -m admin_agent --port 8765
```

4. Ouvrir **http://127.0.0.1:8765** sur ce même ordinateur.
5. Charger les exemples de démonstration. Ils sont fictifs ; le bouton ne les duplique pas.
6. Ouvrir le dossier avec écart de total, examiner les contrôles, modifier le total, puis relancer l'analyse.
7. Relire un résultat sans blocage et le valider en interne. Aucun message n'est envoyé.
8. Exporter le suivi JSON si souhaité. Arrêter le serveur avec `Ctrl+C`.

Ce mode de démonstration écoute uniquement en local. Il ne doit pas être publié sur Internet ni partagé entre plusieurs entreprises. Pour un client, utiliser exclusivement le mode production et son guide ci-dessus. Les dossiers locaux sont persistés dans une base SQLite exclue du dépôt ; `--db /chemin/base.sqlite3` permet de choisir son emplacement. Une base de démonstration contenant des dossiers ne peut pas être attribuée automatiquement à une instance de production.

## Ce qui est disponible

| Élément | État réel |
|---|---|
| Tableau de bord, recherche et filtres | Fonctionnels sur les dossiers enregistrés |
| Création, correction, analyse et revue | Persistés ; une correction invalide l'ancien résultat |
| Contrôle de facture simple | Vérification décimale HT/TVA/TTC, dates et champs ; un taux, devises à deux décimales |
| Préparation de suivi de créance | Brouillon interne sous conditions ; factures payées/contestées et données incohérentes traitées explicitement |
| Dossier comptable | Index structuré, pièces manquantes et doublons potentiels ; les documents originaux ont un parcours d'import séparé |
| Tri administratif | Qualification indicative à partir du texte |
| Notes de frais | Reçu original, champs confirmés, contexte professionnel, politique fournie et revue interne ; aucun remboursement exécuté |
| Sept autres skills | Checklists guidées et instructions spécialisées ; pas sept automatismes achevés |
| Avis IA optionnel | Adaptateur Responses + contexte borné + sortie contrôlée ; désactivé par défaut |
| Traçabilité | Événements de création, analyse, correction et revue ; export JSON |
| Tests et CI | Suite hors ligne, contrôles de compétences et workflow à chaque changement |

Les données peuvent être saisies, importées par connecteur ou préparées depuis un original après revue de l'extraction. Les connexions directes à une messagerie ou à une banque restent à développer. Aucun client n'a été contacté. Aucune clé API, donnée réelle ou base de travail n'est publiée.

## Agents et compétences

| Famille | Skills |
|---|---|
| Bureau administratif | `admin-triage`, `weekly-brief` |
| Contrôle documentaire | `invoice-check`, `bookkeeping-pack`, `expense-review` |
| Encaissements et trésorerie | `receivables-followup`, `cash-visibility` |
| Échéances et conformité | `deadline-watch`, `compliance-watch` |
| Achats et contrats | `supplier-watch`, `contract-watch` |
| Coordination RH | `hr-onboarding` |

Les skills sont versionnées sous `skills/` pour l'application et réutilisables dans un futur orchestrateur. Elles ne sont pas installées automatiquement dans le compte ChatGPT. Le catalogue décrit leurs entrées, sorties et état d'implémentation.

## Tester l'avis IA facultatif en local

Le mode local fonctionne sans dépense API. Pour tester le mode IA local, configurer côté serveur `ADMIN_AGENT_AI_ENABLED=1`, `OPENAI_API_KEY` et `OPENAI_MODEL` avec un modèle accessible au compte et compatible Responses / Structured Outputs. Le fichier `.env.example` documente ces variables ; l'application locale ne charge pas automatiquement `.env`. **Le serveur de production refuse cette activation dans cette release.**

Ne saisir la clé ni dans le navigateur ni dans un dossier. Après redémarrage, choisir explicitement l'analyse IA du dossier. Son contenu est alors transmis à OpenAI. Utiliser des données synthétiques tant que le cadre de traitement des données réelles n'est pas validé. L'avis IA reste séparé des contrôles déterministes et ne peut approuver un dossier.

Le contexte comprend uniquement la skill sélectionnée, le pays et le dossier courant ; 24 000 octets maximum d'instructions/contexte, sortie limitée à 1 200 tokens. Ce plafond par appel ne constitue pas un budget mensuel. Les tests fournisseur utilisent des réponses simulées ; **aucun appel réel à un modèle n'a été validé dans cette livraison**.

## Documentation à lire

- [Décision produit et périmètre](docs/PRODUCT.md)
- [38 fonctions et sources des besoins](docs/research/01-needs.md)
- [Concurrents, connecteurs et économie hypothétique](docs/research/02-market.md)
- [Cadre France / Espagne / UE et règles proposées](docs/research/03-compliance.md)
- [Architecture technique](docs/ARCHITECTURE.md) et [architecture des skills](docs/skills-architecture.md)
- [Backlog priorisé](docs/ROADMAP.md)
- [Résultats QA, corrections et limites](docs/QA.md)

## Développer et vérifier

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-production.txt
python3 scripts/qa.py
```

La commande contrôle le catalogue et lance les tests Python, y compris les scénarios de production lorsque leurs dépendances sont installées. Si Node est installé, elle vérifie aussi la syntaxe du JavaScript. Aucun compte externe n'est nécessaire pour ces tests. La CI utilise Python 3.11, 3.12 et 3.13 ; le rapport QA distingue les vérifications effectivement exécutées. Les bibliothèques Python sont nécessaires au mode production et à sa QA, pas à la démonstration locale.

Pour les parcours DOM/API : `npm ci --ignore-scripts`, puis `npm run test:ui` et `npm run test:auth-ui`. Pour le navigateur réel : `npx playwright install --with-deps chromium`, puis `npm run test:browser` (Python de l'environnement virtuel actif). Le test crée ses propres données et certificats TLS temporaires. Ces dépendances npm servent uniquement à la QA ; l'application n'en charge aucune dans le navigateur.

Pour tester l'OCR, installer aussi `requirements-ocr.txt`, Poppler, Tesseract et ses modèles `fra`, `spa`, `eng` (commandes dans le guide). Rejouer `npm run test:documents-ui` et `npm run test:documents-browser` pour le nouveau parcours documentaire. Des tests ignorés faute de dépendances ne constituent pas une recette OCR.

La CI construit les deux images Docker et exécute `python scripts/container_smoke.py --image admin-agent:ci --ocr-image admin-agent-ocr:ci`. Un audit des dépendances Python interroge la base publique d'avis de sécurité ; cela ne remplace pas la maintenance du système hôte, des images ni une revue de sécurité de l'environnement déployé.

Lire [AGENTS.md](AGENTS.md) pour la boucle développement → test → QA → contrôle → amélioration. Les cas de compétences sous `data/skill-evals.json` décrivent également des évaluations métier ; un scénario documentaire n'est pas à lui seul un test exécuté ni une certification juridique.
