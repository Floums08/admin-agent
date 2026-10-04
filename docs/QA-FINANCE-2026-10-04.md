# QA indépendante — suivi financier et notes de frais

Date : 4 octobre 2026. Données utilisées : entreprises, reçus, factures et mouvements entièrement synthétiques. Aucun compte bancaire, affactureur, client ou fournisseur externe n'est interrogé par cette revue.

## Périmètre de cette revue

Le suivi financier doit conserver un instantané explicitement contrôlé de la facture et des soldes antérieurs, puis des affectations internes traçables. Un rapprochement enregistré n'effectue pas de paiement. Une simulation d'affacturage n'est ni une offre ni une acceptation d'un financeur. Un reçu OCR ne prouve pas son paiement, le droit au remboursement ou la déductibilité de la TVA.

La revue indépendante porte sur `tests/test_finance_review.py`. Les tests d'intégration HTTP, d'OCR natif, d'interface et de déploiement sont des contrôles distincts ; leurs résultats ne sont pas déduits des tests de ce fichier.

## Matrice de risques

| Risque | Vérification prévue |
|---|---|
| Double comptage du passé | Solde initial explicite ; paiement antérieur à la date d'ouverture refusé |
| Dépassement d'un montant disponible | Centimes exacts, montant positif, solde facture et disponibilité bancaire |
| Faux rapprochement | Sens débit/crédit et devise compatibles ; aucune affectation lors de la simple importation ou suggestion |
| Perte de fraîcheur | Version de facture, version bancaire et évolution du dossier source |
| Répétition ou concurrence | Identifiant source stable, contenu modifié refusé, affectation rejouée refusée sans doublon, deux affectations simultanées |
| Import partiel inattendu | Conflit source dans un lot bancaire : aucun nouveau mouvement de ce lot conservé |
| Autorisation révoquée | Refus au moment de la transaction et absence de mutation partielle |
| Correction du rapprochement | Annulation traçable, rétablissement du montant disponible et refus d'une ancienne version |
| Confusion affacturage / encaissement | Simulation et cession sans règlement de la facture ni création de cash |
| Affacturage hors du cas simple | Facture fournisseur, règlement partiel et litige inconnu ou avéré refusés |
| Paiement de frais non prouvé | Confirmation explicite indépendante du texte OCR |
| Double remboursement | Paiement entreprise, remboursement déjà déclaré et reçu similaire entre plusieurs demandeurs |
| Revue de frais devenue périmée | Montant modifié après vérification ; doublon créé entre analyse et validation |
| TVA ou change supposé | Revue brute sans TVA déductible ; absence de conversion d'un plafond en autre devise |

## Exécution

Commande exécutée sur Python 3.12 avec les dépendances de production :

```bash
python -m unittest tests.test_finance_review -v
```

**Premier passage complet : 31 tests réussis, aucun ignoré** — 24 tests de suivi financier et 7 tests de notes de frais. Deux tests ciblés supplémentaires de reconfirmation des reçus ont ensuite été ajoutés et exécutés avec succès, portant le fichier à **33 tests**. Les variantes dans les `subTest` ne sont pas additionnées au nombre de méthodes.

Les reçus des tests de notes de frais passent par le véritable stockage documentaire, son empreinte, l'extraction enregistrée et la confirmation de chaque champ. L'extracteur est simulé dans cette suite pour isoler les règles métier ; ce résultat ne mesure pas la reconnaissance optique d'une photo réelle.

Les contrôles réussis comprennent notamment :

- Facture de 120,00 EUR avec 40,00 EUR déjà réglés : affecter 80,00 EUR solde exactement la facture. Les dépassements, fractions de centime, devises différentes et sens opposés sont refusés.
- Réimport du même mouvement : une seule opération conservée. Un contenu modifié sous le même identifiant est refusé ; un lot conflictuel n'ajoute pas ses autres nouvelles lignes.
- Deux confirmations concurrentes du même montant disponible : une seule réussit. Une révocation simulée au point de mutation laisse les affectations et versions inchangées.
- Un changement d'identité de l'instance bloque les lectures et les écritures financières. Une version source modifiée bloque un nouveau rapprochement.
- La référence `FACT-10` ne sélectionne pas `FACT-1`. Le seul montant commun produit une piste à contrôler manuellement, sans rapprochement automatique.
- Les flux portant une mention de financement et les créances déclarées cédées ne peuvent être enregistrés comme règlements clients dans ce parcours.
- Un reçu payé par l'entreprise, déjà remboursé ou présentant un mode de paiement contradictoire reste bloqué. L'absence de confirmation de paiement reste une donnée manquante.
- Un même marchand, une même date, un même montant et une même devise restent un doublon possible, même avec un autre demandeur. Un nouveau doublon entre analyse et validation bloque la validation.

## Vérification du calcul d'affacturage

Le cas synthétique utilise un nominal de 120,00 EUR, une avance de 80 %, des frais de 2 % du nominal plus 1,00 EUR fixe, un intérêt annuel simple de 12 % sur l'avance, 30 jours et une base de 360 jours.

| Valeur | Résultat attendu et obtenu |
|---|---:|
| Avance | 96,00 EUR |
| Réserve indisponible | 24,00 EUR |
| Frais | 3,40 EUR |
| Intérêts | 0,96 EUR |
| Coût simulé total | 4,36 EUR |
| Net immédiatement simulé | 91,64 EUR |

La réserve n'est pas incluse dans le coût. La simulation ne change ni la facture, ni les mouvements, ni les affectations ; elle ajoute un événement d'audit. Elle déclare explicitement ne pas être une offre externe. Un fournisseur, une créance partiellement payée ou un litige inconnu ou avéré sont refusés dans ce calcul limité.

## Clarifications apportées pendant la revue

Deux assertions initiales ont été corrigées après vérification du contrat prévu, sans masquer d'erreur financière :

1. La répétition d'une confirmation d'affectation retourne volontairement `409 allocation_replay`. Elle ne crée pas une deuxième affectation. Le test vérifie ce refus et l'absence de double comptage.
2. Une simulation ajoute normalement un événement d'audit. Le test compare donc l'ensemble des états métier avant/après, puis vérifie l'événement, au lieu d'exiger un export entièrement identique incluant le journal.

Aucun défaut bloquant n'a été reproduit dans le périmètre des tests indépendants. Cette conclusion reste limitée aux scénarios et au code effectivement examinés ; elle ne remplace pas les contrôles HTTP, navigateur, OCR natif et conteneur de la livraison complète.

## Revue ciblée du dernier changement de sécurité

La relecture du diff couvre le rattachement d'une base à un client, les routes financières et la nouvelle action `DocumentStore.reverify_expense`.

Deux tests indépendants supplémentaires, exécutés sans rejouer toute la suite, établissent les comportements suivants :

- Après correction de 12,00 à 13,00 EUR, une reconfirmation explicite des quatre faits du reçu conserve l'empreinte et la preuve initiale de 12,00 EUR, ajoute la nouvelle lecture de 13,00 EUR, incrémente la version, remet le dossier à `new` et supprime son ancien résultat. L'approbation directe reste refusée jusqu'à une nouvelle analyse. Une requête reprenant l'ancienne version est refusée.
- Un refus d'autorisation simulé après la modification SQL du dossier, puis après l'insertion de son événement, annule toute la transaction : dossier, historique de confirmation et deux journaux retrouvent exactement leur état précédent.

Quatre tests HTTP existants ont été rejoués avec succès : refus d'attribuer une base locale contenant uniquement des mouvements bancaires, restrictions des lecteurs sur les mutations et exports, révocation entre contrôle de requête et écriture, refus d'origine étrangère et d'actions externes sur le serveur local.

Un contrôle synthétique ponctuel complémentaire a confirmé qu'une base contenant seulement des documents est refusée sans réattribution d'identité ; une base dont les tables financières sont présentes mais vides reste initialisable. Ce contrôle ponctuel est distinct du nombre de méthodes automatisées ci-dessus.

Les routes de mutation financières et de reconfirmation exigent le rôle administrateur ou opérateur et passent par les protections communes de session, origine et CSRF. Les contrôles de mutation sont répétés dans la transaction SQLite. Les exports financiers demeurent réservés à l'administrateur en production.

## Limites communes

- Les CSV synthétiques ne prouvent pas la compatibilité avec l'export d'une banque réelle.
- Les montants importés sont des instantanés. La fraîcheur du compte externe et l'exhaustivité de l'export ne sont pas attestées.
- Modifier ou réanalyser puis revalider le dossier source d'une facture peut rendre son suivi financier périmé. Cette version bloque alors les nouvelles affectations et simulations ; elle ne fournit pas de remise à jour automatique du registre. L'annulation corrective d'une affectation reste disponible. Les notes de frais disposent, elles, d'une reconfirmation explicite des faits corrigés sur le reçu, suivie d'une nouvelle analyse.
- Le rapprochement suggéré reste soumis à confirmation ; l'absence de doublon détecté ne prouve pas l'unicité économique de la dépense.
- La qualité des photos et reçus réels, les conditions de financement, les règles fiscales et la politique de frais du client restent à vérifier dans sa recette.
- Aucun résultat de test ne constitue à lui seul l'autorisation de lancement d'une instance cliente.
