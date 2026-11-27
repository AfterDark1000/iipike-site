/* Progressive enhancement for local article illustrations. No autoplay. */
(function(){
"use strict";
document.querySelectorAll(".editorial-carousel").forEach(function(gallery){
  var track=gallery.querySelector(".editorial-carousel-track");
  var slides=Array.from(gallery.querySelectorAll(".editorial-carousel-slide"));
  var controls=gallery.querySelector(".editorial-carousel-controls");
  var prev=gallery.querySelector("[data-carousel-prev]"),next=gallery.querySelector("[data-carousel-next]");
  var count=gallery.querySelector(".editorial-carousel-count");
  if(!track||slides.length<2||!controls||!prev||!next||!count)return;
  var index=0;
  function offset(i){return slides[i].getBoundingClientRect().left-track.getBoundingClientRect().left+track.scrollLeft}
  function update(){
    var best=0,dist=Infinity;
    slides.forEach(function(_,i){var d=Math.abs(offset(i)-track.scrollLeft);if(d<dist){dist=d;best=i}});
    index=best;
    count.textContent=(index+1)+" / "+slides.length;
    prev.disabled=index===0;next.disabled=index===slides.length-1;
  }
  function go(i){
    i=Math.max(0,Math.min(slides.length-1,i));
    track.scrollTo({left:offset(i),behavior:window.matchMedia("(prefers-reduced-motion: reduce)").matches?"instant":"smooth"});
  }
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
});
})();