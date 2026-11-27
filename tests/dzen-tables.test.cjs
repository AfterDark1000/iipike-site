const test=require("node:test"),assert=require("node:assert/strict");
const T=require("../admin/dzen-tables.js");
const source="Лид.\n\n| Модель | Цена | Примечание |\n| --- | ---: | :---: |\n| **A** | 42 | [источник](https://example.org/) |\n| B \\| C | 12 | |\n\nДальше.";
test("parse ordered tables, alignments, empty cells and escaped pipes",()=>{
 const p=T.splitMarkdown(source);
 assert.deepEqual(p.parts.map(x=>x.kind),["text","table","text"]);
 assert.deepEqual(p.tables[0].rows[1],["B | C","12",""]);
 assert.deepEqual(p.tables[0].align,["left","right","center"]);
 assert.equal(p.tables[0].number,1);
 assert.equal(p.parts[2].text,"\nДальше.");
});
test("multiple tables, optional boundary pipes, rejects ragged rows without dropping text",()=>{
 const p=T.splitMarkdown(source+"\n\nИмя | Значение\n--- | ---:\nA | 12\n\n| A | B |\n| --- | --- |\n| x | y | z |");
 assert.equal(p.tables.length,2);assert.equal(p.tables[1].number,2);
 assert.equal(p.errors.length,1);assert.ok(p.parts.at(-1).text.includes("| x | y | z |"));
});
test("uses inline text and safe caller escaping in preview",()=>{
 const p=T.splitMarkdown(source).tables[0];
 assert.deepEqual(T.runs("**A** [ссылка](https://example.org) *B* <b>"),[
 {text:"A",style:"bold"},{text:" ",style:"normal"},{text:"ссылка",style:"link"},
 {text:" ",style:"normal"},{text:"B",style:"italic"},{text:" <b>",style:"normal"}]);
 const html=T.tableHtml(p,x=>x.replace(/</g,"&lt;"));
 assert.ok(html.includes('scope="col"'));assert.ok(html.includes('text-align:right'));assert.ok(html.includes("B | C"));
});
test("layout never crops a long row; paginates with repeat headers",()=>{
 const ctx={measureText:s=>({width:Array.from(s).length*18})};
 const table={number:1,headers:["A","B"],rows:Array.from({length:100},(_,i)=>["Слово ".repeat(i===0?300:15),String(i)]),align:["left","right"]};
 const p=T.layout(table,ctx);
 assert.ok(p.pages.length>1);
 assert.ok(p.pages.every(x=>x.height<=2400));
 const rows=p.pages.flatMap(x=>x.rows);
 assert.equal(new Set(rows.map(x=>x.index)).size,100);
 assert.ok(rows.filter(x=>x.index===0).length>1||rows[0].lines[0].length>1);
 assert.equal(p.columns.reduce((a,b)=>a+b,0),p.width-96);
});