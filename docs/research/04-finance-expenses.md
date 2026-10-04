# Suivi des factures, affacturage et notes de frais : cadrage sourcé

Recherche ciblée du **4 octobre 2026**, France et Espagne. Elle soutient la conception de quatre outils : registre de factures, simulation indicative d'affacturage, préparation de notes de frais et rapprochement d'un export bancaire. Elle ne constitue ni une proposition de crédit ni une qualification fiscale d'une entreprise.

## Ce que les sources établissent

| Sujet | Constat documenté | Conséquence pour Admin Agent |
|---|---|---|
| Affacturage en France | Bpifrance décrit une avance fondée sur la cession de créances, avec sélection par le factor et conditions contractuelles. Coût de financement, commission de service, frais annexes et garantie doivent être distingués. [F1] | Préparer les informations et une simulation aux hypothèses visibles. Une facture dans le registre ne devient pas automatiquement finançable. |
| Affacturage en Espagne | Banco de España distingue le recours, où le cédant reste exposé à l'impayé, du sans-recours. Le contrat fixe notamment une limite de financement et les débiteurs acceptés. [F2] | Le type de recours et les exclusions relèvent du contrat à examiner. L'outil ne classe aucun financeur, ne sollicite aucune offre et ne promet pas l'acceptation. |
| Frais professionnels salariés en France | L'Urssaf rattache les frais à l'activité professionnelle et distingue remboursement des dépenses réelles justifiées et allocations forfaitaires. [E1] | La première implémentation prépare un reçu avec motif, demandeur et politique interne. Elle ne calcule aucun forfait légal ou kilométrique. |
| TVA française | La DGFiP indique que la déduction dépend du statut de l'entreprise, du justificatif, de l'utilisation et de conditions supplémentaires. [E2] | Une TVA lisible dans un reçu reste une TVA observée. Ne pas la présenter comme automatiquement récupérable. |
| IVA espagnole | L'AEAT énumère plusieurs conditions, dont l'affectation à l'activité, le justificatif conforme et son enregistrement. [E3] | L'OCR ne suffit pas à déterminer un droit à déduction ou à remplir les obligations d'enregistrement. |
| Facture simplifiée espagnole | Pour le droit à déduction avec une facture simplifiée, l'AEAT précise des mentions supplémentaires concernant notamment le destinataire et la taxe. [E4] | Un ticket lisible et un total exact ne suffisent pas à certifier le justificatif fiscal. Le professionnel conserve cette qualification. |

Une confirmation humaine dans l'application est une décision interne de préparation. Elle ne transforme pas un reçu en preuve de paiement, ne confirme pas un remboursement et ne remplace pas le contrat d'un factor ou la politique de frais de l'entreprise.

## Décisions de conception issues de ce cadrage

Les points suivants sont **des choix de produit et de contrôle**, pas des règles réglementaires déduites des sources :

1. **Séparer les états.** Une facture peut être contrôlée, rapprochée partiellement, contestée ou déclarée cédée. Ces dimensions ne doivent pas être réduites à une seule case « payée ».
2. **Conserver le périmètre connu.** Les imports ne prouvent pas que toutes les factures ou toutes les opérations d'un compte ont été chargées. Afficher la date de référence et les éléments non rapprochés.
3. **Conserver les preuves bancaires.** Un CSV importé garde son empreinte, ses références de ligne et ses valeurs d'origine dans la base de l'instance. Une suggestion ne devient allocation qu'après confirmation nominative.
4. **Éviter le double comptage.** Refuser une allocation supérieure au disponible d'une transaction ou au restant documenté d'une facture. Une annulation laisse une trace et restitue seulement le montant concerné.
5. **Respecter le sens des flux et la devise.** Un encaissement client ne s'affecte pas à une facture fournisseur. Une égalité de montants dans deux devises ne constitue pas un rapprochement. Aucun taux de conversion n'est inventé.
6. **Figer les références revues.** Si le dossier source change, le suivi financier doit signaler sa divergence et empêcher d'utiliser silencieusement l'ancienne revue.
7. **Rendre le calcul de financement lisible.** Distinguer nominal, avance, montant non avancé et coûts saisis. Une réserve éventuellement restituable n'est pas traitée comme un coût définitif ; le calendrier réel dépend du contrat.
8. **Laisser les paramètres inconnus inconnus.** Les tarifs d'affacturage sont fournis par l'utilisateur pour un scénario. Aucun taux de marché, score d'éligibilité ou prise en charge du risque n'est déduit automatiquement.
9. **Préparer les frais sans payer.** Pour chaque reçu : identifier le demandeur, le motif, le caractère professionnel, le moyen de paiement, le paiement par l'entreprise, un remboursement antérieur et la politique appliquée. Une réponse absente n'équivaut pas à « non ».
10. **Conserver les exceptions.** Un doublon possible, une dépense mixte ou un montant dépassant une limite interne déclenche une revue. Le même reçu ne doit pas produire plusieurs demandes silencieuses.
11. **Ne pas assimiler les statuts.** La politique d'un salarié, celle d'un dirigeant et le traitement d'un autónomo ne se déduisent ni de la langue du reçu ni du pays sélectionné. Cette version n'implémente pas leurs régimes fiscaux.
12. **Garder les écritures locales.** Aucun ordre de paiement, message client, déclaration, cession de créance, écriture d'ERP ou connexion bancaire directe n'est exécuté par ces outils.

Le [guide opérationnel](../launch/09-FINANCE-ET-FRAIS.md) décrit le périmètre livré et ses tests de recette. Ces choix doivent être vérifiés dans la version du code effectivement déployée ; un document de cadrage n'est pas une preuve d'exécution.

## Sources consultées

Consultation : **2026-10-04** pour les six références. Une date non affichée est signalée comme telle, sans lui substituer la date d'indexation du moteur.

| Réf. | Source primaire et URL | Date affichée | Usage retenu |
|---|---|---|---|
| F1 | [Bpifrance Création — L'affacturage pour renforcer la trésorerie de l'entreprise](https://bpifrance-creation.fr/encyclopedie/financements/credits-a-court-terme/laffacturage-renforcer-tresorerie-lentreprise) | Publication : **avril 2024** ; jour non indiqué | Fonctionnement, sélection contractuelle et catégories de coût/garantie |
| F2 | [Banco de España — Autónomo, puedes adelantar el cobro de tus facturas](https://clientebancario.bde.es/pcb/es/blog/autonomo--puedes-adelantar-el-cobro-de-tus-facturas.html) | **17 janvier 2023** | Recours/sans-recours, limite contractuelle et débiteurs acceptés |
| E1 | [Urssaf — Les frais professionnels](https://www.urssaf.fr/accueil/employeur/beneficier-exonerations/frais-professionnels.html) | Mise à jour indiquée : **7 avril 2026** | Définition et distinction frais réels/forfait ; aucun montant de barème repris |
| E2 | [DGFiP — Comment déduire la TVA sur mes achats ?](https://www.impots.gouv.fr/professionnel/questions/comment-deduire-la-tva-sur-mes-achats) | Publié le **31 mars 2016**, modifié le **5 mars 2026** | Droit à déduction distinct de la présence d'un montant de TVA |
| E3 | [AEAT — ¿Qué requisitos debo cumplir para poder deducir el IVA?](https://sede.agenciatributaria.gob.es/Sede/iva/que-iva-soportado-puedo-deducir/que-requisitos-debo-cumplir-poder-iva.html) | Date non affichée dans le contenu consulté | Conditions cumulatives et justificatif/enregistrement |
| E4 | [AEAT — Facturación IVA : Tipos de factura](https://sede.agenciatributaria.gob.es/Sede/iva/facturacion-registro/facturacion-iva/tipos-factura.html) | Date non affichée dans le contenu consulté | Facture simplifiée et mentions utiles à la qualification du justificatif |

Limite de vérification : pour E1, le contenu pertinent et sa date proviennent de l'extrait indexé de la page officielle ; le chargement direct a renvoyé une erreur lors de cette consultation. Les autres pages ont pu être ouvertes. Aucun barème de remboursement, plafond fiscal, taux d'intérêt actuel ou règle automatique de récupération de TVA n'est intégré à partir de cette recherche.
