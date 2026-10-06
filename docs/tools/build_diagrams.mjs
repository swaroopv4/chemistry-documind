import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const require = createRequire(import.meta.url);
const sharp = require('sharp');
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const out=path.join(root,'diagrams');
await fs.mkdir(out,{recursive:true});
const icons={};
for(const name of ['azure','docker','google','python','redis','sqlite','streamlit','github']){
  const svg=await fs.readFile(path.join(root,'assets','icons',name+'.svg'),'utf8');
  const view=(svg.match(/viewBox="([^"]+)"/)||[])[1]||'0 0 128 128';
  icons[name]={view,body:svg.replace(/^[\s\S]*?<svg[^>]*>/,'').replace(/<\/svg>[\s\S]*$/,'')};
}
const color='#283746', blue='#285f83';
const esc=s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;');
let pieces=[];
function start(w,h,description){pieces=[`<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img"><title>${esc(description)}</title><defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10Z" fill="${blue}"/></marker></defs><rect width="100%" height="100%" fill="white"/>`];}
function text(x,y,value,size=20,fill=color,anchor='middle',weight='normal'){pieces.push(`<text x="${x}" y="${y}" text-anchor="${anchor}" font-family="Arial, sans-serif" font-size="${size}" font-weight="${weight}" fill="${fill}">${esc(value)}</text>`);}
function arrow(d,label,x,y,dashed=false){pieces.push(`<path d="${d}" fill="none" stroke="${blue}" stroke-width="2.3" marker-end="url(#arrow)"${dashed?' stroke-dasharray="6 5"':''}/>`);if(label)text(x,y,label,17,blue);}
function symbol(name,x,y){
 let body='';
 if(name==='user') body='<circle cx="0" cy="-12" r="13"/><path d="M-26 24Q-25 2 0 2Q25 2 26 24"/>';
 if(name==='shield') body='<path d="M0 -30L25 -20V2Q23 24 0 32Q-23 24 -25 2V-20Z"/><path d="M-12 0L-2 10L15 -10"/>';
 if(name==='file') body='<path d="M-22 -29H10L24 -15V29H-22Z"/><path d="M10 -29V-15H24M-12 -2H13M-12 8H13M-12 18H7"/>';
 if(name==='worker') body='<circle r="22"/><path d="M0 -33V-23M0 23V33M-33 0H-23M23 0H33M-24 -24L-17 -17M17 17L24 24M24 -24L17 -17M-17 17L-24 24"/><circle r="8"/>';
 if(name==='vector') body='<circle cx="-22" cy="-18" r="7"/><circle cx="23" cy="-22" r="7"/><circle cx="15" cy="24" r="7"/><circle cx="-22" cy="22" r="7"/><circle r="7"/><path d="M-16 -13L-6 -4M7 -5L17 -16M4 7L12 18M-7 6L-16 17M-15 22H8"/>';
 if(name==='cpu') body='<rect x="-22" y="-22" width="44" height="44" rx="3"/><rect x="-10" y="-10" width="20" height="20" rx="2"/><path d="M-12 -32V-22M0 -32V-22M12 -32V-22M-12 22V32M0 22V32M12 22V32M-32 -12H-22M-32 0H-22M-32 12H-22M22 -12H32M22 0H32M22 12H32"/>';
 if(name==='review') body='<path d="M-25 -25H17V8M-25 -25V25H0M-16 -14H8M-16 -4H8M-16 6H-3M-1 18L9 28L30 3"/>';
 if(name==='merge') body='<path d="M-28 -23L0 0L28 0M-28 23L0 0"/><circle cx="-28" cy="-23" r="5"/><circle cx="-28" cy="23" r="5"/><circle cx="28" r="5"/>';
 if(name==='search') body='<circle cx="-5" cy="-5" r="20"/><path d="M10 10L29 29M-16 -5H6M-5 -16V6"/>';
 if(name==='chat') body='<path d="M-29 -22H29V17H-7L-23 30V17H-29Z"/><path d="M-18 -8H18M-18 3H10"/>';
 pieces.push(`<g transform="translate(${x},${y})" fill="none" stroke="${blue}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">${body}</g>`);
}
function node(x,y,icon,label,subtitle='',number=''){
 pieces.push(`<circle cx="${x}" cy="${y}" r="46" fill="white" stroke="#d7e0e7" stroke-width="1.5"/>`);
 if(icons[icon]){const a=icons[icon];pieces.push(`<svg x="${x-29}" y="${y-29}" width="58" height="58" viewBox="${a.view}">${a.body}</svg>`);}else symbol(icon,x,y);
 if(number){pieces.push(`<circle cx="${x-34}" cy="${y-35}" r="13" fill="${blue}"/>`);text(x-34,y-30,number,15,'white','middle','bold');}
 text(x,y+73,label,21,color,'middle','bold');if(subtitle)text(x,y+96,subtitle,17,'#556573');
}
async function save(name){pieces.push('</svg>');const svg=pieces.join('');await fs.writeFile(path.join(out,name+'.svg'),svg);await sharp(Buffer.from(svg)).resize({width:2400}).png().toFile(path.join(out,name+'.png'));}

start(1400,965,'System architecture with an Azure VM boundary and external identity and AI services');
pieces.push('<rect x="235" y="225" width="855" height="685" rx="12" fill="#f8fafb" stroke="#a6b7c5" stroke-dasharray="8 5"/>');
pieces.push(`<svg x="252" y="240" width="32" height="32" viewBox="${icons.azure.view}">${icons.azure.body}</svg><svg x="295" y="240" width="38" height="32" viewBox="${icons.docker.view}">${icons.docker.body}</svg>`);
text(347,265,'Azure VM',19,color,'start','bold');
text(740,265,'Private Docker network',19,color,'start','bold');
arrow('M145 330H292','HTTPS',214,313);arrow('M386 330H554','private HTTP',470,313);
arrow('M600 196V282','verified claims',706,212);
arrow('M647 330H1202','query and embeddings',934,313);
arrow('M643 350H1140V670H1202','selected evidence',1240,514);
arrow('M632 367L773 538','submit jobs',804,448);
arrow('M754 580H700V800H608','consume',751,724);
arrow('M562 358L377 541','exact answers',362,471);
arrow('M639 359L990 468V750','shared state',1024,584);
arrow('M599 774L715 735H1125V375H1215','worker embedding',900,722);
arrow('M607 805H944','state and keywords',780,835);
node(95,330,'user','Browser','student or admin');node(340,330,'shield','Caddy','HTTPS proxy');node(600,330,'streamlit','Streamlit','app and role checks');node(600,80,'google','Google','verified UCI identity');
node(350,580,'redis','Answer Redis','disposable cache');node(800,580,'redis','Broker Redis','queue and results');node(560,800,'worker','Celery','ingestion worker');node(990,800,'sqlite','SQLite','state and BM25');node(1250,330,'vector','Pinecone','vectors and embeddings');node(1250,670,'cpu','Groq','generation and judges');
text(90,950,'Solid arrows show data movement. HTTPS is public; HTTP redirects. SSH is source limited.',17,color,'start');
await save('system-architecture');

start(1320,580,'Document ingestion from administrator upload through queue and worker to private indexed content and reviewed publication');pieces.push('<g transform="translate(60 15)">');
for(const [d,l,x,y] of [['M155 120H335','validate',250,105],['M425 120H605','reserve ID',515,105],['M695 120H875','queue',785,105],['M963 120H1080V340H968','process',1120,241],['M875 340H695','embed and write',785,325],['M605 340H425','complete',515,325],['M335 340H155','review',245,325]])arrow(d,l,x,y);
node(110,120,'file','Upload','supported file',1);node(380,120,'shield','Validate and version','hash and private policy',2);node(650,120,'redis','Redis queue','one ID per file',3);node(920,120,'worker','Celery worker','concurrency one',4);
node(920,340,'python','Parse and chunk','OCR when needed',5);node(650,340,'vector','Pinecone and SQLite','vector plus BM25 writes',6);node(380,340,'file','Private document','SUCCESS is ingestion',7);node(110,340,'review','Admin publication','review before sharing',8);
text(110,508,'A duplicate byte and parser hash avoids another embedding write. A changed file creates a new version.',18,color,'start');pieces.push('</g>');await save('document-ingestion');

start(1320,600,'Student question pipeline including the safe exact cache path and fresh generation path');pieces.push('<g transform="translate(60 25)">');
for(const [d,l,x,y] of [['M155 120H335','authorize',245,105],['M425 120H605','scope lookup',515,105],['M695 120H875','cache miss',785,105],['M963 120H1080V360H968','allowed',1120,246],['M875 360H695','retrieve',785,345],['M605 360H425','evidence',515,345],['M335 360H155','validate',245,345]])arrow(d,l,x,y);
arrow('M650 70V30H-30V360H63','safe cache hit bypasses embedding and model calls',354,23,true);
node(110,120,'user','Verified student','UCI identity',1);node(380,120,'shield','Input and limits','heuristics and rate counter',2);node(650,120,'redis','Exact answer cache','access scope checked',3);node(920,120,'shield','Input classifier','Groq chemistry gate',4);
node(920,360,'vector','Query embedding','Pinecone inference',5);node(650,360,'merge','Hybrid retrieval','published sources only',6);node(380,360,'cpu','Answer and privacy','Groq plus citation check',7);node(110,360,'chat','Answer and feedback','safe response and citations',8);
text(92,530,'Cache hits still require publication and output checks. Fresh answers normally use three Groq calls.',18,color,'start');pieces.push('</g>');await save('student-question');

start(1320,585,'Independent dense and BM25 retrieval with remote verification and reciprocal rank fusion');pieces.push('<g transform="translate(30 10)">');
arrow('M145 260H284V140H355','embed query',260,167);arrow('M145 260H284V370H355','keyword terms',260,329);
arrow('M445 140H635','ranked vectors',542,121);arrow('M445 370H635','verify remote metadata',542,350);
arrow('M725 140H820V258H905','dense ranks',817,187);arrow('M725 370H820V258H905','verified keyword ranks',806,412);
arrow('M997 258H1088','top k',1044,239);
node(100,260,'search','Question','publication scope');node(400,140,'vector','Pinecone','dense candidates');node(400,370,'sqlite','SQLite FTS5','BM25 candidates');node(680,140,'vector','Dense filter','cosine threshold');node(680,370,'shield','Remote verification','ID and text digest');node(950,258,'merge','Rank fusion','sum 1 / (60 + rank)');node(1135,258,'file','Evidence','bounded passages');
text(80,530,'Keyword failure falls back to dense retrieval. Student publication filters apply before fusion and display.',18,color,'start');pieces.push('</g>');await save('hybrid-retrieval');
console.log('Built four SVG and PNG figures.');
