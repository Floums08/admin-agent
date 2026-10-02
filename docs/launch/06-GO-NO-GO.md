# Dossier de décision de lancement — modèle à remplir

Statut initial : **NON LANCÉ**. Copier ce modèle dans l'espace privé du client. Cocher une ligne uniquement avec une preuve, une date et une personne. « À faire », « supposé » et « non exécuté » ne sont pas des réussites.

## Identification

| Champ | Valeur à renseigner |
|---|---|
| Entreprise et identifiant client | |
| Pays et périmètre du service | |
| Version du code / image et date de recette | |
| URL de production / hébergement / région | |
| Responsable client et remplaçant | |
| Responsable du service et technique | |
| Date de lancement demandée et horaires de service | |
| Emplacement privé des preuves | |

## Conditions de lancement

| ID | Condition | Preuve attendue | Responsable | État / date |
|---|---|---|---|---|
| G01 | Une seule entité et quatre workflows maximum couverts ; limites comprises | Périmètre accepté avec volumes et exclusions | Client + service | Non vérifié |
| G02 | Instructions et cadre de traitement validés | Références du contrat, annexes, registre et fournisseurs | Client + prestataire | Non vérifié |
| G03 | Règles de conservation/restitution/suppression décidées | Tableau par catégorie et copies/sauvegardes | Responsable vie privée | Non vérifié |
| G04 | Instance/base dédiées, aucun jeu réel en dépôt public | Config et contrôle d'identité client | Technique | Non vérifié |
| G05 | Domaine, DNS, certificat HTTPS et restrictions réseau fonctionnent | Test depuis un poste externe autorisé ; ports exposés inventoriés | Technique | Non vérifié |
| G06 | Comptes nominatifs, rôles minimaux, TOTP et révocation testés | U01/U02, liste d'accès, récupération hors ligne | Technique + utilisateurs | Non vérifié |
| G07 | Administration hébergeur protégée ; secrets et horloge gérés | MFA infrastructure, permissions et NTP | Technique | Non vérifié |
| G08 | Sauvegarde chiffrée indépendante et restauration complète prouvées | Snapshot, rapport, RPO/RTO mesurés, récupération des accès | Technique | Non vérifié |
| G09 | Recette métier et technique entièrement réussie | U01 à U10, lot métier, contrôle visuel | Responsable recette | Non vérifié |
| G10 | Relecteur et remplaçant formés et disponibles | Formation et circuit de décision | Client + service | Non vérifié |
| G11 | Exploitation, alertes, incident et capacité attribués | Ordonnanceur testé, contacts et seuils | Service + technique | Non vérifié |
| G12 | IA externe, actions engageantes et démos indisponibles en production | Configuration et résultat U09 | Technique | Non vérifié |
| G13 | Coût et engagement compatibles avec charge observée et 100 dossiers cumulés | Temps complet, budget hébergement, nombre de dossiers de recette, date prévue d'atteinte du plafond | Responsable service | Non vérifié |
| G14 | Fin de service et export compréhensibles | Exercice de restitution, limites de purge comprises | Client + prestataire | Non vérifié |

Les preuves techniques du dépôt, décrites dans [QA](../QA.md), peuvent justifier la version de départ. Elles ne remplissent pas les contrôles propres à l'hébergement, au client, aux comptes, aux contrats ou à l'ordonnanceur. Le rapport `preflight` technique est une pièce du dossier, pas une signature juridique ou métier.

## Risques et écarts résiduels

| Écart | Impact | Mesure provisoire | Responsable / échéance | Accepté par |
|---|---|---|---|---|
| À remplir si un écart existe | | | | |

Un échec de sécurité, isolation, restauration, statut métier critique ou cadre de traitement bloque le lancement. Un écart mineur peut être accepté par les responsables compétents s'il ne contourne pas une condition obligatoire ; préciser le périmètre de cette acceptation.

## Décision

Choisir : `LANCEMENT REFUSÉ` / `LANCEMENT DIFFÉRÉ` / `LANCEMENT AUTORISÉ POUR LE PÉRIMÈTRE CI-DESSUS`.

- Motif et éventuelles limites :
- Date/heure effective :
- Version autorisée :
- Responsable client, nom et signature/trace d'accord :
- Responsable du service, nom et signature/trace d'accord :
- Responsable technique, nom et signature/trace d'accord :
- Date de revue suivante :

Cette validation autorise le service humain convenu. Elle ne permet pas à l'application d'envoyer des messages, de payer, de déposer, de signer ou d'activer un nouveau fournisseur.
