# Backlog priorisé

Priorités révisées le 4 octobre 2026 après ajout du suivi financier et des notes de frais. Les estimations sont qualitatives et ne constituent pas un devis.

## Livré pour préparer le premier client

Mode production séparé, comptes nominatifs avec TOTP obligatoire, rôles serveur, sessions révocables, protection CSRF, isolation par instance et identité de base. Docker/Caddy et outils d'exploitation sont fournis. La chaîne SQLite → restic chiffré → récupération → restauration en quarantaine a été exécutée avec données synthétiques et dépôt local. Les preuves détaillées figurent dans [QA.md](QA.md).

Le [parcours de lancement client](launch/00-START-HERE.md) comprend qualification, responsabilités, déploiement, recette, exploitation et décision finale. Le déploiement chez un hébergeur, le certificat public, la sauvegarde hors serveur et les accords du premier client restent à réaliser sur l'environnement retenu.

L'import PDF/PNG/JPEG, l'extraction Poppler/Tesseract isolée avec sources par page et coordonnées, la correction et confirmation des champs, ainsi que les connecteurs CLI dossier local, CSV, Nextcloud/WebDAV et Dolibarr sont livrés. Ils n'activent aucun compte distant. Leur [guide](launch/07-OCR-ET-CONNECTEURS.md) détaille les plafonds et la recette. La qualité sur les documents du client et le temps de revue restent à mesurer avant engagement commercial.

Le [pilote factures](launch/08-PILOTE-FACTURES.md) organise maintenant la prochaine étape : répétition locale sur dix pièces synthétiques, qualification de dix pièces réelles autorisées, observations explicites et décision après deux semaines. Le registre de mesures sépare les cohortes synthétiques et clientes ; ses rapports ne constituent pas une autorisation de lancement. Le plafond opérationnel proposé est de trente dossiers cumulés pour ce pilote, dans les limites techniques existantes.

Le module [Finances et frais](launch/09-FINANCE-ET-FRAIS.md) ajoute les factures clients/fournisseurs suivies, soldes d'ouverture confirmés, règlements partiels, échéances et litiges ; les imports bancaires CSV avec rapprochements manuels réversibles ; la simulation d'affacturage à partir de conditions saisies ; et le contrôle de reçus de frais avec OCR et preuves confirmées. Les données et originaux restent dans la même base sauvegardée. L'affacturage ne contacte aucun financeur et n'exécute aucune cession. Le rapprochement des remboursements de frais et les flux du factor restent hors périmètre.

## Avant d'ouvrir un client réel

1. Compléter les [conditions de lancement](launch/06-GO-NO-GO.md) et fournir les preuves propres au client ; une CI verte n'est pas suffisante.
2. Respecter le périmètre des cinq workflows déterministes et les capacités initiales : 100 dossiers cumulés, 20 000 événements métier, résultats de 32 Kio maximum. La finance ajoute des quotas propres : 100 factures suivies, 1 000 mouvements, 100 imports et 3 000 affectations historiques. Aucun archivage automatique ne permet actuellement de libérer ces quotas. Prévoir une évolution avant saturation.
3. Garder l'IA externe désactivée. Son activation exige une release dédiée avec évaluation réelle, traitement fournisseur accepté, quotas et budgets persistants, puis nouvelle recette.

| Priorité | Évolution | Motif | Critères de sortie | Effort relatif |
|---|---|---|---|---|
| P0 avant chaque lancement | Recette de l'instance et exploitation réelle | Les briques de sécurité sont livrées, l'environnement client ne l'est pas | HTTPS réel, MFA enrôlé, restauration depuis stockage indépendant, responsabilités approuvées | Moyen |
| P0 prochain lot | Exécuter et mesurer le pilote factures | Les outils et scénarios doivent être confrontés au travail réel autorisé | Dix cas, preuves par champ, temps réellement observés, exceptions et bilan de décision documentés | Moyen |
| P0 avant saturation | Pagination, archivage et conservation opérationnelle | La capacité initiale est de 100 dossiers cumulés | Purge/archivage contrôlés, restitution testée, traçabilité et charge mesurée avant augmentation | Élevé |
| P0 avant documents réels | Évaluer l'OCR sur un lot indépendant autorisé | Les tests synthétiques ne mesurent pas les scans réels | Exactitude champs critiques, abstention, langues, photos inclinées et temps de correction mesurés | Moyen |
| P1 | Aperçu visuel sécurisé et rapprochement des zones | La version livrée affiche texte/page/coordonnées et télécharge l'original | Rendu isolé et borné, champ + image côte à côte, mobile et accessibilité vérifiés | Moyen |
| P0 | Évaluation IA réelle sur lot indépendant | Les mocks valident l'intégration, pas la qualité d'un modèle | Résultats FR/ES, erreurs critiques, coût et latence mesurés, pas d'actions externes | Moyen |
| P0 avant chaque lancement | Activer les sauvegardes et la supervision sur l'hôte | Outils livrés et restauration locale testée ; destination distante encore à configurer | Restauration réelle hors hôte, alerte sur échec, politique validée par type de donnée | Moyen |
| P1 | Étendre le rapprochement au-delà des factures simples | Les règlements partiels et ambiguïtés sont couverts ; avoirs, frais bancaires, remboursements salariés et flux du factor restent exclus | Cas métier qualifiés, preuves, annulations et soldes vérifiés sans confusion entre financement et paiement client | Élevé |
| P1 | Relier les brouillons de relance au registre financier | Le workflow de relance conserve ses observations séparées et ne lit pas automatiquement le registre | Référence unique, paiement/litige/cession à jour et blocage sur preuve périmée ; aucun envoi | Moyen |
| P0 avant connexion réelle | Recette du connecteur gratuit choisi | Adaptateurs livrés et protocoles simulés ; comptes réels non qualifiés | Compte de test, permissions minimales, schéma et pagination, révocation, conflits et fraîcheur vérifiés | Moyen |
| P1 | Export de factures XML et connecteur métier supplémentaire | Les formats structurés évitent les erreurs OCR | Format et logiciel choisis selon le premier client, corpus de conformité et compte de test | Élevé |
| P1 | Export métier pour un cabinet pilote | Le JSON ne suffit pas à l'exploitation comptable | Format accepté par le professionnel, références et pièces vérifiées | Moyen |
| P1 | Contrats et échéances avec sources | Valeur récurrente hors factures | Clause et date prouvées, applicabilité qualifiée, abstention en cas ambigu | Élevé |
| P1 | Boucle de correction mesurée | Prioriser selon erreurs réelles | Temps de revue, cause de rejet, version de skill et lot de réserve | Moyen |
| P1 | Plafond monétaire et quotas IA persistants | Le plafond de taille par appel ne borne pas la dépense mensuelle | Comptage réel, prix configurés et arrêts par dossier/entreprise | Moyen |
| P2 | Barèmes de frais, fournisseurs, onboarding salarié | Les reçus de frais sont contrôlés ; calcul de remboursement, barèmes et autres domaines restent à qualifier | Référentiels validés, accès sensibles restreints, jeux de cas dédiés | Élevé |
| P2 | Interface espagnole | Faciliter les pilotes en Espagne | Traductions revues et parité des parcours ; pays distinct de la langue | Moyen |

## Choix du premier connecteur
Commencer par le dossier local ou le CSV pour valider la collecte sans compte externe. Utiliser Nextcloud/WebDAV ou Dolibarr si le client les possède déjà, avec accès de test limité. Les adaptateurs refusent les adresses privées dans cette release ; une installation Nextcloud uniquement interne demande une évolution de déploiement et de sécurité évaluée. Ne pas acheter un logiciel seulement pour ce prototype.

Pennylane, Qonto et Holded restent des possibilités futures selon l'outil du premier utilisateur ; leurs intégrations ne sont pas implémentées. Aucun compte mail, bancaire, comptable ou fiscal réel n'est activé dans cette livraison.

## Hors périmètre actuel
Envoi de courriels et messages, contact client, paiement, télédéclaration, signature et mise à jour autonome du logiciel comptable. Leur absence est une règle de fonctionnement. La publication du code ne donne aucune autorisation d'exécuter ces actions.

## Boucle à chaque changement
Incident ou besoin → priorité motivée → correction → cas de régression → `python3 scripts/qa.py` → revue indépendante ciblée → mise à jour de QA.md → publication. La CI rejoue le contrôle hors ligne à chaque push et pull request. Ce processus n'est ni une promesse de surveillance permanente ni une validation automatique des règles fiscales futures.
