import test from "node:test";
import assert from "node:assert/strict";
import {parseArticle,renderArticle,safeHref} from "../admin/auth/article-preview.mjs";
test("preview preserves article block types and escapes raw markup",()=>{
 const source="**Начало** со [ссылкой](https://example.org).\n\n## Подзаголовок\n\n- Первый\n- Второй\n\n1. Один\n2. Два\n\n> Цитата\n> — Автор\n\n<script>alert(1)</script>";
 const blocks=parseArticle(source,{strict:false});
 assert.deepEqual(blocks.map(b=>b.type),["lead","h2","ul","ol","quote","p"]);
 assert.equal(blocks[4].attribution,"Автор");
 const doc={createElement:tag=>({tag,ownerDocument:doc,children:[],append(n){this.children.push(n)},replaceChildren(){this.children=[]}}),createTextNode:text=>({text})};
 const parent=doc.createElement("div");renderArticle(parent,source);
 assert.equal(parent.children[0].children[0].tag,"strong");
 assert.equal(parent.children[0].children[2].tag,"a");
 assert.equal(parent.children.at(-1).children[0].text,"<script>alert(1)</script>");
 assert.throws(()=>safeHref("javascript:alert(1)"));
 assert.throws(()=>safeHref("https://user@example.org"));
 assert.throws(()=>parseArticle(">цитата",{strict:false}));
 assert.throws(()=>parseArticle("# Неверный заголовок",{strict:false}));
 assert.throws(()=>parseArticle("[ссылка](javascript:alert(1))",{strict:false}));
});
