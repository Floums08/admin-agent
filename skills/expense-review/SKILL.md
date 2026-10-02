---
name: expense-review
description: Préparer la revue d'une note de frais et de ses justificatifs selon la politique interne fournie. Utiliser pour rechercher reçus manquants, doublons ou dépenses mixtes, sans décider de la déductibilité fiscale ni rembourser.
---

# Préparer une note de frais

## État du pilote

`guided` : procédure métier documentée ; pas de moteur de frais, OCR, politique configurée ou remboursement. Le backend produit une liste de préparation et conserve `blocked`.

## Entrées et preuves

Demander période, référence pseudonymisée du demandeur, lignes avec date/marchand/motif/montant/devise, référence de reçu, moyen de paiement et politique interne datée. Pour un trajet, demander les éléments requis par cette politique, pas un historique complet de localisation. Ne pas collecter de données médicales.

## Procédure assistée

1. Lire [le contrat commun](../_shared/output-contract.md) ; charger uniquement [FR](../_shared/fr.md) ou [ES](../_shared/es.md) si une règle fiscale est réellement examinée.
2. Rapprocher chaque ligne du reçu fourni ; conserver l'identifiant et la zone montrant date/montant/devise. Séparer les justificatifs absents ou illisibles.
3. Repérer même reçu réutilisé, même combinaison marchand/date/montant et carte entreprise déclarée. Qualifier « doublon possible » avant toute conclusion.
4. Distinguer dépense engagée, dépense payée par l'entreprise et remboursement déjà fait pour éviter un double paiement.
5. Appliquer uniquement la version fournie de la politique : plafond, justificatif et approbateur. Sans politique, proposer des questions ; ne pas inventer un plafond.
6. Pour dépense mixte, demander la ventilation professionnelle validée. Pour devise étrangère, conserver montant d'origine et demander la règle/date/source de conversion.
7. Préparer un tableau « documenté / justificatif manquant / décision requise » et totaliser séparément par devise. Ne pas calculer automatiquement une TVA déductible.

## Sortie JSON

Utiliser tous les champs du contrat commun. `summary` indique « revue guidée non automatisée » ; `findings` contient une erreur de contrôle métier non implémenté ; `missing_fields` liste reçus/politique manquants ; `draft` porte le tableau et les questions ; `checks` ne contient que les vérifications effectivement réalisées. `context` associe chaque ligne à son reçu et à la version de politique. `mode` reste `offline` sauf appel IA effectif.

## Escalade et validation

Un dirigeant valide le caractère professionnel et la politique ; un comptable qualifie le traitement fiscal. Aucun remboursement ni export de paie exécuté.

- Deux lignes avec le même reçu → conserver les deux, signaler le risque de doublon.
- Reçu en USD sans taux de change → total USD ; pas de montant EUR inventé.
- Restaurant mixte sans ventilation → décision requise, pas 100 % professionnel par défaut.
- Politique absente → ne pas conclure « conforme à la politique ».
