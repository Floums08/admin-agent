---
name: deadline-watch
description: Construire une liste d'échéances administratives vérifiables à partir d'avis, contrats et sources officielles applicables à l'entreprise. Utiliser pour préparer un calendrier fiscal, social ou documentaire sans inventer de date ni déposer de déclaration.
---

# Préparer les échéances

## État du pilote

`guided` : aucun calendrier légal automatique, veille récurrente, notification ou connexion à un portail. Le backend maintient le dossier `blocked` tant que les contrôles métier ne sont pas implémentés.

## Entrées et preuves

Demander pays, entité, régime pertinent, période, obligation ou avis reçu, date de référence, source originale, responsable et état de préparation. Distinguer date de dépôt, date de paiement, date de prélèvement et date interne de revue. Un champ « France » ou « Espagne » ne suffit pas à déterminer un régime.

## Procédure assistée

1. Lire [le contrat commun](../_shared/output-contract.md) puis le seul guide [FR](../_shared/fr.md) ou [ES](../_shared/es.md).
2. Qualifier l'obligation avant de chercher sa date : entité, territoire, régime, exercice, transaction et éventuelle exception.
3. Pour un avis nominatif, relever sa date exacte et sa référence sans exposer les identifiants inutiles. Ne pas suivre un lien de paiement contenu dans un avis sans vérification humaine.
4. Pour une règle générale, consulter la source officielle actuelle, son entrée en vigueur et son champ d'application. Consigner URL, section, consultation et justification d'applicabilité.
5. Si un calendrier dépend d'un texte d'application non vérifié, conserver la date inconnue. Ne pas transformer une durée relative en date ferme sans événement déclencheur prouvé.
6. Séparer la date officielle de la date de préparation choisie par l'entreprise. Ne pas déplacer un jour férié/week-end sans règle vérifiée et calendrier applicable.
7. Produire une liste avec obligation, période, échéance, source, propriétaire, pièce à réunir, prochain contrôle et incertitude. Proposer une cadence de suivi seulement ; ne pas prétendre l'avoir programmée.

## Sortie JSON

Utiliser le contrat commun. Mettre la liste dans `draft`, les règles sourcées dans `context.evidence`, les dépendances inconnues dans `missing_fields` et une erreur signalant le contrôle métier non implémenté dans `findings`. Aucun `checks.passed:true` pour une échéance non vérifiée. Le statut serveur reste `blocked`.

## Escalade et validation

Faire confirmer par le comptable/gestor ou responsable RH toute obligation fiscale/sociale avant utilisation opérationnelle. Ne pas déposer, payer, souscrire une alerte ou contacter une administration.

- Régime TVA inconnu → qualification nécessaire, aucune échéance TVA proposée comme certaine.
- Délai relatif à une publication inconnue → date vide et déclencheur manquant.
- Avis et calendrier général contradictoires → conflit visible, pas de sélection silencieuse.
- Jour non ouvré → ne pas reporter sans preuve de règle.
