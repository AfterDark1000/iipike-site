/* First-party static listings. Keep real hrefs for crawlers and no-JS readers. */
(function () {
  if (typeof document.querySelector !== "function" || typeof fetch !== "function" ||
      typeof DOMParser !== "function") return;
  var content = document.querySelector("[data-listing-content]");
  var link = document.querySelector("[data-listing-next]");
  if (!content || !link) return;
  var busy = false;
  var directory = new URL("./", location.href);
  function valid(url) {
    return url.origin === location.origin && new URL("./", url).href === directory.href &&
      /^page-([2-9]|[1-9][0-9]+)\.html$/.test(url.pathname.split("/").pop());
  }
  link.dataset.listingReady = "true";
  link.addEventListener("click", async function (event) {
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
    var target = new URL(link.href, location.href);
    if (!valid(target)) return;
    event.preventDefault();
    if (busy) return;
    busy = true;
    link.setAttribute("aria-busy", "true");
    try {
      var response = await fetch(target.href, {credentials:"same-origin"});
      if (!response.ok || new URL(response.url).href !== target.href) throw Error("Listing unavailable");
      var doc = new DOMParser().parseFromString(await response.text(), "text/html");
      var incoming = doc.querySelector("[data-listing-content]");
      var next = doc.querySelector("[data-listing-next]");
      var nextUrl = next ? new URL(next.getAttribute("href"), target) : null;
      if (!incoming || (nextUrl && !valid(nextUrl))) throw Error("Invalid continuation");
      var selector = ".archive-card,.brief-item";
      var key = function (card) {return card.matches(".brief-item") ? card.id : card.getAttribute("href");};
      var seen = new Set(Array.from(content.querySelectorAll(selector), key));
      Array.from(incoming.querySelectorAll(selector)).forEach(function(card){
        var id=key(card);
        if (seen.has(id)) card.remove(); else seen.add(id);
      });
      var firstAdded = null;
      Array.from(incoming.children).forEach(function(day){
        var list=day.querySelector(".rubric-day-list,.brief-day-list");
        if (!list || !list.children.length) return;
        var previous=content.lastElementChild;
        var title=day.querySelector("h2");
        var previousTitle=previous && previous.querySelector("h2");
        var previousList=previous && previous.querySelector(".rubric-day-list,.brief-day-list");
        if (!firstAdded) firstAdded=list.firstElementChild;
        if (previousTitle && title && previousList && previousTitle.textContent===title.textContent) {
          while(list.firstChild) previousList.appendChild(list.firstChild);
        } else content.appendChild(day);
      });
      if (nextUrl) link.href = nextUrl.href;
      else link.parentElement.remove();
      if (firstAdded) {
        firstAdded.setAttribute("tabindex","-1");
        firstAdded.focus({preventScroll:true});
      }
    } catch (error) {
      location.assign(target.href);
    } finally {
      busy = false;
      link.removeAttribute("aria-busy");
    }
  });
})();
