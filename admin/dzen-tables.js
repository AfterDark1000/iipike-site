/* HPII deterministic table illustrations. Local Canvas only; no network or AI. */
(function(root){
"use strict";
function cells(line){
  line=line.trim();const out=[];let cell="",n=0;
  for(let i=0;i<line.length;i++){
    const ch=line[i];
    if(ch==="\\"&&i+1<line.length&&["|","\\"].includes(line[i+1])){cell+=line[++i];continue}
    if(ch==="|"){out.push(cell.trim());cell="";n++}else cell+=ch;
  }
  if(!n)return null;
  out.push(cell.trim());
  if(line.startsWith("|"))out.shift();
  if(cell===""&&out[out.length-1]==="")out.pop();
  return out;
}
function splitMarkdown(source){
  const lines=source.replace(/\r\n/g,"\n").split("\n"),parts=[],tables=[],errors=[];
  let text=[];
  function flush(){if(text.length){parts.push({kind:"text",text:text.join("\n")});text=[]}}
  for(let i=0;i<lines.length;i++){
    const headers=cells(lines[i]),sep=headers&&i+1<lines.length?cells(lines[i+1]):null;
    if(!sep||!sep.length||!sep.every(x=>/^:?-{3,}:?$/.test(x))){text.push(lines[i]);continue}
    const start=i,rows=[];let j=i+2;
    for(;j<lines.length&&lines[j].trim();j++){const row=cells(lines[j]);if(!row)break;rows.push(row)}
    i=j-1;
    const raw=lines.slice(start,j).join("\n");
    const valid=headers.length>=1&&headers.length<=12&&headers.length===sep.length&&
      headers.some(x=>x.trim())&&rows.length>=1&&rows.length<=100&&
      [headers,...rows].every(row=>row.length===headers.length&&row.every(x=>x.length<=2000&&!/[\x00-\x1f]/.test(x)));
    if(!valid){errors.push("Таблица у строки "+(start+1)+": не совпадают размеры или превышены ограничения.");text.push(raw);continue}
    flush();
    const table={kind:"table",number:tables.length+1,headers,rows,align:sep.map(x=>x.endsWith(":")?(x.startsWith(":")?"center":"right"):"left"),raw};
    tables.push(table);parts.push(table);
  }
  flush();return {parts,tables,errors};
}
function tableHtml(table,inline){
  function row(items,tag){return "<tr>"+items.map((x,i)=>"<"+tag+(tag==="th"?' scope="col"':"")+' style="text-align:'+table.align[i]+'">'+inline(x)+"</"+tag+">").join("")+"</tr>"}
  return '<table class="dzen-preview-table"><thead>'+row(table.headers,"th")+"</thead><tbody>"+table.rows.map(x=>row(x,"td")).join("")+"</tbody></table>";
}
// Same supported inline syntax as site_rich_text: labels, bold, italic.
// Canvas receives text only, never HTML; literal characters are preserved.
function runs(text,header=false){
  const pattern=/\[([^\]\n]{1,200})\]\(([^)\n]{1,2000})\)|\*\*([^*\n]{1,3000})\*\*|\*([^*\n]{1,3000})\*/g;
  let pos=0,result=[],m;
  const add=(s,style)=>{if(s)result.push({text:s,style:header?"bold":style})};
  while((m=pattern.exec(text))){add(text.slice(pos,m.index),"normal");add(m[1]??m[3]??m[4],m[1]!==undefined?"link":m[3]!==undefined?"bold":"italic");pos=pattern.lastIndex}
  add(text.slice(pos),"normal");return result;
}
const FONT=32,LINE=44,PAD=22,MARGIN=48,TOP=118,FOOT=76,MAX_PAGE=2400;
const font=style=>(style==="bold"?"700 ":style==="italic"?"italic ":"400 ")+FONT+'px Arial, "DejaVu Sans", sans-serif';
function measure(ctx,s,style){ctx.font=font(style);return ctx.measureText(s).width}
function wrap(ctx,value,width,header){
  const result=[];let line=[],used=0;
  function flush(){result.push({runs:line,width:used});line=[];used=0}
  for(const run of runs(value,header)){
    for(const word of run.text.match(/\s+|[^\s]+/gu)||[]){
      const size=measure(ctx,word,run.style);
      if(size<=width){
        if(line.length&&used+size>width)flush();
        // Discard only layout whitespace at a new line; never truncate content.
        if(!line.length&&/^\s+$/.test(word))continue;
        line.push({text:word,style:run.style,width:size});used+=size;continue;
      }
      for(const ch of Array.from(word)){
        const w=measure(ctx,ch,run.style);
        if(line.length&&used+w>width)flush();
        line.push({text:ch,style:run.style,width:w});used+=w;
      }
    }
  }
  if(line.length||!result.length)flush();
  return result;
}
function layout(table,ctx){
  const n=table.headers.length;
  // Wide tables get a wider bitmap, instead of unreadably tiny text.
  const width=Math.max(1600,Math.min(3200,96+n*256)),available=width-2*MARGIN;
  const weights=table.headers.map((h,i)=>{
    const sample=[h,...table.rows.map(r=>r[i])];
    return Math.max(1,Math.min(3.3,Math.sqrt(Math.max(...sample.map(s=>Array.from(s).length),1)/12)));
  });
  const min=145,extra=available-min*n,sum=weights.reduce((x,y)=>x+y,0);
  const columns=weights.map(w=>Math.floor(min+extra*w/sum));
  columns[n-1]+=available-columns.reduce((x,y)=>x+y,0);
  const make=(row,header)=>({lines:row.map((v,i)=>wrap(ctx,v,columns[i]-2*PAD,header))});
  const height=r=>Math.max(...r.lines.map(x=>x.length))*LINE+2*PAD;
  const header=make(table.headers,true);header.height=height(header);
  if(header.height+TOP+FOOT+LINE+2*PAD>MAX_PAGE)throw Error("Шапка слишком высокая для читаемой картинки. Сократите заголовки таблицы.");
  const maxLines=Math.max(1,Math.floor((MAX_PAGE-TOP-FOOT-header.height-2*PAD)/LINE));
  const fragments=[];
  table.rows.forEach((r,i)=>{
    const row=make(r,false),count=Math.max(...row.lines.map(x=>x.length));
    for(let start=0;start<count;start+=maxLines){
      const fragment={index:i,lines:row.lines.map(x=>x.slice(start,start+maxLines))};
      fragment.height=height(fragment);fragments.push(fragment);
    }
  });
  const pages=[];let page=[],h=TOP+header.height+FOOT;
  for(const row of fragments){
    if(page.length&&h+row.height>MAX_PAGE){pages.push({rows:page,height:h});page=[];h=TOP+header.height+FOOT}
    page.push(row);h+=row.height;
  }
  if(page.length)pages.push({rows:page,height:h});
  return {width,columns,header,pages};
}
function draw(table,plan,index,canvas){
  const page=plan.pages[index];canvas.width=plan.width;canvas.height=page.height;
  const ctx=canvas.getContext("2d");
  if(!ctx)throw Error("Canvas недоступен");
  ctx.fillStyle="#f6f3eb";ctx.fillRect(0,0,canvas.width,canvas.height);
  ctx.fillStyle="#9b482a";ctx.fillRect(MARGIN,36,66,52);
  ctx.font="700 25px Arial, sans-serif";ctx.fillStyle="#ffffff";ctx.textAlign="center";ctx.textBaseline="middle";ctx.fillText("ХПИ",MARGIN+33,62);
  ctx.textAlign="left";ctx.fillStyle="#242b28";ctx.font="700 29px Arial, sans-serif";ctx.fillText("ХРОНИКИ ПИКИРУЮЩЕГО ИИ",MARGIN+84,51);
  ctx.font="400 22px Arial, sans-serif";ctx.fillStyle="#626b63";ctx.fillText("ТАБЛИЦА "+table.number+(plan.pages.length>1?"  /  ЧАСТЬ "+(index+1)+" ИЗ "+plan.pages.length:""),MARGIN+84,79);
  let y=TOP;
  function paint(row,header){
    ctx.fillStyle=header?"#233b30":row.index%2===0?"#fffdf6":"#eae5db";
    ctx.fillRect(MARGIN,y,canvas.width-2*MARGIN,row.height);
    let x=MARGIN;
    row.lines.forEach((lines,i)=>{
      const col=plan.columns[i];
      for(let j=0;j<lines.length;j++){
        const l=lines[j];let dx=x+PAD;
        if(table.align[i]==="right")dx=x+col-PAD-l.width;
        if(table.align[i]==="center")dx=x+(col-l.width)/2;
        for(const run of l.runs){
          ctx.font=font(run.style);ctx.fillStyle=header?"#ffffff":run.style==="link"?"#9b482a":"#242b28";
          ctx.fillText(run.text,dx,y+PAD+LINE/2+j*LINE);dx+=run.width;
        }
      }
      ctx.strokeStyle=header?"#52695b":"#d6d7ce";ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x+col,y);ctx.lineTo(x+col,y+row.height);ctx.stroke();
      x+=col;
    });
    ctx.strokeStyle="#d6d7ce";ctx.beginPath();ctx.moveTo(MARGIN,y+row.height);ctx.lineTo(canvas.width-MARGIN,y+row.height);ctx.stroke();
    y+=row.height;
  }
  paint(plan.header,true);for(const row of page.rows)paint(row,false);
  ctx.font="700 23px Arial, sans-serif";ctx.fillStyle="#626b63";ctx.fillText("iipike.ru",MARGIN,canvas.height-FOOT/2);
  return canvas;
}
async function pngFiles(table,slug,makeCanvas){
  const create=makeCanvas||(()=>document.createElement("canvas"));
  const canvas=create(),ctx=canvas.getContext("2d");
  if(!ctx)throw Error("Canvas недоступен");
  const plan=layout(table,ctx),files=[];
  for(let i=0;i<plan.pages.length;i++){
    draw(table,plan,i,canvas);
    const blob=await new Promise((resolve,reject)=>canvas.toBlob(b=>b&&b.size?resolve(b):reject(Error("Не удалось сформировать PNG")),"image/png"));
    files.push({name:slug+"-table-"+String(table.number).padStart(2,"0")+(plan.pages.length>1?"-part-"+String(i+1).padStart(2,"0"):"")+".png",blob});
  }
  canvas.width=1;canvas.height=1;
  return files;
}
const api={cells,splitMarkdown,tableHtml,runs,wrap,layout,draw,pngFiles};
if(typeof module!=="undefined"&&module.exports)module.exports=api;else root.HpiiDzenTables=api;
})(typeof globalThis!=="undefined"?globalThis:this);
