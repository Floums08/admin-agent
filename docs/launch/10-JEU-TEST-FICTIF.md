# Générer les factures et notes de frais de test

Ce jeu accompagne le [module Finances et frais](09-FINANCE-ET-FRAIS.md). Il contient **10 factures, 8 reçus de frais, deux CSV bancaires, un guide PDF de six pages et un corrigé séparé**. Quatorze pièces sont des PDF et quatre sont des PNG. Une facture est une copie binaire volontaire : le lot représente 17 originaux uniques.

Toutes les entités, références, prestations et situations sont inventées. Chaque pièce porte « DOCUMENT FICTIF - TEST UNIQUEMENT ». Aucun identifiant fiscal réel, IBAN ou moyen de contact n'est fourni. Les taux et politiques de frais sont des hypothèses d'exercice, pas des règles applicables à un client.

## Parcours manuel

1. Utiliser une instance de recette vide avec le worker OCR. Les générateurs ne créent ni compte ni déploiement et n'importent rien automatiquement.
2. Lire `GUIDE_DE_TEST.pdf`. Les dernières pages donnent les informations humaines à saisir pour chaque note de frais : demandeur, motif, catégorie, paiement et politique fictive.
3. Dans **Documents**, importer les fichiers de `01_factures` et `02_notes_de_frais`, avec la langue FR/ES indiquée. Comparer et confirmer les champs avant de créer puis analyser chaque dossier.
4. Garder les anomalies intentionnelles. Par exemple, le TTC de F06 est imprimé à 725 EUR alors que HT + TVA donnent 720 EUR ; le test doit détecter cet écart.
5. Ajouter les factures cohérentes au registre **Finances**, avec les soldes d'ouverture du corrigé. Importer `03_banque/01_releve.csv` dans **Banque & rapprochements**, puis confirmer les rapprochements utiles.
6. Réimporter le même CSV pour vérifier la déduplication. Importer ensuite `02_releve_conflit.csv` : un identifiant existant avec un montant modifié doit être refusé.
7. Tester F10 après F01 et E08 après E01. F10 ne crée aucun original supplémentaire ; E08 déclenche un doublon de frais potentiel, qui bloque aussi une nouvelle analyse de E01.

Ne pas importer le guide ou le corrigé comme une pièce justificative. Le CSV bancaire ne doit pas être chargé dans le connecteur CSV de collecte de factures.

## Recréer un lot avec des dates actuelles

Outil d'auteur Linux uniquement ; aucune nouvelle dépendance n'est ajoutée à l'application de production. Prévoir Python 3.11+, Poppler, les polices DejaVu et, pour vérifier les images, Tesseract FR/ES/EN et `prlimit`.

Dans un environnement Python de développement :

```bash
python -m pip install -r requirements-production.txt -r requirements-ocr.txt reportlab==4.4.9
python scripts/test_document_pack.py --output runtime/jeu-test-2026-10-05 --as-of 2026-10-05
```

Changer le nom de sortie et la date pour un nouvel essai. Sans `--as-of`, le générateur utilise la date locale du poste. Il refuse un dossier de sortie existant et toute écriture de documents dans le dépôt hors de `runtime/`. Les sorties ne sont pas versionnées : seuls les sources et les cas synthétiques le sont.

Le corrigé est écrit à partir des cas préparés dans `finance_demo_cases.py` et `expense_demo_cases.py`, indépendamment du résultat OCR. Les montants, noms et dates à confirmer ne sont pas inventés à partir de ce que reconnaît le moteur.

## Vérification automatique du lot généré

```bash
python scripts/validate_test_document_pack.py --pack runtime/jeu-test-2026-10-05 --report runtime/jeu-test-2026-10-05/qa/validation.json
```

Le validateur utilise une base SQLite temporaire et le vrai sous-processus OCR borné. Il extrait les pièces, compare les propositions à la vérité préparée, simule une revue humaine explicite avec ces valeurs, puis vérifie les statuts, doublons et opérations du registre. L'horloge métier est fixée à la date du lot pour que cette répétition soit reproductible ; dans une instance ordinaire, les échéances restent évaluées à la date réelle.

La réussite du parcours après correction humaine ne signifie pas que tous les champs ont été lus automatiquement. Le rapport distingue les propositions exactes, absentes et différentes. Il ne teste pas un compte bancaire réel, un fournisseur d'affacturage ou la qualité de photographies clientes.

## Résultats du lot du 5 octobre 2026

- 18 cas documentaires réussis ; 17 originaux uniques et 17 dossiers, dont 13 extractions PDF natives et quatre OCR PNG.
- 127 champs comparés : 125 exacts et deux corrections de noms de clients à effectuer (`FO8` vers `F08`, `FO9` vers `F09`). Tous les montants et toutes les dates présents ont été correctement proposés ; E07 est intentionnellement sans date.
- Neuf scénarios banque/affacturage réussis. Deux règlements de 400 puis 800 EUR soldent F01 ; le débit de 242 EUR solde F02. Les ambiguïtés, devises incompatibles, mauvais sens et flux du factor restent refusés ou à examiner manuellement.
- Simulation F03 : nominal 2 400 EUR, avance 1 920 EUR, réserve 480 EUR, coût 38,60 EUR et net 1 881,40 EUR selon les hypothèses fictives fournies.
- Rejeux, CSV conflictuel, annulation tracée et vérification croisée des reçus E01/E08 réussis.
- Suite existante : 335 tests Python réussis, aucun ignoré. Aucun changement du code applicatif de production.

Les PDF ont été rendus et inspectés. Les polices sont embarquées pour éviter les substitutions de caractères et d'espacement. Les PNG sont des images synthétiques propres ; ce lot ne constitue pas un corpus indépendant de photos réelles.
