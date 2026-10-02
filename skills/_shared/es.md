# Espagne : qualification avant application d'une règle

Ressource de routage, pas moteur de conformité. Sources ci-dessous ouvertes et contrôlées le **2026-10-02**. Reconsulter la page concernée au moment d'utiliser une obligation, un seuil ou un calendrier ; aucune date légale ne doit être déduite de la seule présence de ce guide.

## Entrées de qualification

Déterminer autonomo/société, territoire fiscal pertinent, régime IVA/IGIC/autre, activité, type de facture complète/simplifiée/rectificative, B2B/B2C/publique, opération nationale/internationale, exercice et éventuelle administration forale. Pour le social, déterminer l'employeur, le lieu d'emploi et le cadre applicable. Une entreprise « ES » n'implique pas à elle seule un régime fiscal unique.

## Sources officielles par sujet

| Sujet | Source | Utilisation et limite |
|---|---|---|
| Contenu des factures | [AEAT : contenido de las facturas](https://sede.agenciatributaria.gob.es/Sede/iva/facturacion-registro/facturacion-iva/contenido-facturas.html) | Distinguer factures complètes et simplifiées, rectifications et circonstances particulières. Le payload minimal du pilote n'en vérifie pas toutes les mentions. |
| Systèmes informatiques de facturation | [AEAT : délais SIF/RRSIF](https://sede.agenciatributaria.gob.es/Sede/iva/sistemas-informaticos-facturacion-verifactu/nota-informativa-ampliacion-plazo-adaptacion-facturacion.html) | Qualifier le contribuable et les exceptions avant de reprendre un délai. Ne pas confondre ce calendrier avec la facturation électronique B2B. |
| Facturation électronique B2B | [BOE : Real Decreto 238/2026](https://www.boe.es/buscar/act.php?id=BOE-A-2026-7295) | Vérifier les dispositions d'application et le texte déclencheur ; l'entrée en vigueur du décret ne suffit pas à déterminer la date opérationnelle d'une entreprise. |
| Protection des données | [AEPD : Facilita RGPD](https://www.aepd.es/guias-y-herramientas/herramientas/facilita-rgpd) | Aide initiale pour traitements à faible risque ; documents à adapter. Ne pas l'utiliser comme preuve de conformité ni pour conclure sur un traitement à haut risque. |

Pour les calendriers fiscaux, logiciels de facturation, facturation électronique B2B, cotisations et embauche, rechercher les pages actuelles d'AEAT, de la Seguridad Social, du SEPE, de l'administration territoriale compétente et les textes applicables au BOE. Ne pas confondre règles sur les systèmes de facturation et obligation de facture électronique B2B. Aucun calendrier n'est préchargé ici.

## Preuve à conserver par règle utilisée

`{country, topic, official_url, consulted_at, effective_from, scope, claim, source_excerpt_location, applicability_evidence}`. Maintenir explicitement l'inconnu ; conserver le passage pertinent ou son emplacement. Une facture étrangère n'autorise pas à appliquer automatiquement le taux usuel espagnol.

## Limites opérationnelles

Ne pas calculer retenue IRPF, cotisation, déductibilité ou pénalité sur la seule base d'un montant. Transmettre un dossier interne au gestor/comptable, juriste ou responsable RH pour décision. Ne pas déclarer, payer, signer ou contacter des tiers.
