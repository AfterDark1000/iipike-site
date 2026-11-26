import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
const html=readFileSync(new URL("../admin/auto-corrector/index.html",import.meta.url),"utf8");
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
const helpers=script.slice(script.indexOf("function candidateTitle("),script.indexOf("function render(item)"));
const row={article_id:"test-long-slug",revision:2,version:1,download_url:"https://example.test/candidate"};
const item={schema_version:2,worker:"hpii-chief-copyeditor",article_id:row.article_id,source_revision:2,copyedit_version:1,original_text:{title:"Исходный заголовок"},edited_text:{title:"Новый заголовок"}};
test("picker uses real candidate titles, never slug as visible label",async()=>{
 let response=item;
 const context=vm.createContext({fetch:async()=>({ok:true,json:async()=>response})});
 vm.runInContext(helpers,context);
 assert.equal(await context.readPickerLabel(row),"Новый заголовок");
 response={...item,edited_text:{title:" "}};
 assert.equal(await context.readPickerLabel(row),"Исходный заголовок");
 response={...item,source_revision:3};
 assert.equal(await context.readPickerLabel(row),"");
 assert.match(script,/titles\[i\]\|\|"Материал "/);
 assert.doesNotMatch(script,/new Option\(x\.article_id/);
 assert.match(html,/id="technical-info"/);
 assert.match(html,/id="selected-version"/);
 assert.match(html,/minmax\(0,1fr\)/);
 assert.doesNotThrow(()=>new vm.Script(script));
});

test("copyeditor renders article Markdown as safe semantic HTML nodes",()=>{
 const markdownHelpers=script.slice(script.indexOf("function node("),script.indexOf("function show()"));
 assert.ok(markdownHelpers.includes("function rich(parent,content)"));
 class FakeNode{
  constructor(tag){this.tag=tag;this.children=[];this.textContent="";this.className="";}
  appendChild(child){this.children.push(child);return child;}
 }
 const document={
  createElement:tag=>new FakeNode(tag),
  createTextNode:text=>({tag:"#text",textContent:text,children:[]})
 };
 const context=vm.createContext({document,URL});
 vm.runInContext(markdownHelpers,context);
 const root=new FakeNode("div");
 context.rich(root,["В **Lila Sciences** поручили Nemotron составлять протоколы.","","## Зачем ИИ квантовые точки","","В [опыте с роботом](https://dzen.ru/a/example) результат был виден сразу."].join("\n"));
 assert.deepEqual(root.children.map(x=>x.tag),["p","h2","p"]);
 const first=root.children[0];
 assert.ok(first.children.some(x=>x.tag==="strong"&&x.textContent==="Lila Sciences"));
 const last=root.children[2];
 assert.ok(last.children.some(x=>x.tag==="a"&&x.href==="https://dzen.ru/a/example"));
 assert.doesNotThrow(()=>new vm.Script(script));
});
