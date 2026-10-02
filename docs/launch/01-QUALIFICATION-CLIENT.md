# Qualification et préparation d'un client

À remplir dans un espace privé, jamais dans le dépôt public. Une réponse inconnue reste « à confirmer ». Le [modèle JSON](../../examples/client-onboarding.example.json) est un aide-mémoire de collecte, pas une configuration active.

## 1. Qualifier le besoin pendant un entretien de cadrage

| Question | Pourquoi la poser | Critère de décision |
|---|---|---|
| Quelle tâche absorbe du temps chaque semaine ? | Choisir un processus observable | Un résultat précis et répétitif, couvert par un des quatre workflows |
| Combien de dossiers par semaine, et quels pics ? | Prévoir charge, délais et prix | Volume et durée compatibles avec 100 dossiers cumulés, recette comprise, et la capacité de revue |
| Qui fait le travail et combien de temps aujourd'hui ? | Établir une base de comparaison | Mesure sur quelques dossiers, pas une impression globale |
| Quel logiciel détient la vérité et où sont les originaux ? | Éviter deux comptabilités ou deux états de paiement | Source unique désignée pour chaque donnée importante |
| Qui peut confirmer qu'une facture est payée ou contestée ? | Éviter une relance injustifiée | Responsable nommé et preuve datée |
| Qui revoit le résultat et dans quel délai ? | Empêcher les dossiers de rester sans décision | Relecteur disponible et remplaçant |
| Quels cas sont particuliers ? | Délimiter l'automatisation | Acomptes, avoirs, devises, taux multiples, opérations internationales identifiés |
| Quelles conséquences aurait une erreur ? | Proportionner revue et sécurité | Cas critiques manuels ; aucun acte engageant automatisé |
| Quelles données personnelles sont nécessaires ? | Réduire la collecte | Exclusion des informations sans lien direct avec le processus |
| Quel résultat justifierait de poursuivre à 30 jours ? | Définir un succès mesurable | Objectif temps/qualité/volume confirmé après mesure initiale |

Premier segment proposé : entreprise de services B2B, FR ou ES, une entité, documents simples, outil de facturation et professionnel comptable déjà identifiés. Il s'agit d'une hypothèse de ciblage, pas d'une restriction juridique générale.

Reporter les demandes portant principalement sur la paie, les dossiers médicaux, les stocks complexes, plusieurs entités, des paiements partiels fréquents ou la facturation réglementaire. Les huit skills guidées peuvent aider à préparer les questions ; elles ne rendent pas ces cas automatisés.

## 2. Fiche client minimale

| Bloc | Informations à recueillir |
|---|---|
| Identité | Dénomination, identifiant légal nécessaire, adresse de facturation, pays et établissements concernés |
| Activité | Type de service, clientèle B2B/B2C, opérations transfrontalières, particularités identifiées |
| Régime | Statut juridique, TVA et périodicité si nécessaires, professionnel ayant confirmé ; aucun régime déduit de la langue |
| Périmètre | Workflow choisi, période, devises, nombre de dossiers, inclus/exclus, livrable attendu |
| Sources | Logiciel de facturation, espace documentaire, format des données, identifiants stables, dates de mise à jour |
| Personnes | Décideur, opérateur, relecteur, remplaçant, responsable technique, contact vie privée et incident |
| Accès | Rôle de chaque compte, date de début/fin, accès aux sources, procédure de retrait |
| Traitement | Catégories de personnes/données, finalité, instructions, base juridique à déterminer par le responsable, sous-traitants |
| Exploitation | Horaires, fréquence de préparation, seuil d'escalade, cible de reprise et perte maximale de données |
| Fin de service | Format de retour, destinataire autorisé, procédure de réception, suppression et sauvegardes |

Le prestataire n'a pas besoin des identifiants de banque, du certificat fiscal, d'un accès à la messagerie ou d'un compte partagé. La V1 ne se connecte pas à ces services. Les comptes fournisseurs d'hébergement doivent également être individuels et protégés.

## 3. Organiser l'entrée des dossiers

1. Le client conserve les originaux dans son espace documentaire autorisé. Il donne l'accès minimal nécessaire aux opérateurs ou fournit un lot dans un espace de transfert sécurisé choisi contractuellement.
2. L'opérateur vérifie qu'il s'agit de la bonne entreprise et de la bonne période. Il relève une référence stable, la date de consultation et le logiciel source. Ne pas utiliser un lien public ou une URL comportant un jeton d'accès.
3. L'opérateur saisit les champs nécessaires dans le formulaire. Les données structurées avancées peuvent être fournies comme JSON dans le formulaire du workflow correspondant ; il n'existe pas d'import global du dossier de qualification ni d'OCR.
4. La description indique, par exemple, `Source : FACT-2026-014, dossier client factures/2026-09 ; vérifié le AAAA-MM-JJ par opérateur ; statut de paiement fourni par responsable le AAAA-MM-JJ`. Cette traçabilité est déclarative : l'application ne télécharge ni ne certifie la pièce.
5. Un statut de paiement inconnu reste inconnu. Ne pas saisir `false` simplement pour obtenir un brouillon. Un paiement partiel, un litige ou une modification bancaire bloque le traitement standard.
6. Le relecteur compare au document original avant approbation interne. Le client ou le professionnel réalise toute action réelle dans son propre outil.

Formats : dates `AAAA-MM-JJ`, période comptable `AAAA-MM`, montants JSON en chaînes avec point décimal (`"1200.00"`), booléens `true`/`false` seulement lorsqu'ils sont confirmés. Les montants négatifs et les avoirs ne sont pas traités. Les devises admises sont EUR, USD, GBP, CHF, CAD et AUD, avec deux décimales.

## 4. Définir les preuves nécessaires par workflow

| Workflow | Données minimum | Contrôle humain décisif |
|---|---|---|
| Facture | Numéro, fournisseur/client, dates, HT, taux, TVA, TTC, devise, statut de paiement déclaré | Original, taux applicable, présence des mentions requises, unicité de la pièce |
| Créance | Champs facture + contestation confirmée, dernier suivi éventuel, absence d'acompte | Statut récent dans l'outil faisant foi, bénéficiaire, éventuel litige |
| Précomptabilité | Période, liste de pièces (id, type, numéro, date, TTC, devise), quantité attendue | Original disponible pour chaque ligne et exhaustivité de la période |
| Tri | Description minimale de la demande, source, responsable | Bonne orientation et demande réellement comprise |

Ne pas coller des données RH sensibles dans la description d'un tri. Une mention telle que « vérifier la présence de la pièce RH dans l'espace habilité » suffit si la pièce elle-même n'est pas nécessaire.

## 5. Fixer les critères économiques et de service

Documenter le temps manuel de départ, la cadence, le nombre de dossiers inclus et le coût humain. Un seuil proposé doit être approuvé après observation. Exemple de tableau à compléter : `volume mensuel`, `minutes avant`, `minutes saisie+revue+correction`, `erreurs critiques`, `dossiers incomplets`, `délai médian`, `coût d'exploitation`, `marge après temps opérateur`.

Une signature commerciale n'autorise pas un nouveau type de traitement. Tout ajout de processus, pays, données sensibles, connecteur ou fournisseur doit repasser par le cadrage, la revue des données et une recette ciblée.
