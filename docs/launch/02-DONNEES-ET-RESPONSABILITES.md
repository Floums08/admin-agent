# Données, contrats et responsabilités

Vérifié le 2 octobre 2026 auprès des sources officielles listées ci-dessous. Ce document est une **liste de décisions opérationnelles à faire valider**, pas un contrat de sous-traitance complet ni une attestation de conformité.

## Définir les rôles réels

Dans le service proposé, l'hypothèse de départ est que le client définit la finalité administrative et que le prestataire agit sur ses instructions. La qualification dépend toutefois des faits, pas uniquement du titre donné au contrat. Documenter qui décide des usages, données, destinataires et durées ; qualifier séparément les traitements propres du prestataire, tels que sa facturation [S1].

| Sujet | Client | Prestataire / opérateur | Responsable technique |
|---|---|---|---|
| Périmètre et instructions | Décide et confirme | Exécute le périmètre convenu | Configure les capacités autorisées |
| Exactitude et provenance | Désigne l'outil faisant foi | Recopie, contrôle et demande clarification | Préserve les données et l'audit |
| Revue administrative | Désigne son responsable de décision | Prépare et relit selon mandat | N'approuve pas à la place du métier |
| Fiscalité et comptabilité | Mobilise son professionnel | Escalade les inconnues | N'invente aucune règle |
| Accès | Autorise les personnes | Utilise des comptes nominatifs | Crée, retire, teste et trace les accès |
| Protection des données | Qualifie les finalités et obligations | Applique les instructions et aide aux demandes | Met en œuvre les mesures convenues |
| Incident | Décide des notifications relevant de son rôle | Alerte le responsable désigné | Contient, conserve les preuves et restaure |
| Fin de contrat | Donne instruction de restitution/conservation | Organise le retour et documente la clôture | Retire les accès et applique les opérations validées |

Cette répartition organisationnelle ne transfère pas les obligations légales de chacun. Pour le premier client, choisir explicitement si le relecteur interne est un salarié du prestataire, le dirigeant client ou un professionnel ; un compte ne constitue pas à lui seul un mandat.

## Dossier à valider avant traitement réel

Le contrat doit décrire concrètement la prestation et les mesures associées [S2]. Préparer les annexes suivantes, puis faire valider leur adaptation :

- Objet, finalité, durée, catégories de données et de personnes ; instructions et personnes autorisées à les modifier.
- Confidentialité des opérateurs, accès individuels, formation, contrôle des habilitations et mesures de sécurité.
- Fournisseurs utilisés, autorisation des sous-traitants ultérieurs et procédure d'information en cas de changement.
- Lieux de traitement, accès de support et transferts éventuels ; mécanisme juridique et analyse nécessaires selon le cas.
- Assistance aux demandes d'accès, rectification, effacement, limitation et portabilité lorsqu'applicable ; procédure et délais de coopération.
- Incident : contacts, canal urgent, informations initiales et mises à jour, conservation des preuves et responsabilités.
- Sortie : restitution, suppression ou conservation justifiée, sort des copies et sauvegardes, preuve d'exécution.
- Informations et moyens de vérification des mesures ; procédure d'audit adaptée.

Le dossier client précise également la base juridique retenue et l'information des personnes, sous la responsabilité de l'acteur concerné. Ne pas utiliser un « consentement RGPD » générique comme solution universelle. Faire évaluer la nécessité d'une analyse d'impact selon les traitements réels ; une instance isolée ne suffit pas à décider ce point.

## Registre des fournisseurs à compléter

| Fonction | Fournisseur / entité contractuelle | Région des données et accès support | Données reçues | Contrat / transfert / autorisation | État |
|---|---|---|---|---|---|
| Hébergement de l'instance | À choisir | À confirmer | Base, comptes et journaux | Références à consigner | Bloquant avant données réelles |
| Sauvegarde indépendante | À choisir | À confirmer | Copie chiffrée ; qui détient la clé à documenter | Références à consigner | Bloquant avant données réelles |
| VPN / contrôle d'accès supplémentaire, si utilisé | À choisir si nécessaire | À confirmer | Comptes, journaux de connexion ; contenu si terminaison TLS | Références à consigner | Selon architecture retenue |
| DNS / certificats | À choisir | À confirmer | Métadonnées de domaine ; vérifier la chaîne technique | Références à consigner | À examiner |
| Supervision / support | À choisir ou exploitation interne | À confirmer | Métadonnées nécessaires seulement | Références à consigner | À examiner |
| Fournisseur IA externe | Aucun en mode production de cette version | Sans objet tant que désactivé | Aucune transmission par le mode production | Nouvelle validation requise avant activation future | Désactivé |

GitHub contient le code et les exemples fictifs, pas la base, les documents ni les secrets. Le code ouvert n'autorise pas l'ajout de données clientes dans les tickets de support.

Choix de déploiement proposé : hébergement et sauvegarde dans l'UE, avec localisation et conditions réelles vérifiées. Le lieu du serveur ne démontre pas seul l'absence de transferts ou d'accès hors UE ; la chaîne de sous-traitance et le support doivent être examinés [S2].

## Durées et suppression : décisions explicites

La durée dépend de la finalité et des obligations applicables. La CNIL distingue utilisation active et éventuel archivage ; un référentiel ne remplace pas l'examen de la situation [S3]. Les durées légales des factures originales ne sont pas automatiquement celles de tous les brouillons ou copies de travail.

| Catégorie | Durée active | Archivage justifié | Sauvegardes | Responsable / preuve |
|---|---|---|---|---|
| Champs et résultats des dossiers | À décider | À décider | Fenêtre de copies à décider | Client et prestataire |
| Références vers originaux | À décider | Selon finalité documentée | À aligner | Client |
| Événements métier | Durée à décider ; pas de purge automatique | Si justifié | À aligner | Responsable technique / vie privée |
| Événements de sécurité/authentification | Rotation technique : 90 jours maximum et 50 000 entrées maximum | Si requis, prévoir une solution avant lancement | Copies de sauvegarde à traiter séparément | Responsable technique / vie privée |
| Comptes désactivés et identité d'audit | À décider | Trace minimale justifiée | À aligner | Responsable technique |
| Exports et fichiers de recette | À décider | Si nécessaire | Inventorier chaque copie | Responsable de recette |

La livraison n'effectue **aucune purge automatique des dossiers ni des événements métier**. Le journal de sécurité applique une rotation technique de 90 jours ou 50 000 entrées, la limite atteinte en premier ; ce choix produit n'est pas une durée légale et ne garantit pas 90 jours si le plafond d'entrées est atteint. Faire accepter son adéquation ou le modifier de manière testée avant lancement. Fixer le processus et un responsable pour les autres catégories ; si le besoin exige une suppression sélective immédiate, cette capacité doit être développée et testée avant acceptation du client. Une suppression SQL improvisée risque de casser l'audit et les relations entre données.

Les sauvegardes restent soumises à la politique convenue : documenter leur expiration, les accès restreints et la réapplication des instructions de suppression en cas de restauration. Ne pas promettre une suppression immédiate de toutes les copies si l'infrastructure ne la permet pas. Les exports téléchargés sont aussi des copies à inventorier.

## Mesures organisationnelles retenues pour ce lancement

Une instance et une base par entreprise ; préproduction distincte ; HTTPS et MFA TOTP applicative obligatoire ; comptes individuels ; MFA sur les comptes d'administration de l'hébergement ; pas de mots de passe envoyés dans les dossiers ; revue des habilitations ; postes à jour et verrouillés ; gestionnaire de mots de passe ; chiffrement des volumes et des sauvegardes selon l'hébergement choisi ; récupération des clés documentée. Ces mesures sont des exigences du projet, pas une affirmation que chaque mesure est imposée à l'identique à toute TPE. La CNIL fournit des recommandations spécifiques sur la MFA [S4].

## Sources officielles

| Réf. | Source | Date de page / lecture | Usage dans ce guide |
|---|---|---|---|
| S1 | [CNIL — Bien identifier son rôle](https://www.cnil.fr/fr/rgpd-comment-bien-identifier-son-role) | 06/06/2025 ; lu 02/10/2026 | Qualification factuelle des acteurs |
| S2 | [CNIL — Sécurité : gérer la sous-traitance](https://www.cnil.fr/fr/securite-gerer-la-sous-traitance) | 14/03/2024 ; lu 02/10/2026 | Contrat, garanties, localisation, chaîne fournisseur |
| S3 | [CNIL — Durées de conservation](https://www.cnil.fr/fr/passer-laction/les-durees-de-conservation-des-donnees) | 02/04/2026 ; lu 02/10/2026 | Durées justifiées par finalité/contexte |
| S4 | [CNIL — Recommandation MFA](https://www.cnil.fr/fr/recommandation-mfa) | 01/04/2025 ; lu 02/10/2026 | Choix et encadrement MFA |
| S5 | [AEPD — Notification des violations de données](https://www.aepd.es/preguntas-frecuentes/2-tus-obligaciones-como-responsable-del-tratamiento/11-brechas-de-datos-personales/FAQ-0233-a-quien-hay-que-notificar-las-brechas-de-datos-personales) | Date de mise à jour non affichée ; lu 02/10/2026 | Qualification et notification des incidents |
| S6 | [CNIL — Clauses responsable / sous-traitant](https://www.cnil.fr/fr/clauses-contractuelles-types-entre-responsable-de-traitement-et-sous-traitant) | Consulté 02/10/2026 | Base de travail juridique, à adapter |

Le texte RGPD EUR-Lex était protégé par un contrôle anti-robot lors de cette vérification ; aucune lecture intégrale du texte via ce lien n'est revendiquée. Les recommandations ci-dessus s'appuient sur les pages officielles consultables et la [recherche réglementaire du dépôt](../research/03-compliance.md). Revalider les sources avant chaque évolution importante de périmètre.
