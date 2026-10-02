---
name: weekly-brief
description: Préparer une synthèse administrative hebdomadaire factuelle à partir d'un ensemble de tâches explicitement sélectionné. Utiliser pour montrer décisions, blocages et prochaines actions sans inventer un gain de temps, un paiement ou une tâche terminée.
---

# Préparer le briefing hebdomadaire

## État du pilote

`guided` : synthèse humaine assistée des seules informations fournies ; aucun rapport récurrent programmé, agrégation automatique de tous les dossiers ou email. Le backend conserve `blocked`.

## Entrées et preuves

Demander période avec fuseau, liste explicite des tâches et leur version/statut/date, décisions connues, changements depuis la dernière revue et périmètre de couverture. Sans état précédent, préparer un état des lieux, pas une évolution calculée.

## Procédure assistée

1. Lire [le contrat commun](../_shared/output-contract.md). Ne charger les guides [FR](../_shared/fr.md) ou [ES](../_shared/es.md) que si une règle nationale est réellement citée.
2. Prendre un instantané du jeu de tâches sélectionné ; ne pas charger tout l'historique ou d'autres entreprises pour enrichir artificiellement le briefing.
3. Compter séparément nouveaux dossiers, à revoir, bloqués, approuvés et rejetés. Une approbation interne ne signifie ni email envoyé, ni paiement encaissé, ni déclaration déposée.
4. Classer les décisions par échéance vérifiée, impact documenté et dépendance. Les qualificatifs d'urgence non sourcés restent des déclarations.
5. Résumer chaque blocage avec cause, pièce manquante, rôle responsable et action proposée. Identifier les sujets sans propriétaire.
6. Présenter une variation par rapport à la semaine précédente uniquement si même périmètre et instantanés comparables ; expliquer ajouts/suppressions.
7. Mesurer des durées seulement à partir d'horodatages et d'une définition. Ne pas convertir arbitrairement un nombre de tâches en heures ou euros économisés.
8. Préparer une synthèse courte : décisions à prendre, dossiers débloqués, risques factuels, trois prochaines actions maximum ; lier chaque ligne à la tâche source.

## Sortie JSON

Utiliser le contrat commun. `draft` porte le briefing ; `context` documente période, fuseau, tâche/version et couverture ; `missing_fields` porte l'état de référence absent si une évolution est demandée. Maintenir l'erreur de contrôle métier non implémenté et le statut `blocked`. Ne pas écrire « diffusé ».

## Escalade et validation

Le dirigeant vérifie le périmètre, les priorités et les responsabilités. Ne pas inclure inutilement noms de salariés, détails médicaux ou coordonnées bancaires dans une synthèse globale.

- Aucun instantané précédent → pas de « +20 % cette semaine ».
- Dossier approuvé → écrire « préparation approuvée », pas « relance envoyée ».
- 10 tâches sans mesure de durée → aucun gain de temps chiffré.
- Jeu de tâches partiel → limiter le titre et les conclusions à ce périmètre.
