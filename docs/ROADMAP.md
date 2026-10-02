# Backlog priorisé

Ordre initial de conception, à revoir avec les erreurs observées. Statut au 2 octobre 2026. Les estimations sont qualitatives et ne constituent pas un devis.

| Priorité | Évolution | Motif | Critères de sortie | Effort relatif |
|---|---|---|---|---|
| P0 avant données réelles partagées | Authentification, rôles et isolation des entreprises | La version initiale est locale et mono-entreprise | Tests d'accès inter-entreprises, sessions et accès pièce par pièce | Élevé |
| P0 | Import réel de PDF/images avec extraction sourcée | Éviter la ressaisie qui limite la valeur actuelle | Chaque champ critique lié à page/zone ; erreurs OCR explicites ; originaux conservés | Élevé |
| P0 | Correction assistée des champs extraits | La revue doit être rapide et traçable | Image + champ côte à côte, historique et réanalyse après changement | Moyen |
| P0 | Évaluation IA réelle sur lot indépendant | Les mocks valident l'intégration, pas la qualité d'un modèle | Résultats FR/ES, erreurs critiques, coût et latence mesurés, pas d'actions externes | Moyen |
| P0 | Sauvegarde/restauration et conservation | Pas de données réelles sans reprise testée | Sauvegarde chiffrée, restauration vérifiée, politique validée par type de donnée | Moyen |
| P1 | Rapprochement et règlements partiels | Ne pas préparer de relance sur un solde périmé | Avoirs, paiements partiels, fraîcheur et ambiguïtés couverts par tests | Élevé |
| P1 | Un premier connecteur en lecture seule | Réduire la collecte manuelle | OAuth/scopes minimaux, pagination, reprise et révocation testées | Élevé |
| P1 | Export métier pour un cabinet pilote | Le JSON ne suffit pas à l'exploitation comptable | Format accepté par le professionnel, références et pièces vérifiées | Moyen |
| P1 | Contrats et échéances avec sources | Valeur récurrente hors factures | Clause et date prouvées, applicabilité qualifiée, abstention en cas ambigu | Élevé |
| P1 | Boucle de correction mesurée | Prioriser selon erreurs réelles | Temps de revue, cause de rejet, version de skill et lot de réserve | Moyen |
| P1 | Plafond monétaire et quotas IA persistants | Le plafond de taille par appel ne borne pas la dépense mensuelle | Comptage réel, prix configurés et arrêts par dossier/entreprise | Moyen |
| P2 | Frais, fournisseurs, onboarding salarié | Élargir après validation des fonctions principales | Référentiels validés, accès sensibles restreints, jeux de cas dédiés | Élevé |
| P2 | Interface espagnole | Faciliter les pilotes en Espagne | Traductions revues et parité des parcours ; pays distinct de la langue | Moyen |

## Choix du premier connecteur
Pennylane ou Qonto pour un pilote français, Holded pour un pilote espagnol : choisir selon le logiciel du premier utilisateur, pas en développant trois intégrations à l'avance. La recherche a consulté leur documentation ; aucun compte réel ni connecteur n'est activé.

## Hors périmètre actuel
Envoi de courriels et messages, contact client, paiement, télédéclaration, signature et mise à jour autonome du logiciel comptable. Leur absence est une règle de fonctionnement. La publication du code ne donne aucune autorisation d'exécuter ces actions.

## Boucle à chaque changement
Incident ou besoin → priorité motivée → correction → cas de régression → `python3 scripts/qa.py` → revue indépendante ciblée → mise à jour de QA.md → publication. La CI rejoue le contrôle hors ligne à chaque push et pull request. Ce processus n'est ni une promesse de surveillance permanente ni une validation automatique des règles fiscales futures.
