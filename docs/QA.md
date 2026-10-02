# Contrôle qualité — version initiale

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
