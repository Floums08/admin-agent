# Lancer un premier client Admin Agent

Version du 2 octobre 2026. Ce guide prépare un **service administratif opéré**, avec une instance isolée par entreprise et des personnes nommées pour préparer et relire les dossiers. Il ne décrit pas un SaaS mutualisé en libre-service.

La présence du code, d'un conteneur ou d'une CI verte ne signifie pas qu'un client est lancé. Le lancement est acquis seulement après déploiement sur l'hébergement choisi, recette sur cette instance, restauration prouvée et décision de lancement enregistrée. Aucune infrastructure cliente, donnée réelle, commande d'achat ou prise de contact n'est créée par cette documentation.

**Pour commencer par un processus concret : suivre le [pilote collecte et contrôle de factures](08-PILOTE-FACTURES.md).** Il fournit la répétition locale sur dix pièces fictives, la mesure de qualité et de temps, puis le passage à dix pièces autorisées. Le pilote opérationnel reste limité à trente dossiers cumulés, avec bilan en fin de première puis de deuxième semaine.

## Le parcours, dans l'ordre

| Étape | Ce que tu fais | Résultat indispensable | Guide |
|---|---|---|---|
| 1. Choisir un processus | Prendre une seule entreprise FR ou ES, un responsable et un besoin répétitif | Périmètre écrit, volumes et exclusions compris | [Qualification](01-QUALIFICATION-CLIENT.md) |
| 2. Encadrer la prestation | Valider données, instructions, contrats, conservation, accès et fournisseurs | Dossier contractuel et décisions de traitement | [Données et responsabilités](02-DONNEES-ET-RESPONSABILITES.md) |
| 3. Préparer l'environnement | Choisir hébergement, domaine, comptes avec MFA et sauvegardes | Instance de recette isolée et protégée | [Déploiement](03-DEPLOIEMENT.md) |
| 4. Préparer dix cas | Faire fournir des pièces représentatives, autorisées et minimisées | Sources identifiées et résultats attendus validés | [Recette](04-RECETTE-CLIENT.md) |
| 5. Tester et former | Passer la recette, restaurer une sauvegarde et former les opérateurs | Preuves de tests et personnes habilitées | [Exploitation](05-EXPLOITATION.md) |
| 6. Décider | Examiner les preuves et traiter chaque point bloquant | Accord de lancement daté et signé | [Dossier de lancement](06-GO-NO-GO.md) |
| 7. Stabiliser pendant 30 jours | Mesurer temps, corrections, erreurs et charge ; revoir chaque semaine | Décision documentée : poursuivre, ajuster ou arrêter | [Exploitation](05-EXPLOITATION.md) |

Pour commencer aujourd'hui : dupliquer **hors du dépôt public** le [formulaire client fictif](../../examples/client-onboarding.example.json), remplir les inconnues, choisir le premier processus, puis attribuer un responsable à chaque ligne du dossier de lancement. Le JSON est un modèle de collecte ; l'application ne l'importe pas automatiquement.

## Ce que tu peux proposer dans cette version

| Prestation | Livrable produit | Limite à expliquer au client |
|---|---|---|
| Vérifier une facture simple | Cohérence des montants HT/TVA/TTC, dates et champs saisis | Un seul taux, montants positifs et devises prises en charge ; aucune certification fiscale ou contrôle exhaustif des mentions légales |
| Préparer le suivi d'une créance | Brouillon interne quand les informations permettent de le préparer | Aucun envoi ; paiement partiel, litige ou changement bancaire nécessitent une résolution humaine |
| Préparer le dossier du comptable | Index des pièces déclarées, manques, doublons possibles, totaux par devise | Les originaux restent dans l'espace documentaire du client ; aucun rapprochement bancaire ni écriture comptable |
| Trier une demande administrative | Orientation indicative et questions à clarifier | Tri par règles et mots-clés ; aucune boîte mail surveillée |
| Préparer les champs depuis une pièce | Import PDF/PNG/JPEG, texte par page et suggestions à vérifier | 5 Mio et 5 pages maximum ; copie conservée ; chaque champ utilisé doit être confirmé avant création d'un dossier |

Les huit autres skills — frais, échéances, fournisseurs, contrats, RH, conformité, trésorerie, synthèse hebdomadaire — sont **des guides de travail**, pas huit automatismes supplémentaires vendables comme achevés. Les tâches guidées n'accèdent pas au circuit d'approbation d'un résultat exécuté.

Le mode de production de cette livraison exécute les contrôles déterministes. **L'analyse IA externe y est désactivée**, même si une clé existe sur le serveur. Son activation future nécessite une livraison dédiée, une évaluation métier avec appels réels, un cadre de traitement fournisseur et une nouvelle recette. Il faut donc présenter honnêtement l'offre initiale comme un atelier administratif assisté par logiciel, préparant l'usage d'agents IA spécialisés.

L'[OCR local et les connecteurs gratuits](07-OCR-ET-CONNECTEURS.md) ajoutent une collecte contrôlée : dossier local, CSV, Nextcloud/WebDAV et Dolibarr en lecture seule. Ils nécessitent une configuration et une recette sur les sources du client ; aucune connexion réelle n'est créée par la publication du code. Les connecteurs sont des commandes d'administration explicites, pas une synchronisation automatique depuis le navigateur.

Ne pas inclure dans l'offre initiale : accès banque ou messagerie, émission de factures réglementaires, déclaration fiscale, paie, paiement, signature, contact de clients ou scoring RH. Un statut « prêt » signifie **relu en interne**, pas « envoyé », « payé » ou « déclaré ».

## Ce qu'il faut obtenir avant les données réelles

| Élément | Fournisseur attendu | À enregistrer |
|---|---|---|
| Identité de l'entreprise, pays, périmètre | Dirigeant | Une seule entité juridique et un seul périmètre de lancement |
| Régime pertinent et règles applicables | Client avec son expert-comptable / gestoría ou conseil | Ce qui est confirmé, par qui et à quelle date ; inconnues explicites |
| Décideur et remplaçant | Client | Personnes habilitées à expliquer les sources et décider des suites |
| Opérateur et relecteur | Prestataire | Comptes individuels ; responsabilité de revue clairement attribuée |
| Documents d'exemple et preuves attendues | Client | Lot autorisé, minimisé, avec références stables vers les originaux |
| Accord de traitement et durées | Client et prestataire | Instructions écrites, fournisseurs, conservation, retour/suppression |
| Hébergement, domaine et accès | Responsable technique | Compte fournisseur avec MFA, région, budget, comptes applicatifs avec TOTP, HTTPS |
| Sauvegarde indépendante | Responsable technique | Destination chiffrée, clés récupérables, durée choisie et restauration testée |
| Conditions d'exploitation | Responsable de service et client | Horaires, seuils de volume, procédure incident, délai de reprise convenu |

Les mots de passe, clés API, factures, coordonnées bancaires et noms réels ne doivent pas être ajoutés aux exemples, issues GitHub ou fichiers versionnés. Les secrets vont dans un gestionnaire de secrets ou les fichiers protégés prévus au déploiement.

## Dimensionner l'offre avant de promettre un forfait

Commencer par un lot limité et représentatif d'un processus. Mesurer la saisie, la préparation, la revue, les corrections et la coordination. Le temps du premier lot n'est pas une garantie de productivité future.

Calcul utile : **charge mensuelle = volume × temps humain complet par dossier + exploitation + support + contrôles qualité**. Le coût doit intégrer hébergement, sauvegardes, accès sécurisé, assurance éventuelle et temps de suivi. Aucun tarif d'hébergement ou gain commercial n'est garanti par ce dépôt.

Fixer par écrit le nombre de dossiers inclus, la définition d'un dossier, les horaires de service, les délais de fourniture des pièces et la conduite à tenir au-delà du volume. Ne pas promettre une disponibilité 24 h/24 ou un délai de reprise qu'aucun essai n'a démontré.

**Capacité initiale : 100 dossiers cumulés par instance**, tous statuts confondus, et 20 000 événements métier. Ce n'est pas un quota mensuel qui se réinitialise. Les dossiers de recette créés dans l'instance occupent aussi cette capacité. Choisir un premier périmètre compatible et planifier une évolution vérifiée avant la limite ; aucune fonction d'archivage/suppression de dossiers ne libère automatiquement la place. Un besoin initial supérieur n'entre pas dans le lancement de cette version.

La collecte documentaire est également bornée : 100 documents, 100 Mio d'originaux et 20 Mio d'historique d'extraction cumulés par instance, avec cinq extractions réussies maximum par document. Ces quotas distincts ne sont pas des quotas mensuels. Les originaux importés et le texte extrait font partie de la base sauvegardée et de la politique de conservation.

## Conditions d'arrêt

Suspendre le lancement si les rôles sont inconnus, le cadre de traitement n'est pas validé, l'accès n'est pas suffisamment protégé, la restauration échoue, un test de permission échoue ou les pièces sortent du périmètre maîtrisé. Un professionnel compétent doit résoudre les ambiguïtés fiscales ou comptables. Une exception de sécurité majeure n'est pas compensée par une case cochée.

Le [dossier de lancement](06-GO-NO-GO.md) sépare les preuves disponibles dans le dépôt des vérifications qui dépendent encore de l'environnement client. Il est le document de décision final.
