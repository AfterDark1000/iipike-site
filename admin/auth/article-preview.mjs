// Shared safe article preview and save-time Markdown preflight.
// Mirrors the supported subset of scripts/site_rich_text.py; never renders raw HTML.
const INLINE=/\[([^\]\n]{1,200})\]\(([^)\n]{1,2000})\)|\*\*([^*\n]{1,3000})\*\*|\*([^*\n]{1,3000})\*/g;
const IMAGE=/^!\[([^\]\n]{1,240})\]\((illustrations\/[a-z0-9]+(?:-[a-z0-9]+)*\/[a-z0-9][a-z0-9_-]{0,79}\.(?:webp|png|jpg|jpeg))\)$/;
const size=s=>Array.from(s).length;
export function safeHref(value){
 if(typeof value!=="string"||value.length>2000||/[\x00-\x20\\<>"]/.test(value)||!value.startsWith("https://"))throw Error("Ссылка должна быть безопасным HTTPS-адресом");
 const u=new URL(value);
 if(u.protocol!=="https:"||!u.hostname||u.username||u.password||u.port)throw Error("Недопустимый адрес ссылки");
 return value;
}
function tokens(value){return Array.from(value.matchAll(INLINE))}
function textCheck(value,limit){
 if(!value.trim()||size(value)>limit)throw Error("Пустой или слишком длинный блок статьи");
 for(const m of tokens(value))if(m[2]!==undefined)safeHref(m[2]);
 return size(value);
}
export function parseArticle(source,{strict=true,articleId=null}={}){
 if(typeof source!=="string"||source.includes("\r")||source.includes("\0")||size(source)>110000)throw Error("Недопустимый текст статьи");
 const blocks=[];let paragraph=[],items=[],kind=null,quote=[];
 const flushP=()=>{if(paragraph.length){blocks.push({type:"p",text:paragraph.join(" ")});paragraph=[]}};
 const flushL=()=>{if(items.length){blocks.push({type:kind,items});items=[]}kind=null};
 const flushQ=()=>{if(quote.length){const b={type:"quote"};if(quote.length>1&&quote.at(-1).startsWith("— "))b.attribution=quote.pop().slice(2).trim();b.text=quote.join(" ");blocks.push(b);quote=[]}};
 const flush=()=>{flushP();flushL();flushQ()};
 for(const [i,line] of source.split("\n").entries()){
  const s=line.trim();if(!s){flush();continue}
  if(s.startsWith(String.fromCharCode(96).repeat(3))||s.startsWith("~~~")||s==="---")throw Error("Неподдерживаемый блок, строка "+(i+1));
  const h=/^(#{1,6})[ \t]+(.+)$/.exec(s);
  if(h){flush();if(![2,3].includes(h[1].length))throw Error("Используй ## или ### для подзаголовка");blocks.push({type:"h"+h[1].length,text:h[2]});continue}
  if(s.startsWith("![")){flush();const m=IMAGE.exec(s);if(!m||(articleId&&!m[2].startsWith("illustrations/"+articleId+"/")))throw Error("Неверная иллюстрация");blocks.push({type:"image",alt:m[1],src:m[2]});continue}
  const ul=/^[-*][ \t]+(.+)$/.exec(s),ol=/^[0-9]{1,2}[.)][ \t]+(.+)$/.exec(s);
  if(ul||ol){flushP();flushQ();const k=ul?"ul":"ol";if(kind!==k)flushL();kind=k;items.push((ul||ol)[1]);continue}
  if(s.startsWith(">")){if(!s.startsWith("> ")||!s.slice(2).trim())throw Error("Цитата: нужен префикс '> ' в строке "+(i+1));flushP();flushL();quote.push(s.slice(2).trim());continue}
  flushL();flushQ();paragraph.push(s);
 }
 flush();if(blocks[0]?.type==="p")blocks[0].type="lead";
 let total=0;
 for(const b of blocks){
  if(b.items){if(b.items.length>24)throw Error("Слишком длинный список");for(const x of b.items)total+=textCheck(x,2000)}
  else if(b.type==="image"){textCheck(b.alt,240)}
  else{total+=textCheck(b.text,b.type==="quote"?3500:12000);if(b.attribution!==undefined)textCheck(b.attribution,240)}
 }
 if(strict&&(size(source)<400||total<400||blocks.length<2||blocks.length>160||blocks[0]?.type!=="lead"))throw Error("Нужна полноценная статья: вступление, текст и не менее 400 символов");
 return blocks;
}
export function renderArticle(parent,source,{articleId=null}={}){
 parent.replaceChildren();
 const blocks=parseArticle(source,{strict:false,articleId});
 const doc=parent.ownerDocument;
 function add(p,tag,value){const n=doc.createElement(tag);if(value!==undefined)n.textContent=value;p.append(n);return n}
 function inline(p,value){
  let pos=0;for(const m of tokens(value)){
   if(m.index>pos)p.append(doc.createTextNode(value.slice(pos,m.index)));
   if(m[2]!==undefined){const a=add(p,"a",m[1]);a.href=safeHref(m[2]);a.target="_blank";a.rel="noopener noreferrer"}
   else add(p,m[3]!==undefined?"strong":"em",m[3]??m[4]);
   pos=m.index+m[0].length;
  }
  if(pos<value.length)p.append(doc.createTextNode(value.slice(pos)));
 }
 for(const b of blocks){
  if(b.items){const list=add(parent,b.type);for(const x of b.items)inline(add(list,"li"),x)}
  else if(b.type==="image"){const f=add(parent,"figure"),img=add(f,"img");img.src="/assets/editorial/inline/"+b.src.slice("illustrations/".length);img.alt=b.alt;img.loading="lazy"}
  else if(b.type==="quote"){const q=add(parent,"blockquote");inline(add(q,"p"),b.text);if(b.attribution)inline(add(add(q,"footer"),"cite"),b.attribution)}
  else{const p=add(parent,b.type==="lead"?"p":b.type);if(b.type==="lead")p.className="lead";inline(p,b.text)}
 }
}
