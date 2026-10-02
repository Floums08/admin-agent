---
name: cash-visibility
description: Préparer une vue de trésorerie à partir d'un solde daté et de flux explicitement fournis. Utiliser pour distinguer encaissements attendus, dettes et incertitudes, sans connexion bancaire, ordre de paiement ou prévision garantie.
---

# Préparer la visibilité de trésorerie

## État du pilote

`guided` : procédure et scénario à construire avec l'opérateur ; aucun rapprochement bancaire, calcul prévisionnel de production ou conseil d'investissement. Le backend conserve `blocked`.

## Entrées et preuves

Demander solde initial et date/source, comptes inclus, horizon, devise et flux avec identifiant, sens, montant, date attendue, statut payé/non payé, source et certitude. Préciser ce qui est exclu. Un chiffre d'affaires n'est pas un encaissement et une commande n'est pas un paiement acquis.

## Procédure assistée

1. Lire [le contrat commun](../_shared/output-contract.md). Ne charger aucune règle pays pour une simple addition de flux ; [FR](../_shared/fr.md) ou [ES](../_shared/es.md) uniquement pour une obligation qualifiée.
2. Vérifier la date de valeur du solde et le périmètre des comptes. Marquer un solde ancien sans prétendre à une situation en temps réel.
3. Éliminer le double comptage logique entre facture, prévision et paiement seulement après preuve de leur lien ; conserver un journal des rapprochements proposés.
4. Séparer confirmé, attendu et incertain. Ne pas inventer de probabilité de règlement ; présenter un scénario avec/sans un encaissement incertain.
5. Calculer solde initial + encaissements - décaissements en `Decimal`, par devise et date, avec les seules lignes documentées. Conserver le détail permettant de reproduire le calcul.
6. Faire apparaître les sorties connues sans date, les taxes non qualifiées et les flux récurrents incomplets. Une absence dans l'inventaire ne signifie pas une dépense nulle.
7. Préparer les dates de tension et les décisions internes à examiner ; ne pas recommander un paiement ou financement autonome.

## Sortie JSON

Utiliser le contrat commun. `draft` présente hypothèses et flux ; `context` contient solde daté, périmètre, sources et scénarios. `missing_fields` indique les montants/dates inconnus. `findings` signale l'absence de contrôles métier implémentés et le statut serveur reste `blocked`. Aucun solde « certain » si les données ne le permettent pas.

## Escalade et validation

Le dirigeant/comptable vérifie les flux, les scénarios et les décisions. Ne pas payer, promettre une rentrée d'argent, négocier avec un client ou connecter un compte bancaire.

- Facture 1 000 EUR et paiement correspondant déjà dans le solde → éviter l'encaissement compté deux fois.
- Flux USD et EUR → scénarios séparés sans taux inventé.
- Solde sans date → situation de trésorerie actuelle non démontrée.
- Client contestataire → encaissement incertain clairement identifié.
