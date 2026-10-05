"""Create clearly synthetic invoices, receipts, bank CSVs and a separate answer key.

Authoring-only utility. Uses reportlab/Pillow/Poppler; never imports into an app,
contacts a customer, connects a bank or changes production behavior.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from finance_demo_cases import invoice_cases, bank_cases
from expense_demo_cases import expense_cases


def register_fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    font_root=Path('/usr/share/fonts/truetype/dejavu')
    for name,filename in [('PackSans','DejaVuSans.ttf'),('PackSans-Bold','DejaVuSans-Bold.ttf')]:
        pdfmetrics.registerFont(TTFont(name,str(font_root/filename)))


def pdf_invoice(path, case):
    from reportlab.pdfgen import canvas
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    p = case['payload']
    spanish = case['country'] == 'ES'
    c = canvas.Canvas(str(path), pagesize=A4, invariant=1, pageCompression=1)
    c.setTitle('Document fictif - ' + p['invoice_number'])
    c.setAuthor('Admin Agent - donnees synthetiques')
    w, h = A4
    c.setFillColor(HexColor('#FFF1D8')); c.rect(0, h-40, w, 40, fill=1, stroke=0)
    c.setFillColor(HexColor('#8A4A00')); c.setFont('PackSans-Bold', 11)
    c.drawString(40, h-25, 'DOCUMENT FICTIF - TEST UNIQUEMENT')
    c.setFillColor(HexColor('#153D38')); c.setFont('PackSans-Bold', 31)
    c.drawString(40, 745, 'FACTURA DE PRUEBA' if spanish else 'FACTURE DE TEST')
    c.setFont('PackSans', 11); c.setFillColor(HexColor('#52736D'))
    c.drawString(40, 722, 'Admin Agent / collection de demonstration / ' + case['id'])
    c.setStrokeColor(HexColor('#D4E2DE')); c.line(40, 702, w-40, 702)
    labels = (('invoice_number','Factura numero' if spanish else 'Facture numero'),
              ('supplier','Proveedor' if spanish else 'Fournisseur'),
              ('customer','Cliente' if spanish else 'Client'),
              ('issue_date','Fecha de emision' if spanish else "Date d'emission"),
              ('due_date','Fecha de vencimiento' if spanish else "Date d'echeance"),
              ('currency','Moneda' if spanish else 'Devise'))
    c.setFillColor(HexColor('#153D38')); c.setFont('PackSans', 12)
    for i, (key,label) in enumerate(labels):
        if p.get(key) is not None:
            c.drawString(40, 677-27*i, label + ': ' + p[key])
    c.setFillColor(HexColor('#EAF2EF')); c.rect(40, 449, w-80, 31, fill=1, stroke=0)
    c.setFillColor(HexColor('#153D38')); c.setFont('PackSans-Bold', 10)
    c.drawString(52, 460, 'CONCEPTO' if spanish else 'DESIGNATION')
    c.drawRightString(w-52, 460, 'BASE / HT')
    c.setFont('PackSans', 11)
    c.drawString(52, 425, 'Servicio de demostracion - cantidad 1' if spanish else 'Prestation de demonstration - quantite 1')
    c.drawRightString(w-52, 425, p['net_amount'])
    c.setStrokeColor(HexColor('#D4E2DE')); c.line(40, 408, w-40, 408)
    amounts = (('net_amount','Base imponible' if spanish else 'Montant HT'),
               ('vat_rate','Tipo IVA' if spanish else 'Taux TVA'),
               ('vat_amount','Importe IVA' if spanish else 'Montant TVA'),
               ('total_amount','Importe total' if spanish else 'Total TTC'))
    for i,(key,label) in enumerate(amounts):
        y=370-33*i
        c.setFont('PackSans-Bold' if key=='total_amount' else 'PackSans', 15 if key=='total_amount' else 12)
        c.drawString(268, y, label + ': ' + p[key] + (' %' if key=='vat_rate' else ''))
    c.setFont('PackSans', 10); c.setFillColor(HexColor('#52736D'))
    for i,line in enumerate(case.get('notes', [])):
        c.drawString(40, 190-15*i, line)
    c.setStrokeColor(HexColor('#D4E2DE')); c.line(40, 112, w-40, 112)
    c.setFont('PackSans-Bold', 10); c.setFillColor(HexColor('#8A4A00'))
    c.drawString(40, 92, 'AUCUNE VALEUR FISCALE OU COMPTABLE')
    c.setFont('PackSans', 9); c.setFillColor(HexColor('#52736D'))
    c.drawString(40, 74, 'Entites, references et prestations inventees. Aucun identifiant fiscal ni IBAN reel.')
    c.drawString(40, 58, 'Ne pas transmettre comme facture commerciale. Aucun paiement a effectuer.')
    c.save()


def pdf_receipt(path, case):
    from reportlab.pdfgen import canvas
    from reportlab.lib.colors import HexColor
    p=case['payload']; spanish=case['country']=='ES'
    w,h=360,570
    c=canvas.Canvas(str(path),pagesize=(w,h),invariant=1,pageCompression=1)
    c.setTitle('Recu fictif - '+case['id']);c.setAuthor('Admin Agent - donnees synthetiques')
    c.setFillColor(HexColor('#FFF1D8'));c.rect(0,h-46,w,46,fill=1,stroke=0)
    c.setFillColor(HexColor('#8A4A00'));c.setFont('PackSans-Bold',10)
    c.drawCentredString(w/2,h-22,'DOCUMENT FICTIF - TEST UNIQUEMENT')
    c.setFillColor(HexColor('#153D38'));c.setFont('PackSans-Bold',21)
    c.drawString(26,484,'RECIBO DE PRUEBA' if spanish else 'RECU DE TEST')
    c.setFont('PackSans',10);c.drawString(26,463,'Collection Admin Agent / '+case['id'])
    c.setStrokeColor(HexColor('#D4E2DE'));c.line(26,445,w-26,445)
    labels=[('merchant','Comercio' if spanish else 'Commercant'),('expense_date','Fecha del recibo' if spanish else 'Date du recu')]
    c.setFont('PackSans',12)
    for i,(key,label) in enumerate(labels):
        if p.get(key):c.drawString(26,415-i*28,label+': '+p[key])
    descriptions={'meals':'Menu demonstration','travel':'Trajet demonstration','lodging':'Nuitee demonstration','office':'Fournitures demonstration','other':'Service demonstration'}
    c.setFont('PackSans',11);c.drawString(26,340,descriptions[p['category']])
    c.drawString(26,316,'Quantite: 1')
    c.setStrokeColor(HexColor('#D4E2DE'));c.line(26,292,w-26,292)
    c.setFont('PackSans-Bold',17)
    c.drawString(26,264,('Importe total' if spanish else 'Total TTC')+': '+p['total_amount'])
    c.setFont('PackSans',12);c.drawString(26,235,('Moneda' if spanish else 'Devise')+': '+p['currency'])
    if p.get('vat_amount') is not None:
        c.drawString(26,207,('Importe IVA' if spanish else 'Montant TVA')+': '+p['vat_amount'])
    c.setFont('PackSans',9);c.setFillColor(HexColor('#52736D'))
    for i,line in enumerate(case.get('notes',[])):c.drawString(26,174-i*15,line)
    c.setStrokeColor(HexColor('#D4E2DE'));c.line(26,105,w-26,105)
    c.setFont('PackSans-Bold',9);c.setFillColor(HexColor('#8A4A00'))
    c.drawString(26,85,'RECU SANS VALEUR COMMERCIALE')
    c.setFont('PackSans',9);c.setFillColor(HexColor('#52736D'))
    c.drawString(26,68,'Aucune transaction reelle. Donnees inventees.')
    c.drawString(26,51,'Le contexte professionnel figure dans le corrige separe.')
    c.save()


def make_png(pdf, output):
    from PIL import Image
    tool=shutil.which('pdftoppm')
    if not tool:raise RuntimeError('Poppler pdftoppm est requis pour les images de test.')
    subprocess.run([tool,'-singlefile','-r','144','-png',str(pdf),str(output.with_suffix(''))],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    with Image.open(output) as image:
        assert image.width*image.height<20_000_000


def write_guide(folder, manifest):
    """Separate operator truth; never print the answer key inside a receipt."""
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    from xml.sax.saxutils import escape
    styles=getSampleStyleSheet()
    for style in styles.byName.values():style.fontName='PackSans-Bold' if 'Heading' in style.name or style.name=='Title' else 'PackSans'
    styles.add(ParagraphStyle('PackBody',fontName='PackSans',fontSize=10,leading=14,spaceAfter=9,textColor=colors.HexColor('#153D38')))
    styles.add(ParagraphStyle('PackCell',fontName='PackSans',fontSize=8,leading=11,textColor=colors.HexColor('#153D38')))
    def p(text,style='PackBody'):return Paragraph(escape(text.replace('—','-').replace('–','-')),styles[style])
    pages=[]
    pages += [p('ADMIN AGENT / KIT DE TEST FICTIF','Title'),p('Factures, notes de frais et banque','Heading1'),p('Date de reference : '+manifest['as_of'])]
    intro=[
        '18 pieces a importer : 10 factures (8 PDF, 2 PNG) et 8 recus de frais (6 PDF, 2 PNG). Les images sont des scans synthetiques propres, pas des photos de terrain.',
        'Tout est invente. Les montants et taux sont des hypotheses de test, sans valeur fiscale. Aucun email, appel bancaire, financement ou remboursement ne doit etre execute.',
        'Utiliser une instance de recette vide, separee de tout client reel. Lancer le mode production de test avec OCR : la demonstration Python sans dependances ne propose pas le parcours documentaire complet.',
        'Importer uniquement les fichiers des dossiers 01_factures et 02_notes_de_frais dans Documents. Le guide et le corrige restent a cote : ils ne doivent pas etre traites comme pieces justificatives.',
        'Dans Documents : Importer une piece > choisir la langue indiquee > Extraire > choisir Controle de facture ou Note de frais > comparer chaque champ a l original > corriger et cocher chaque valeur retenue > Creer le dossier > Analyser > Relire.',
        'Les paiements, litiges et informations de remboursement se saisissent depuis le corrige. Ils ne sont pas prouves par le texte OCR. Un resultat A relire doit encore etre approuve manuellement.',
    ]
    pages += [p(x) for x in intro]
    pages += [p('Ordre conseille','Heading2'),p('1. F01 puis F02 : verifier, approuver, inscrire dans Finances. 2. F03 : tester la simulation avant tout paiement. 3. F04 a F09 : anomalies, retards et ambiguite. 4. F10 : reimporter le doublon exact. 5. E01 a E07, puis E08 en dernier : le doublon de frais bloque aussi E01 lors de sa prochaine analyse.'),p('Les dates sont ancrees au '+manifest['as_of']+'. Pour une recette ulterieure, regenerer le lot avec la date du jour ; ne pas corriger silencieusement les echeances dans les sources.'),PageBreak()]
    for kind,title in [('invoice','Les 10 factures'),('expense','Les 8 notes de frais')]:
        pages += [p(title,'Heading1')]
        rows=[[p('Piece / langue','PackCell'),p('Scenario','PackCell'),p('Resultat attendu','PackCell')]]
        for c in manifest['cases']:
            if c['kind']==kind:
                rows.append([p(c['id']+' / '+c['country']+' / '+c['format'].upper(),'PackCell'),p(c['title'],'PackCell'),p(c['expected']['explanation'],'PackCell')])
        table=Table(rows,colWidths=[75,150,280],repeatRows=1,hAlign='LEFT')
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#EAF2EF')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),('LINEBELOW',(0,0),(-1,-1),.3,colors.HexColor('#D4E2DE'))]))
        pages += [table,Spacer(1,12)]
        if kind=='expense':pages += [p('Contexte a saisir','Heading2'),p('Le fichier 04_corrige/CORRIGE.md contient, pour chaque recu, le demandeur fictif, le motif, la categorie, le moyen de paiement, les confirmations et le plafond de politique. Tous les plafonds sont inventes pour le test. Ne pas recopier automatiquement le corrigé dans un vrai dossier.')]
        pages += [PageBreak()]
    pages += [p('Banque et affacturage','Heading1')]
    opening=next(c['finance']['opening_as_of'] for c in manifest['cases'] if c.get('finance'))
    pages += [p('Ouverture du registre : '+opening+' en fin de journee, deja paye 0.00 EUR. Sens fournisseur pour F02 ; sens client pour F01, F03, F04, F05, F08 et F09. Litige confirme uniquement pour F05. Ne pas inscrire F06/F07 bloques, ni F10 qui est un doublon.')]
    for text in [
        'Dans Finances > Factures : ajouter chaque dossier valide au registre avec le sens, le montant deja paye et la date d ouverture fournis dans le corrige. L ouverture est la fin de cette journee et reste figee.',
        'Dans Banque & rapprochements : utiliser le compte fictif '+manifest['bank']['account_ref']+', charger 03_banque/01_releve.csv, previsualiser puis confirmer. Ne pas importer ce CSV depuis le connecteur de collecte de factures.',
        'F01 : affecter 400.00 EUR, verifier le restant 800.00 EUR, puis affecter 800.00 EUR et verifier le restant zero. Annuler une affectation pour verifier le retour du solde et la trace conservee.',
        'F02 : rapprocher le debit fournisseur. Le montant seul sans reference, une devise differente et un flux de financement ne doivent pas produire un paiement client automatique.',
        'Reimporter le meme CSV : aucun nouveau mouvement. 02_releve_conflit.csv contient un identifiant existant avec montant different : tout le lot doit etre refuse apres le premier import. Les mouvements non rapproches restent visibles.',
        'Avant paiement sur F03 : avance 80 %, commission 1 %, frais fixes 5.00 EUR, interet annuel 6 %, base 360, financement a la date de reference. Sur 30 jours : avance 1920.00, reserve 480.00, frais 29.00, interets 9.60, cout 38.60, net 1881.40 EUR.',
        'Ce calcul n est pas une offre de financement. Une avance du factor ne solde pas une facture client. Aucun compte de banque ni affactureur n est contacte.',
    ]:pages.append(p(text))
    pages += [p('Ce que cette recette verifie','Heading2'),p('La circulation des pieces, la correction OCR, la revue humaine, les refus attendus, les soldes et les doublons. Elle ne certifie pas la qualite sur photos reelles, le droit au remboursement, la TVA deductible, l exhaustivite comptable ou le lancement d un client.')]
    categories={'meals':'Repas','travel':'Deplacement','lodging':'Hebergement','office':'Fournitures','other':'Autre'}
    methods={'employee_card':'Carte du demandeur','company_card':'Carte entreprise','cash':'Especes','bank_transfer':'Virement','other':'Autre'}
    expenses=[case for case in manifest['cases'] if case['kind']=='expense']
    for start in (0,4):
        pages += [PageBreak(),p('Fiches de saisie des frais - '+str(start+1)+' a '+str(start+4),'Heading1'),p('Declarations fictives a saisir apres verification du recu. Ces informations ne sont pas extraites par OCR.')]
        for case in expenses[start:start+4]:
            values=case['payload']
            pages += [p(case['id']+' / '+values['merchant']+' / '+values['total_amount']+' '+values['currency'],'Heading3')]
            lines=[('Demandeur',values['employee_ref']),('Motif',values['business_purpose']),('Categorie / paiement',categories[values['category']]+' / '+methods[values['payment_method']]),('Politique / plafond',values['policy_ref']+' / '+values.get('policy_limit','non defini')+' '+values.get('policy_currency',''))]
            rows=[[p(label,'PackCell'),p(value,'PackCell')] for label,value in lines]
            table=Table(rows,colWidths=[115,390],hAlign='LEFT')
            table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(0,-1),colors.HexColor('#EAF2EF')),('LEFTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
            pages += [table,p(' / '.join(label+': '+('OUI' if values[key] else 'NON') for key,label in [('payment_confirmed','Paiement confirme'),('paid_by_company','Paye par entreprise'),('reimbursed','Deja rembourse'),('business_only','Usage professionnel seul'),('policy_confirmed','Politique confirmee')]),'PackCell'),Spacer(1,11)]
    def footer(c,doc):
        c.setFont('PackSans',8);c.setFillColor(colors.HexColor('#52736D'));c.drawString(45,24,'Donnees fictives / Admin Agent / '+manifest['as_of']);c.drawRightString(550,24,str(doc.page))
    SimpleDocTemplate(str(folder/'GUIDE_DE_TEST.pdf'),pagesize=A4,rightMargin=45,leftMargin=45,topMargin=45,bottomMargin=45).build(pages,onFirstPage=footer,onLaterPages=footer)
    lines=['# Corrige du lot fictif Admin Agent','',f"Date de reference : {manifest['as_of']}",'','Ne pas importer ce corrige comme justificatif. Les confirmations ci-dessous sont les hypotheses de la recette uniquement.','']
    for case in manifest['cases']:
        lines += ['## '+case['id']+' - '+case['title'],'',f"Fichier : `{case['file']}`",'',case['expected']['explanation'],'','Valeurs et contexte attendus a verifier/saisir :','','```json',json.dumps(case['payload'],ensure_ascii=False,indent=2),'```','']
        if case.get('finance'):lines += ['Inscription au registre :','','```json',json.dumps(case['finance'],ensure_ascii=False,indent=2),'```','']
    lines += ['## Scenarios bancaires et simulation','','```json',json.dumps(manifest['bank'],ensure_ascii=False,indent=2),'```','']
    (folder/'04_corrige'/'CORRIGE.md').write_text('\n'.join(lines),encoding='utf-8')
    readme=f'''KIT DE TEST ADMIN AGENT - PIECES ENTIEREMENT FICTIVES
Date de reference : {manifest['as_of']}

1. Ouvrir GUIDE_DE_TEST.pdf et suivre l'ordre indique.
2. Importer 01_factures et 02_notes_de_frais dans Documents, une piece a la fois.
3. Choisir la langue du corrigé. Confirmer chaque champ et le contexte.
4. Utiliser les CSV de 03_banque uniquement dans Finances > Banque & rapprochements.
5. Consulter 04_corrige/CORRIGE.md pour les valeurs, situations et resultats attendus.

Ne pas importer le guide, le corrige ou un CSV bancaire comme une facture.
F10 est volontairement identique a F01 : un seul document doit etre conserve.
E08 ressemble a E01 : l'alerte de doublon est attendue ; le tester en dernier.
Le montant d'ouverture est fige. Utiliser une instance de test vide, jamais une base client.
Aucun identifiant reel, paiement, remboursement, email ou financement.

Guide de fonctionnement :
https://github.com/Floums08/admin-agent/blob/main/docs/launch/09-FINANCE-ET-FRAIS.md
'''
    (folder/'LIRE_EN_PREMIER.txt').write_text(readme,encoding='utf-8')


def generate_pack(folder, as_of):
    register_fonts()
    folder=Path(folder).resolve()
    if folder.exists():raise ValueError('Le dossier de sortie existe deja ; choisir un nouveau chemin.')
    # Generated binaries must never enter the source repository by accident.
    if folder.is_relative_to(ROOT) and not folder.is_relative_to(ROOT/'runtime'):
        raise ValueError('Dans le depot, les documents generes doivent rester sous runtime/.')
    cases=deepcopy(invoice_cases(as_of)+expense_cases(as_of))
    folder.mkdir(parents=True)
    for name in ('01_factures','02_notes_de_frais','03_banque','04_corrige'):(folder/name).mkdir()
    files={}
    for case in cases:
        directory='01_factures' if case['kind']=='invoice' else '02_notes_de_frais'
        relative=f"{directory}/{case['id']}_fictif.{case['format']}"
        target=folder/relative
        case['file']=relative
        case['skill_id']='invoice-check' if case['kind']=='invoice' else 'expense-review'
        if case.get('duplicate_of') and case.get('duplicate_kind','exact')=='exact':
            shutil.copyfile(files[case['duplicate_of']],target)
        else:
            renderer=pdf_invoice if case['kind']=='invoice' else pdf_receipt
            if case['format']=='pdf':renderer(target,case)
            else:
                with tempfile.TemporaryDirectory(prefix='admin-agent-render-') as temporary:
                    pdf=Path(temporary)/'source.pdf';renderer(pdf,case);make_png(pdf,target)
        files[case['id']]=target
        case['sha256']=hashlib.sha256(target.read_bytes()).hexdigest()
    bank=bank_cases(as_of)
    csv_text=bank.pop('csv_text')
    bank['file']='03_banque/01_releve.csv'
    (folder/bank['file']).write_text(csv_text,encoding='utf-8',newline='')
    # A repeat transaction identity with a conflicting amount rejects the batch.
    import csv,io
    rows=list(csv.reader(io.StringIO(csv_text)))
    conflict=[rows[0],list(rows[1])];conflict[1][2]='399.00'
    buffer=io.StringIO(newline='');writer=csv.writer(buffer,lineterminator='\n');writer.writerows(conflict)
    (folder/'03_banque'/'02_releve_conflit.csv').write_text(buffer.getvalue(),encoding='utf-8')
    manifest={'schema_version':1,'synthetic':True,'as_of':as_of.isoformat(),'cases':cases,'bank':bank}
    (folder/'04_corrige'/'attendus.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    write_guide(folder,manifest)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--as-of',type=date.fromisoformat,default=date.today())
    args=parser.parse_args()
    result=generate_pack(args.output,args.as_of)
    print(f"{len(result['cases'])} pieces fictives et leur guide generes dans {args.output.resolve()}")


if __name__=='__main__':main()
