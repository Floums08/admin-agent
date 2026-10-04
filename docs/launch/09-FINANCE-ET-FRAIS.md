# Suivi financier et préparation des notes de frais

Version du 4 octobre 2026. Ce guide complète le [pilote factures](08-PILOTE-FACTURES.md) avec quatre parcours : suivi des factures, comparaison d'hypothèses d'affacturage, préparation d'un reçu de frais et rapprochement d'un export bancaire.

Ces fonctions préparent des décisions internes. **Elles n'effectuent aucun paiement, remboursement, contact client, cession de créance ou écriture dans un logiciel comptable.** Le rapprochement utilise un fichier fourni, sans connexion au compte bancaire. Le simulateur ne consulte aucun financeur et ne délivre aucune offre de crédit.

## 1. Accès, données et limites

Utiliser le mode de production authentifié, sur l'instance de la bonne entreprise. Pour une répétition, reprendre l'environnement local HTTPS du guide du pilote et employer uniquement des données fictives. Une publication du code ne crée pas une instance cliente.

| Parcours | Compte nécessaire | Données à préparer |
|---|---|---|
| Consulter Finances et les documents | `reader`, `operator` ou `admin` | Accès nominatif à l'instance |
| Enregistrer une facture, importer et rapprocher | `operator` ou `admin` | Facture contrôlée, référence de preuve, historique de règlement et export bancaire autorisé |
| Simuler l'affacturage | `operator` ou `admin` | Facture client compatible avec le modèle et paramètres explicitement saisis |
| Préparer et relire des frais | `operator` ou `admin` | Reçu original, contexte professionnel et politique interne datée |
| Exporter les données financières | `admin` | Destination privée et finalité autorisée |

Les nouvelles écritures restent dans la base SQLite propre au client, avec traces et contrôles de concurrence. Les copies de CSV bancaires, leurs empreintes et les allocations font partie de la sauvegarde cohérente de cette base. Un export financier peut contenir des données bancaires et le texte original des CSV : le conserver dans l'espace privé convenu.

| Plafond | Valeur |
|---|---|
| Registre des factures | 100 factures cumulées |
| Opérations bancaires | 1 000 opérations cumulées |
| Historique financier | 100 imports conservés, 3 000 allocations et 10 000 événements financiers |
| Lot bancaire | 200 lignes au maximum ; CSV limité à 60 000 octets |
| Requête API | Enveloppe JSON limitée à 64 Kio ; un CSV très échappé peut atteindre cette limite avant le plafond de texte |
| Documents | Limites existantes : 5 Mio et 5 pages par original, 100 documents/100 Mio cumulés |
| Dossiers | Limite existante : 100 dossiers cumulés, notes de frais comprises |

Ces plafonds ne se réinitialisent pas chaque mois. L'aperçu, l'import bancaire et la simulation ont aussi une limite de fréquence de quinze requêtes par utilisateur et par fenêtre de quinze minutes, en plus des protections générales de l'API. Réduire un lot ou attendre la fin de la fenêtre ne remplace pas le traitement d'une erreur de données.

## 2. Enregistrer et suivre une facture

1. Préparer la facture dans le circuit habituel `invoice-check`, depuis un document revu ou une saisie contrôlée.
2. Analyser puis effectuer la revue interne. Le dossier doit être `ready` dans sa **version actuelle** avant son inscription au registre.
3. Ouvrir **Finances → Factures → Ajouter une facture validée**.
4. Choisir le sens : **À encaisser (client)** ou **À payer (fournisseur)**. Vérifier l'identité de la contrepartie, le montant, la devise, le numéro et l'échéance.
5. Confirmer le montant déjà réglé à la fin d'une date de référence, avec sa preuve. Un zéro est une déclaration à vérifier, pas une valeur à choisir par défaut parce qu'aucun relevé n'a été importé.
6. Indiquer l'état du litige : oui, non ou inconnu. L'absence de litige ne se déduit pas de l'apparence de la facture.
7. Enregistrer, puis consulter le restant et les mouvements confirmés dans le registre.

Le registre conserve un instantané des informations revues et la version du dossier source. **Finir les corrections et la revue avant l'inscription, puis figer ce dossier.** Une modification ou une nouvelle analyse après inscription change sa version : les nouvelles allocations, simulations et déclarations de cession sont alors bloquées. Cette version ne propose pas de remise à jour de l'instantané du registre. Les annulations d'allocations restent possibles pour conserver un historique correct.

Le solde d'ouverture et sa date sont également immuables après inscription. Une erreur d'ouverture ou une divergence de source exige une escalade au responsable du suivi, avec examen des preuves et décision de traitement hors du parcours courant. Ne pas créer une seconde facture, modifier directement la base ou effacer des traces pour contourner le contrôle. Aucune reprise automatique n'est promise dans cette livraison.

Pour une évolution du litige, utiliser **Mettre à jour le litige**, avec le nouvel état, la date de vérification, la référence de preuve et une note. Cette mise à jour conserve une trace ; elle ne modifie ni le montant original ni les paiements et ne signifie pas que la contrepartie a reçu un message.

### Comprendre les montants et états

| Indication | Interprétation |
|---|---|
| Déjà réglé à l'ouverture | Montant historique déclaré et confirmé à la fin de la date de référence |
| Rapprochements actifs | Montants affectés explicitement depuis les opérations bancaires importées, hors affectations annulées |
| Restant | Montant de la facture moins ouverture confirmée et rapprochements actifs |
| Non réglée / partielle / réglée | État calculé sur ces éléments connus ; il ne prouve pas que toutes les opérations bancaires ont été importées |
| En retard | Échéance antérieure à la date de calcul avec un restant positif |
| Cédée | Déclaration interne d'une cession préexistante ; ce marquage ne réalise pas la cession et n'encaisse aucun montant |

Le registre ne modifie pas automatiquement l'ancien champ `paid` du dossier source et n'approuve pas ce dossier. Pour le suivi financier, consulter les éléments et la fraîcheur du registre ; ne pas présenter une ancienne saisie de paiement comme synchronisée avec la banque.

## 3. Importer un export bancaire

Ouvrir **Finances → Banque & rapprochements**. Préparer un CSV de l'entreprise concernée avec exactement les colonnes suivantes :

```csv
transaction_id,date,amount,currency,reference
demo-001,2026-10-01,1200.00,EUR,FA-2026-001
demo-002,2026-10-02,-72.00,EUR,FO-2026-002
demo-003,2026-10-03,400.00,EUR,FA-2026-003 acompte
```

Cet exemple est fictif. Ne pas le mélanger aux opérations réelles. Le format attendu est UTF-8, séparateur virgule, dates ISO `AAAA-MM-JJ` et montants décimaux avec un point. Un éventuel BOM UTF-8 est accepté. Les entrées d'argent sont positives, les sorties négatives. Les montants et la devise doivent provenir de l'export, sans conversion implicite.

Associer le lot à une **référence stable de compte**. Cette référence peut être un alias interne ; elle sert à distinguer les sources. Ne pas changer d'alias pour réimporter une opération déjà connue. Chaque identifiant de transaction doit être stable sur ce compte ; ne pas remplacer les identifiants de la banque par un numéro de ligne variable d'un export à l'autre.

1. Sélectionner le fichier et la référence du compte.
2. Cliquer **Prévisualiser le CSV**. Contrôler dates, signes, devise, nombre de lignes et références. Aucun import n'est effectué par cette seule étape.
3. Vérifier la période face à l'ouverture des factures : seules les opérations **strictement postérieures** à la date de référence de l'ouverture pourront être affectées à ces factures.
4. Cliquer **Confirmer l'import** après cette revue. Le serveur vérifie l'empreinte du contenu prévisualisé.
5. Examiner les opérations ajoutées et les doublons reconnus avant de rapprocher.

Un rejeu du même élément ne doit pas créer un nouveau paiement. Une opération modifiée sous la même référence de compte et le même identifiant entraîne un conflit : comparer les exports et résoudre l'écart, sans renommer la ligne pour le masquer. Le CSV original reste conservé ; une correction du mapping se fait sur un nouvel export correctement préparé, avec gestion explicite des références déjà importées.

L'import ne démontre ni l'exhaustivité d'une période ni le solde bancaire actuel. Les frais bancaires, virements internes, remboursements, écarts de change ou mouvements sans facture peuvent rester non affectés. Leur présence n'est pas à elle seule une anomalie à corriger artificiellement.

## 4. Confirmer ou annuler un rapprochement

Les suggestions servent à repérer des correspondances possibles. Un même montant ou un libellé proche ne suffit pas à prouver le lien.

Un litige déclaré ou inconnu exclut la facture des suggestions et de la simulation. Un règlement réellement constaté peut néanmoins être affecté manuellement à une facture contestée, avec sa preuve et les mêmes contrôles de solde, de date et de devise ; cette allocation ne clôt pas le litige.

1. Sélectionner l'opération et la facture, puis ouvrir **Rapprocher**.
2. Vérifier la contrepartie, la référence, la date, le sens du flux et la devise sur les sources.
3. Saisir le montant à affecter et la preuve de la correspondance. Il doit être positif et ne dépasser ni le disponible de l'opération ni le restant de la facture.
4. Confirmer. Le serveur vérifie les versions courantes et recalcule le restant.
5. Si un autre utilisateur a changé une affectation entre-temps, recharger puis refaire la vérification ; ne pas répéter aveuglément la validation.

Plusieurs allocations peuvent documenter un paiement partiel ou ventiler un mouvement, dans la limite des disponibles. Elles ne doivent pas reconstituer une somme déjà comprise dans l'ouverture. La date d'ouverture désigne une situation **à la fin de cette journée** : une opération du même jour ou antérieure est donc refusée pour cette facture.

Pour une erreur, utiliser **Annuler le rapprochement** et fournir le motif. L'allocation reste visible dans l'historique ; seule sa contribution active est retirée des soldes. Il ne s'agit ni d'un remboursement ni d'une annulation bancaire. Refaire ensuite une allocation correcte si les preuves le permettent.

Le rapprochement de cette version vise les factures enregistrées depuis `invoice-check`. Une note de frais préparée dans `expense-review` n'est pas automatiquement transformée en facture du registre ou rapprochée à un remboursement salarié. Les litiges, avoirs et règlements complexes demandent une qualification distincte.

## 5. Comparer une hypothèse d'affacturage

Ouvrir **Finances → Affacturage**. Le modèle initial accepte seulement une facture client du registre, totalement non réglée, non contestée, non déjà déclarée cédée, dont la référence source est actuelle et l'échéance future. **Ce filtre décrit le périmètre du calcul ; il ne signifie pas que le factor financera la facture.**

La recherche distingue les coûts de gestion, les coûts de financement et le montant retenu. Le choix avec ou sans recours, les débiteurs acceptés, plafonds, garanties et exclusions restent contractuels : voir [le cadrage sourcé](../research/04-finance-expenses.md), F1 et F2.

Saisir les paramètres d'un scénario ou d'une proposition obtenue séparément :

- pourcentage d'avance sur le nominal ;
- date d'avance envisagée, au plus tôt aujourd'hui et strictement avant l'échéance ;
- commission en pourcentage du nominal et frais fixes ;
- taux d'intérêt annuel ;
- base de calcul de 360 ou 365 jours.

Cliquer **Calculer la simulation**. Les taux saisis sont des hypothèses explicites : aucun prix du marché ou financeur n'est sélectionné automatiquement.

### Formule du modèle

Avec `M` le nominal, `a` le pourcentage d'avance, `c` la commission, `f` les frais fixes, `r` le taux annuel, `j` le nombre de jours entre la date d'avance envisagée et l'échéance de la facture, et `b` la base de jours :

| Résultat | Calcul |
|---|---|
| Avance brute | `M × a / 100` |
| Montant non avancé | `M − avance brute` |
| Commission et frais | `M × c / 100 + f` |
| Intérêts | `avance brute × r / 100 × j / b` |
| Coût total simulé | `commission et frais + intérêts` |
| Trésorerie nette immédiate simulée | `avance brute − commission et frais − intérêts` |

Les calculs utilisent des décimales et des arrondis au centime. Le montant non avancé n'est pas soustrait une deuxième fois de l'avance et n'est pas additionné aux frais. Sa restitution, ses conditions et sa date dépendent du contrat, qui n'est pas exécuté par l'application.

Exemple strictement fictif : nominal 1 000 EUR, avance 80 %, commission 2 %, frais fixes 5 EUR, taux annuel 12 %, durée 30 jours et base 360. L'avance est 800 EUR, le montant non avancé 200 EUR, les intérêts 8 EUR, le coût simulé 33 EUR et la trésorerie nette immédiate 767 EUR. **Ces chiffres ne sont ni une offre ni un tarif recommandé.**

Le calcul ne qualifie pas le régime de TVA des frais, une assurance éventuelle, les minimums de contrat, pénalités, garanties personnelles ou frais non renseignés. Il ne fournit pas une TAE/TAEG exhaustive. Une proposition réelle doit être comparée sur le même périmètre et la même durée avec les postes pertinents ajoutés explicitement ou examinés séparément.

Si une cession existe réellement, la déclarer dans le suivi avec sa preuve. Une facture déclarée cédée est exclue du circuit ordinaire d'affectation des encaissements : le règlement par le débiteur au factor exige un suivi adapté. **Une avance du factor n'est pas un paiement du client.** Lever un marquage de cession nécessite également une décision documentée ; aucune démarche externe n'est réalisée par ce changement interne.

## 6. Préparer une note de frais depuis son reçu

Dans **Documents**, importer le PDF, PNG ou JPEG du reçu, puis lancer l'extraction. Choisir **Note de frais** dans la préparation du dossier. Le parcours reste limité à **un reçu par dossier**.

L'OCR peut proposer le commerçant, la date et des montants lorsqu'ils sont explicites dans la pièce. Comparer chaque proposition avec l'original, corriger les erreurs et confirmer les champs retenus. Il ne déduit pas la personne à rembourser, le motif professionnel ou la politique applicable.

La détection du commerçant et de la date dépend des libellés reconnus. Un reçu sans libellé explicite peut nécessiter leur saisie manuelle ; il n'existe pas de reconnaissance universelle de tous les formats. Faire ces corrections pendant la revue du document, avant de créer le dossier.

| Informations | Vérification attendue |
|---|---|
| Commerçant, date, montant TTC, devise | Comparaison avec le reçu original |
| Référence du demandeur | Alias permettant d'identifier la personne dans le référentiel privé, sans collecter des informations inutiles |
| Motif professionnel | Description de l'objet de la dépense |
| Catégorie | Déplacement, repas, hébergement, bureau ou autre |
| Moyen de paiement | Carte personnelle, carte entreprise, espèces, virement ou autre |
| Paiement de la dépense confirmé | Vérification distincte du reçu ; l'OCR ne démontre pas que le paiement a eu lieu |
| Déjà payé par l'entreprise | Réponse explicitement vérifiée |
| Déjà remboursé | Réponse explicitement vérifiée |
| Dépense entièrement professionnelle | Confirmation ; une dépense mixte reste à qualifier |
| Politique interne | Référence/version et confirmation de son application ; limite facultative uniquement avec sa devise |

Une réponse inconnue reste absente ou non confirmée ; elle ne devient pas « non ». Un paiement non confirmé, une dépense déjà payée par l'entreprise, déjà remboursée ou mixte est bloqué dans ce parcours de préparation au remboursement. Le but est de conserver le besoin de décision, pas d'exécuter un second paiement.

Le contrôle recherche également les justificatifs manquants et les doublons possibles selon le commerçant, la date, le montant et la devise, y compris lorsque le demandeur diffère. Un signalement de doublon n'est pas une preuve de fraude. Comparer les reçus et leur contexte avant de décider.

Après confirmation, créer le dossier puis lancer son analyse. Le statut nouveau ou à relire n'est pas un remboursement autorisé. Une validation finale reste une revue interne de préparation ; le paiement appartient au circuit habituel de l'entreprise.

Si le commerçant, la date, le total ou la devise sont modifiés ensuite dans le dossier, leur ancienne preuve de revue ne vaut plus pour ces nouvelles valeurs. Utiliser **Reconfirmer le reçu**, rouvrir l'original, comparer les quatre valeurs et cocher leurs confirmations. La nouvelle revue conserve l'original et la première preuve, ajoute une entrée à l'historique et annule l'analyse et l'approbation précédentes. Relancer l'analyse, puis la revue interne. Une modification concurrente demande de recharger et de recommencer la vérification ; une même pièce accepte dix reconfirmations au maximum. Ne pas effacer la provenance ou créer une seconde demande pour contourner un blocage.

Les changements de contexte — motif, demandeur, paiement ou politique — suivent l'analyse et la revue habituelles. Ils ne permettent pas de remplacer les faits du reçu sans sa reconfirmation documentaire.

La TVA éventuellement extraite est conservée comme information du reçu. Aucun montant récupérable, barème social ou déduction fiscale n'est calculé. Le traitement du salarié, du dirigeant ou de l'autónomo doit être qualifié séparément avec la politique et le régime pertinents. Une dépense à plusieurs taux peut être examinée sur son montant brut sans constituer un contrôle exhaustif de chaque taux ou de leur déductibilité.

## 7. Recette à ajouter avant d'utiliser ces données réelles

Le [dossier de lancement](06-GO-NO-GO.md) reste applicable. Ajouter les essais ci-dessous aux tests d'OCR et de collecte ; relever le compte, la version du code, les identifiants et les résultats effectivement obtenus.

| ID | Essai | Résultat attendu |
|---|---|---|
| F01 | Inscrire une facture non approuvée ou une ancienne version | Refus ; seule la source revue et actuelle est retenue |
| F02 | Ouvrir une facture à 1 000 EUR avec 200 EUR déjà réglés et preuve datée | Restant 800 EUR, ouverture distincte des allocations futures |
| F03 | Prévisualiser puis importer deux fois le même CSV | Aucun effet au seul aperçu ; aucun double paiement au rejeu |
| F04 | Modifier une opération sous la même clé compte/transaction | Conflit explicite ; aucune substitution silencieuse |
| F05 | Affecter une opération antérieure ou égale à la date d'ouverture | Refus pour éviter le double comptage du règlement historique |
| F06 | Affecter 300 EUR puis 500 EUR à la facture de F02 | Restant 500 puis 0 ; aucune troisième affectation excédentaire |
| F07 | Annuler l'allocation de 300 EUR avec motif | Restant 300 EUR, historique conservé ; aucune opération bancaire inverse |
| F08 | Essayer devise ou sens incompatibles, montant excédentaire et validation concurrente | Refus ou conflit sans solde incohérent |
| F09 | Modifier ou réanalyser le dossier source d'une facture déjà au registre | Divergence signalée ; nouvelles allocations/simulations bloquées, annulation conservée ; aucune remise à jour automatique |
| F10 | Simuler le cas fictif puis une facture partiellement payée, contestée ou cédée | Calcul reproductible pour le cas admis ; refus des autres cas dans ce modèle |
| F11 | Reçu avec paiement/remboursement inconnu, puis déjà remboursé ; correction d'un fait du reçu et reconfirmation | Blocage des inconnues ; correction à reconfirmer sur l'original, ancienne analyse/approbation annulée, puis nouvelle analyse requise |
| F12 | Deux reçus potentiellement identiques, dont un avec un autre demandeur, et dépense mixte | Risque de doublon ou décision nécessaire ; aucun remboursement effectué |
| F13 | Essayer les nouvelles écritures avec `reader` puis exporter sans rôle admin | Actions refusées selon la matrice des permissions |
| F14 | Sauvegarder et restaurer avec CSV, allocations et reçu de frais | Original, empreintes, états et historique retrouvés ; rétablissement des accès selon la procédure existante |

Pour F06/F07, utiliser des opérations postérieures à l'ouverture et conserver leur devise et sens. Tous les montants des essais sont fictifs. Les tests du dépôt ne démontrent pas à eux seuls la compatibilité avec les exports d'une banque ou la politique réelle du client.

## 8. Préparer l'activation chez un client

Obtenir un export bancaire minimisé et autorisé, une facture client, une facture fournisseur, un reçu de frais, les soldes d'ouverture vérifiés et la politique de frais applicable. Choisir les alias de compte/demandeur et nommer les personnes qui valident les preuves. Garder les originaux, contrats, relevés et secrets dans l'espace privé du client.

Tester d'abord avec des données fictives, puis avec ce lot restreint sur l'instance qualifiée. Mesurer les erreurs de champ, les correspondances proposées à tort et le temps de revue. Pour l'affacturage, demander au responsable de comparer les hypothèses à une proposition contractuelle qu'il possède déjà ; le logiciel ne contacte personne pour en obtenir une.

Les [six sources primaires FR/ES et les décisions de conception](../research/04-finance-expenses.md) expliquent les limites retenues. Le [rapport QA](../QA.md) indique ce qui a réellement été vérifié dans le dépôt. Le choix d'un hébergement, la restauration hors hôte, les accès réels et l'acceptation du périmètre restent propres à chaque lancement.
