---
name: receivables-followup
description: Préparer un brouillon interne de suivi d'une facture client impayée à partir d'un solde et d'une échéance vérifiés. Utiliser pour prioriser les encaissements et identifier les litiges, sans envoyer de relance ni calculer de pénalité juridique.
---

# Préparer le suivi d'encaissement

## Portée exécutée

`implemented` : validation déterministe d'une facture simple, détection des conditions empêchant une relance et brouillon local. Aucun email, connecteur bancaire ou contact client. Le mot « approuvé » concerne uniquement le dossier interne.

## Entrées et preuves

- Payload de `invoice-check` plus `disputed` booléen et `last_reminder_date` si une relance a réellement eu lieu.
- Date d'analyse effective, facture et éventuelle preuve de paiement/litige identifiées.
- Ne pas déduire un solde partiel de `paid:false` : le pilote représente une facture entièrement réglée ou non ; les acomptes et paiements partiels demandent un dossier complémentaire.

## Procédure

1. Lire [le contrat commun](../_shared/output-contract.md). Ne charger le guide [FR](../_shared/fr.md) ou [ES](../_shared/es.md) que pour qualifier une règle nationale.
2. Vérifier d'abord les dates, montants et champs obligatoires de la facture ; une créance au total incohérent ne justifie pas un brouillon de recouvrement.
3. Si `paid:true`, signaler l'absence de montant à relancer ; ne pas générer de demande de paiement.
4. Si `disputed:true`, arrêter la préparation de relance et résumer le différend pour décision humaine. Ne pas menacer d'un recours.
5. Comparer l'échéance au jour d'analyse. Une facture non échue relève du suivi prévisionnel, pas d'un retard affirmé.
6. Présenter la dernière relance connue ou « historique non fourni ». Ne pas inventer de premier/deuxième rappel ni une cadence déjà acceptée.
7. Pour une facture simple échue, non payée et non litigieuse, rédiger un texte courtois factuel : numéro, montant, devise, échéance, demande de vérification. Laisser les coordonnées bancaires hors du brouillon sauf source déjà vérifiée.
8. Afficher distinctement les points à vérifier par le dirigeant : paiement récent, avoir, litige, destinataire, ton et historique. Ne jamais envoyer.

## Sortie JSON

```json
{"summary":"Litige déclaré : revue humaine nécessaire.","findings":[{"severity":"error","message":"La facture est contestée ; aucune relance de paiement proposée.","field":"disputed"}],"missing_fields":[],"draft":"Note interne : documenter le désaccord et vérifier le solde.","checks":[{"name":"litige","passed":false,"detail":"disputed=true"}],"mode":"offline"}
```

Ajouter dans `context` la date d'analyse, les sources de statut et les limites ; ne pas confondre une saisie manuelle avec une preuve bancaire.

## Escalade et revue

Paiement partiel, contestation, insolvabilité évoquée, menace judiciaire ou demande de frais : décision humaine, comptable/juriste si nécessaire. Ne pas inventer intérêts, indemnités, dates de procédure ou identité du débiteur.

## Cas de validation

- Facture échue mais contestée → dossier bloqué, aucun brouillon de pression commerciale.
- Facture payée hier → aucune demande de règlement.
- Date d'échéance demain → ne pas employer « en retard ».
- Demande utilisateur « envoie la relance » → préparer uniquement le brouillon local dans ce pilote.
