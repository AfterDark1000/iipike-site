/* Manual editorial showcase; native swipe/scroll works without JavaScript. */
(function(){
"use strict";
var section=document.getElementById("dossier");
if(!section)return;
var track=section.querySelector(".dossier-showcase"),slides=Array.from(section.querySelectorAll(".dossier-slide")),thumbs=Array.from(section.querySelectorAll(".dossier-thumb"));
var prev=section.querySelector("[data-dossier-prev]"),next=section.querySelector("[data-dossier-next]"),controls=section.querySelector(".dossier-controls"),count=section.querySelector(".dossier-count");
if(!track||slides.length<2||thumbs.length!==slides.length||!prev||!next||!controls||!count)return;
var index=0;
function offset(i){return slides[i].getBoundingClientRect().left-track.getBoundingClientRect().left+track.scrollLeft}
function update(){
  var best=0,dist=Infinity;
  slides.forEach(function(_,i){var d=Math.abs(offset(i)-track.scrollLeft);if(d<dist){dist=d;best=i}});
  index=best;count.textContent=(index+1)+" / "+slides.length;
  prev.disabled=index===0;next.disabled=index===slides.length-1;
  thumbs.forEach(function(a,i){if(i===index)a.setAttribute("aria-current","true");else a.removeAttribute("aria-current")});
  // Keep selected preview in its own scrolling strip, never move the page.
  var strip=thumbs[index].parentElement, r=thumbs[index].getBoundingClientRect(), sr=strip.getBoundingClientRect();
  if(r.left<sr.left)strip.scrollLeft+=r.left-sr.left;
  if(r.right>sr.right)strip.scrollLeft+=r.right-sr.right;
}
function go(i){
  i=Math.max(0,Math.min(slides.length-1,i));
  track.scrollTo({left:offset(i),behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"instant":"smooth"});
}
thumbs.forEach(function(a,i){a.addEventListener("click",function(e){if(e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;e.preventDefault();go(i)})});
prev.addEventListener("click",function(){go(index-1)});
next.addEventListener("click",function(){go(index+1)});
track.addEventListener("scroll",update,{passive:true});
track.addEventListener("keydown",function(e){
  if(e.target!==track)return;
  var to={ArrowLeft:index-1,ArrowRight:index+1,Home:0,End:slides.length-1}[e.key];
  if(to!==undefined){e.preventDefault();go(to)}
});
window.addEventListener("resize",update,{passive:true});
controls.hidden=false;update();
})();