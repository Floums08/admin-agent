# Recette du premier client

Cette recette s'exécute sur **l'instance effectivement destinée au client**, d'abord avec des données fictives. Pour le lot métier autorisé, utiliser une préproduction séparée ou la fenêtre de lancement convenue. Une CI verte ne remplace ni les tests HTTPS/MFA ni la comparaison des saisies avec les originaux.

## Préparation

Nommer le responsable de recette, le relecteur métier et le responsable technique. Enregistrer le client, la version exacte du code/image, la date, l'URL, le navigateur, le poste et le statut de chaque test : `non exécuté`, `réussi`, `échoué`, `hors périmètre justifié`. Conserver les preuves dans l'espace privé de lancement ; aucun secret ou document réel dans GitHub.

Créer trois comptes de recette nominatifs : `admin`, `operator`, `reader`. Faire leur enrôlement TOTP individuellement. Préparer une facture simple fictive : HT `1000.00`, taux `20.00`, TVA `200.00`, TTC `1200.00`, EUR, dates cohérentes. Le taux de 20 % n'est ici qu'une donnée arithmétique de test. Les dates de créance doivent être adaptées au jour d'exécution.

## Dix scénarios obligatoires

| ID | Action et données | Résultat attendu | Preuve à conserver |
|---|---|---|---|
| U01 — Connexion et MFA | Se connecter avec un mauvais mot de passe, un TOTP erroné puis le couple correct ; tester déconnexion et expiration | Les erreurs n'ouvrent aucune session. MFA obligatoire. Déconnexion invalide la session. Cookie protégé et HTTPS vérifiés | Captures sans secrets + statut HTTP + comptes utilisés |
| U02 — Permissions et révocation | Avec `reader`, tenter création/analyse/revue/export. Désactiver ce compte puis réessayer une session déjà ouverte | Lecture permise avant retrait ; écritures/revue/export refusés. Session du compte désactivé inutilisable. Export réservé à `admin` | Matrice droits observée ; journal de révocation |
| U03 — Identité client | Démarrer une copie de recette avec un identifiant client différent lié à la même base ; contrôler l'identité affichée sur l'instance normale | Configuration/base incompatibles refusées. Aucune sélection d'une autre entreprise dans l'application | Sortie de contrôle sans données clientes ; identité attendue |
| U04 — Facture correcte | Créer la facture fictive, analyser puis comparer au document source fictif et approuver | Calculs cohérents ; revue requise ; statut prêt seulement après revue. Aucun paiement ni envoi | Identifiant, version analysée et version approuvée, événement nominatif |
| U05 — Erreur et information inconnue | TTC `1190.00`, puis facture sans `paid` confirmé ; tenter validation | Erreur de total ou champ manquant visible ; approbation bloquée. Inconnu ne devient pas `false` | Anomalies attendues et statut obtenu |
| U06 — Suivi de créance | Tester facture échue non payée/non contestée, puis payée, zéro, contestée, avec acompte et changement bancaire | Brouillon seulement pour le cas éligible. Payée/zéro : aucune demande de règlement. Contestée/acompte/changement bancaire : blocage approprié | Résultats de chaque variante ; preuve qu'aucun message n'a été envoyé |
| U07 — Pièces comptables et tri | Saisir un index avec une pièce manquante puis deux lignes en doublon ; faire un tri d'une demande ambiguë | Manque/doublon signalés ; totaux séparés par devise ; tri indicatif sans prétendre ouvrir les originaux ou comprendre un régime fiscal | Index, alertes et questions de revue |
| U08 — Revue et concurrence | Ouvrir le même dossier dans deux onglets. Modifier dans le premier ; tenter d'approuver l'ancienne version dans le second | Ancienne analyse/revue invalidée. Conflit de version explicite ; rechargement et nouvelle analyse nécessaires | Versions avant/après et refus d'approbation périmée |
| U09 — Limites et confidentialité | Choisir une skill guidée ; tester texte contenant une instruction d'envoi ; contrôler IA, démonstration et endpoints exposés | Mode guidé identifiable ; aucune approbation de faux résultat exécuté. Aucune action externe. IA externe et chargement de démos indisponibles en production | Résultat et contrôles techniques ; pas de secrets dans journaux |
| U10 — Sauvegarde, restauration et retour | Exporter en admin, sauvegarder, vérifier, restaurer dans une nouvelle base puis lancer la copie isolée | Données et audit retrouvés ; autre client/refus de copie corrompue vérifiés. Tous les comptes restaurés désactivés, sessions révoquées ; récupération par CLI testée | Rapport de restauration, durées, volumes et concordance export |

Ajouter un test sur navigateur et écran étroit pour les quatre parcours retenus : connexion, création, analyse, revue. Vérifier lisibilité, accès clavier, erreurs de formulaire et fermeture de session. Les tests DOM automatisés ne certifient pas le rendu visuel.

## Lot métier représentatif

Utiliser environ dix dossiers autorisés : cas normaux, manques, incohérence, cas refusé et correction. Si le client ne retient qu'un workflow, concentrer le lot métier dessus tout en conservant tous les tests de sécurité et d'exploitation. Le responsable métier établit le résultat attendu **avant** de consulter le résultat logiciel. Un lot qui sert à corriger les règles doit être complété par des cas nouveaux pour la décision finale.

Pour chaque dossier, relever : référence originale, temps manuel de référence, temps de saisie, temps de revue, corrections, statut attendu/obtenu, erreurs critiques, cause et responsable. Ne pas utiliser une exactitude globale pour masquer une erreur de montant, de destinataire ou de statut de paiement.

## Seuils de décision

- Aucun test de sécurité, isolation, révocation, sauvegarde/restauration ou limites métier en échec.
- Aucun résultat engageant présenté comme exécuté ; aucune approbation d'un dossier bloquant.
- Tous les dossiers du lot ont une source identifiable et un relecteur ; toute divergence est résolue ou explicitement exclue du périmètre.
- Les objectifs de temps et de charge du pilote sont renseignés et compris. Ils sont mesurés, pas garantis par le nombre de tests techniques.
- Tout point non exécuté est déclaré ; un test obligatoire non exécuté empêche le lancement.

Une anomalie critique entraîne correction, test de non-régression et nouvelle recette ciblée. Le [dossier de lancement](06-GO-NO-GO.md) conserve la décision, la version et les signatures. Le compte-rendu doit dire ce qui a réellement été testé, avec les écarts restants.
