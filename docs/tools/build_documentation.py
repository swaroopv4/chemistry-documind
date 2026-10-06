"""Build the technical PDF from its Markdown source and checked-in figures."""
from pathlib import Path
import re
from xml.sax.saxutils import escape
from PIL import Image as PILImage
from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, PageBreak, Table, TableStyle, Image, KeepTogether, Preformatted
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'TECHNICAL_GUIDE.md'
OUTPUT=ROOT/'reference/DocuMind_Chemistry_Technical_Documentation.pdf'
OUTPUT.parent.mkdir(parents=True,exist_ok=True)
WIDTH,HEIGHT=A4
MARGIN=48
CONTENT=WIDTH-2*MARGIN
styles=getSampleStyleSheet()
styles.add(ParagraphStyle(name='DocTitle',fontName='Helvetica-Bold',fontSize=24,leading=29,textColor=colors.black,spaceAfter=15))
styles.add(ParagraphStyle(name='Section',fontName='Helvetica-Bold',fontSize=16,leading=20,textColor=colors.black,spaceAfter=13,keepWithNext=True))
styles.add(ParagraphStyle(name='BodyTextDoc',fontName='Helvetica',fontSize=10.1,leading=14.2,spaceAfter=9,textColor=colors.HexColor('#20252b')))
styles.add(ParagraphStyle(name='Meta',fontName='Helvetica',fontSize=9,leading=13,spaceAfter=10,textColor=colors.HexColor('#4c535c')))
styles.add(ParagraphStyle(name='Cell',fontName='Helvetica',fontSize=8.6,leading=11.8,textColor=colors.black))
styles.add(ParagraphStyle(name='CellHead',fontName='Helvetica-Bold',fontSize=8.7,leading=12,textColor=colors.white))
styles.add(ParagraphStyle(name='CodeDoc',fontName='Courier',fontSize=8,leading=11,spaceBefore=3,spaceAfter=10,backColor=colors.HexColor('#f2f4f6'),borderPadding=8))
styles.add(ParagraphStyle(name='CaptionDoc',fontName='Helvetica',fontSize=8.5,leading=11,textColor=colors.HexColor('#4b535b'),spaceAfter=9))
styles.add(ParagraphStyle(name='ContentsEntry',fontName='Helvetica',fontSize=9.5,leading=16,leftIndent=0,firstLineIndent=0,textColor=colors.black))

def markup(text):
    text=escape(text)
    text=re.sub(r'`([^`]+)`',r'<font name="Courier">\1</font>',text)
    text=re.sub(r'(https?://[^\s<]+)',lambda m:f'<link href="{m[0]}" color="#285f83">{m[0]}</link>',text)
    return text

class Guide(BaseDocTemplate):
    def afterFlowable(self,flowable):
        if isinstance(flowable,Paragraph) and flowable.style.name=='Section':
            title=flowable.getPlainText()
            if title=='Contents':
                return
            key='section-'+title.split()[0]
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(title,key,0)
            self.notify('TOCEntry',(0,title,self.page,key))

def page(canvas,document):
    canvas.saveState()
    canvas.setFillColor(colors.HexColor('#555b64'))
    canvas.setFont('Helvetica',8)
    if document.page>1:
        canvas.drawString(MARGIN,HEIGHT-29,'DocuMind Chemistry  |  Technical documentation  |  Version 1.0')
    canvas.drawString(MARGIN,25,'6 October 2026')
    canvas.drawRightString(WIDTH-MARGIN,25,str(document.page))
    canvas.restoreState()

doc=Guide(str(OUTPUT),pagesize=A4,leftMargin=MARGIN,rightMargin=MARGIN,topMargin=48,bottomMargin=44,title='DocuMind Chemistry Technical Documentation',author='Venkat Swaroop Veerla',subject='Architecture workflows security deployment and operations')
doc.addPageTemplates(PageTemplate(id='standard',frames=[Frame(MARGIN,44,CONTENT,HEIGHT-92,id='body',leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)],onPage=page))
lines=SOURCE.read_text(encoding='utf8').splitlines()
story=[]
headings=[line[3:] for line in lines if line.startswith('## ')]
i=0;cover_done=False
while i<len(lines):
    line=lines[i]
    if not line.strip():i+=1;continue
    if line.startswith('# '):story.append(Paragraph(markup(line[2:]),styles['DocTitle']));i+=1;continue
    if line.startswith('## '):
        if not cover_done:
            story.append(Spacer(1,12));story.append(Paragraph('Contents',styles['Section']))
            toc=TableOfContents();toc.levelStyles=[styles['ContentsEntry']];story.append(toc)
            cover_done=True
        story.append(PageBreak());story.append(Paragraph(markup(line[3:]),styles['Section']));i+=1;continue
    if line.startswith('!['):
        match=re.match(r'!\[(.*?)\]\((.*?)\)',line)
        image_path=ROOT/match[2]
        w,h=PILImage.open(image_path).size
        image=Image(str(image_path),width=CONTENT,height=CONTENT*h/w)
        story.append(KeepTogether([image,Spacer(1,5),Paragraph(markup(match[1]),styles['CaptionDoc'])]));i+=1;continue
    if line.startswith('|'):
        rows=[]
        while i<len(lines) and lines[i].startswith('|'):
            cells=[cell.strip() for cell in lines[i].strip('|').split('|')]
            if not all(re.fullmatch(r':?-+:?',cell) for cell in cells):rows.append(cells)
            i+=1
        n=len(rows[0])
        if n==2:widths=[CONTENT*.30,CONTENT*.70]
        elif rows[0][0]=='Operation':widths=[CONTENT*.46,CONTENT*.22,CONTENT*.32]
        elif rows[0][0]=='Setting':widths=[CONTENT*.28,CONTENT*.32,CONTENT*.40]
        elif rows[0][0]=='Data':widths=[CONTENT*.27,CONTENT*.28,CONTENT*.45]
        else:widths=[CONTENT*.24,CONTENT*.34,CONTENT*.42]
        table=Table([[Paragraph(markup(value),styles['CellHead'] if r==0 else styles['Cell']) for value in row] for r,row in enumerate(rows)],colWidths=widths,repeatRows=1,hAlign='LEFT')
        commands=[('BACKGROUND',(0,0),(-1,0),colors.HexColor('#344654')),('GRID',(0,0),(-1,-1),.45,colors.HexColor('#d9d9d9')),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]
        for row in range(2,len(rows),2):commands.append(('BACKGROUND',(0,row),(-1,row),colors.HexColor('#f4f6f8')))
        table.setStyle(TableStyle(commands));story.append(table);story.append(Spacer(1,11));continue
    if line.startswith('```'):
        i+=1;code=[]
        while i<len(lines) and not lines[i].startswith('```'):code.append(lines[i]);i+=1
        story.append(Preformatted('\n'.join(code),styles['CodeDoc'],maxLineLength=93));i+=1;continue
    if line.startswith('- '):
        story.append(Paragraph(markup(line[2:]),styles['BodyTextDoc'],bulletText='\u2022'));i+=1;continue
    para=[line];i+=1
    while i<len(lines) and lines[i].strip() and not lines[i].startswith(('#','|','![','```','- ')):
        para.append(lines[i]);i+=1
    style='Meta' if para[0].startswith('Version ') else 'BodyTextDoc'
    story.append(Paragraph(markup(' '.join(para)),styles[style]))
doc.multiBuild(story)
print(OUTPUT)
