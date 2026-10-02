# Admin Agent

**Un atelier administratif pour entrepreneurs et TPE : préparer les dossiers, montrer ce qui manque et garder la décision humaine.**

Premier socle développé le 2 octobre 2026, à partir d'une recherche France / Espagne / UE : **38 fonctions administratives, 36 références documentées, 12 skills et 6 familles de spécialistes**. Les recommandations et prix éventuels sont des hypothèses de validation, distinctes des faits sourcés.

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

Le pilote écoute uniquement en local. Il ne doit pas être publié sur Internet ni partagé entre plusieurs entreprises. La publication GitHub porte sur le code, pas sur un SaaS opérationnel. Les dossiers sont persistés dans une base SQLite locale exclue du dépôt ; `--db /chemin/base.sqlite3` permet de choisir son emplacement.

## Ce qui est disponible

| Élément | État réel |
|---|---|
| Tableau de bord, recherche et filtres | Fonctionnels sur les dossiers enregistrés |
| Création, correction, analyse et revue | Persistés ; une correction invalide l'ancien résultat |
| Contrôle de facture simple | Vérification décimale HT/TVA/TTC, dates et champs ; un taux, devises à deux décimales |
| Préparation de suivi de créance | Brouillon interne sous conditions ; factures payées/contestées et données incohérentes traitées explicitement |
| Dossier comptable | Index structuré, pièces manquantes et doublons potentiels ; pas d'import d'originaux |
| Tri administratif | Qualification indicative à partir du texte |
| Huit autres skills | Checklists guidées et instructions spécialisées ; pas huit automatismes achevés |
| Avis IA optionnel | Adaptateur Responses + contexte borné + sortie contrôlée ; désactivé par défaut |
| Traçabilité | Événements de création, analyse, correction et revue ; export JSON |
| Tests et CI | Suite hors ligne, contrôles de compétences et workflow à chaque changement |

Les données sont saisies ou fournies sous forme JSON. **OCR, import PDF/images, connexion mail, banque et logiciel comptable restent à développer.** Aucun client n'a été contacté. Aucune clé API, donnée réelle ou base de travail n'est publiée.

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

## Activer l'avis IA facultatif

Le mode local fonctionne sans dépense API. Pour tester le mode IA, configurer côté serveur `ADMIN_AGENT_AI_ENABLED=1`, `OPENAI_API_KEY` et `OPENAI_MODEL` avec un modèle accessible au compte et compatible Responses / Structured Outputs. Le fichier `.env.example` documente ces variables ; l'application ne charge pas automatiquement `.env`.

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
python3 scripts/qa.py
```

La commande contrôle le catalogue et lance tous les tests Python. Si Node est installé, elle vérifie aussi la syntaxe du JavaScript. Aucun compte externe n'est nécessaire. La CI utilise Python 3.11, 3.12 et 3.13 ; le rapport QA distingue les versions réellement exécutées localement.

Pour les tests de parcours DOM/API supplémentaires (Node 24 utilisé lors de la validation) : `npm ci --ignore-scripts`, puis `npm run test:ui`. Cette dépendance sert uniquement au développement ; elle n'est pas nécessaire pour utiliser l'application. Ces tests ne remplacent pas une vérification visuelle dans un navigateur.

Lire [AGENTS.md](AGENTS.md) pour la boucle développement → test → QA → contrôle → amélioration. Les cas de compétences sous `data/skill-evals.json` décrivent également des évaluations métier ; un scénario documentaire n'est pas à lui seul un test exécuté ni une certification juridique.
