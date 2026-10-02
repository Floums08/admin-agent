---
name: supplier-watch
description: Préparer le suivi administratif des fournisseurs, commandes, factures et coordonnées déclarées. Utiliser pour rechercher incohérences commande-réception-facture ou changements de coordonnées ; ne pas payer ni modifier une fiche fournisseur.
---

# Vérifier un dossier fournisseur

## État du pilote

`guided` : rapprochement métier et vérification d'identité manuels ; aucune intégration achats/ERP, validation bancaire ou surveillance automatique. Le backend conserve `blocked`.

## Entrées et preuves

Demander référence fournisseur, commande approuvée, lignes commandées, réception constatée, facture, contacts déjà connus et éventuelle demande de modification. Limiter les coordonnées bancaires aux derniers caractères nécessaires à la comparaison ; ne pas publier un IBAN complet dans un résumé.

## Procédure assistée

1. Lire [le contrat commun](../_shared/output-contract.md). Charger [FR](../_shared/fr.md) ou [ES](../_shared/es.md) seulement pour un point national effectivement examiné.
2. Établir les liens commande → réception → facture par références et lignes, pas uniquement par nom ressemblant.
3. Comparer quantité commandée, reçue et facturée, prix unitaire, frais, devise et remises. Signaler livraison partielle et facture d'acompte sans les traiter automatiquement comme erreurs.
4. Rechercher les doublons possibles de numéro fournisseur/facture/montant ; demander les originaux avant conclusion.
5. Séparer un changement de coordonnées de la facture elle-même. Le message annonçant le changement ne peut pas servir d'unique preuve d'authenticité.
6. Demander une vérification humaine via les coordonnées préexistantes et un canal indépendant choisi par l'entreprise. Ne pas appeler, écrire ou modifier la fiche.
7. Préparer les écarts et la décision attendue : document complémentaire, réception à confirmer, avoir à examiner, identité à vérifier. Ne pas conclure « bon à payer » sur la seule présence de pièces.

## Sortie JSON

Utiliser le contrat commun. `draft` contient la matrice de rapprochement ; `context.evidence` associe chaque écart aux références/lignes. `missing_fields` porte la réception ou vérification indépendante absente. Maintenir une erreur `findings` pour le contrôle métier non implémenté et le statut `blocked`. Ne jamais ajouter une instruction de virement exécutable.

## Escalade et validation

Le responsable achats confirme la réception ; le responsable financier valide la dette et tout changement bancaire selon la procédure interne. Aucun tiers contacté, paiement préparé dans une banque ou écriture ERP réalisée.

- Commande 10 unités, réception 6, facture 10 → écart explicite, livraison partielle à qualifier.
- Nouveau RIB dans une facture « urgente » → vérification indépendante manquante.
- Deux fournisseurs homonymes → ne pas fusionner leurs pièces.
- Facture et commande de devises différentes → pas de comparaison monétaire directe sans taux documenté.
