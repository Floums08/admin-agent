---
name: bookkeeping-pack
description: Préparer l'inventaire mensuel des justificatifs pour le comptable, repérer pièces manquantes, doublons et écarts de période. Utiliser pour organiser une clôture documentaire ; ne pas tenir ou certifier la comptabilité.
---

# Préparer le dossier comptable

## Portée exécutée

`implemented` : contrôle déterministe d'un inventaire structuré, pas lecture automatique de PDF, rapprochement bancaire ou affectation au plan comptable. Une liste de documents ne prouve pas qu'ils sont accessibles, authentiques ou fiscalement déductibles.

## Entrées et preuves

- `period` au format `YYYY-MM`.
- `documents` : chaque entrée contient `id`, `type`, `number`, `date`, `total_amount`, `currency`.
- `expected_documents` facultatif, uniquement s'il provient d'un inventaire attendu connu.
- Identifiants stables et dates de document ; garder séparée une date de réception si disponible.

## Procédure

1. Charger [le contrat commun](../_shared/output-contract.md). Charger [FR](../_shared/fr.md) ou [ES](../_shared/es.md) seulement si l'opérateur demande une règle nationale.
2. Vérifier la période et le schéma de chaque document ; garder visibles les références incomplètes.
3. Identifier les identifiants réutilisés et les répétitions de référence comme anomalies à examiner. Ne pas supprimer une pièce : deux fournisseurs peuvent employer le même numéro.
4. Signaler les dates hors période. Ne pas antidater une facture pour la faire entrer dans le mois.
5. Comparer nombre reçu et nombre attendu seulement si l'attendu est fourni ; sinon écrire « complétude totale non démontrée ».
6. Regrouper les montants par devise, jamais en un total multidevise non converti. Employer `Decimal` et conserver les montants source.
7. Préparer l'inventaire, la liste des anomalies et les questions internes destinées au comptable. Éviter tout numéro de compte comptable ou traitement TVA sans validation.
8. Marquer la différence entre « inventaire contrôlé », « pièces vues » et « dossier validé par le comptable ». Aucun envoi automatique.

## Sortie JSON

```json
{"summary":"Dossier incomplet au regard de l'attendu fourni.","findings":[{"severity":"error","message":"1 justificatif fourni pour 2 attendus.","field":"documents"}],"missing_fields":["documents_missing"],"draft":"Inventaire interne et demande de recherche du justificatif manquant.","checks":[{"name":"completude","passed":false,"detail":"1/2 pièces"}],"mode":"offline"}
```

Documenter dans `context` la période, les identifiants examinés, la source de l'attendu et les pièces réellement consultées. Adapter les noms de champs d'anomalie à ceux du moteur ; ne pas annoncer une vérification de fichiers absents.

## Escalade et revue

Faire décider par le comptable du rattachement à l'exercice, des avoirs, immobilisations, devises et dépenses mixtes. Aucune écriture, transmission ou suppression de pièce n'est autorisée.

## Cas de validation

- Même `id` deux fois → doublon visible, aucune suppression silencieuse.
- Trois documents reçus sans `expected_documents` → ne pas affirmer « mois complet ».
- Une pièce en USD et une en EUR → pas de somme présentée comme EUR.
- Facture du mois précédent reçue ce mois-ci → signaler le décalage, ne pas changer sa date.
