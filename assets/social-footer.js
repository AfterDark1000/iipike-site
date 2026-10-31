/* ХПИИ: единая карта площадок для всех страниц сайта и новых авточерновиков.
 * Без библиотек, сторонних шрифтов, внешних запросов и динамического HTML.
 */
(function () {
  "use strict";
  var platforms = [
    { name: "Дзен", kind: "dzen", label: "Главная лента", url: "https://dzen.ru/iipike" },
    { name: "Telegram", kind: "telegram", label: "Новости в канале", url: "https://t.me/iipike" },
    { name: "ВКонтакте", kind: "vk", label: "Статьи и клипы", url: "https://vk.com/club242308928" },
    { name: "Threads", kind: "threads", label: "Обсуждаем ИИ", url: "https://www.threads.com/@iipike.ai" },
    { name: "X / Twitter", kind: "x", label: "Коротко и по делу", url: "https://x.com/iipike_ai" },
    { name: "MAX", kind: "max", label: "Новости без шума", url: "https://max.ru/channel_iipike" },
    { name: "YouTube", kind: "youtube", label: "Видео и Shorts", url: "https://www.youtube.com/channel/UCCEtLy-Id7ynkGtI_M-OtUQ" },
    { name: "Instagram", kind: "instagram", label: "Публикации на паузе", url: "https://www.instagram.com/iipike.ai/", paused: true }
  ];
  var NS = "http://www.w3.org/2000/svg";

  function el(tag, cls, content) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (content !== undefined) n.textContent = content;
    return n;
  }
  function shape(parent, tag, attrs, content) {
    var node = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    if (content) node.textContent = content;
    parent.appendChild(node);
    return node;
  }
  function icon(kind) {
    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", "24");
    svg.setAttribute("height", "24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    if (kind === "dzen") {
      shape(svg, "path", {d:"M12 2.2c.7 5.6 4.2 9.1 9.8 9.8-5.6.7-9.1 4.2-9.8 9.8-.7-5.6-4.2-9.1-9.8-9.8 5.6-.7 9.1-4.2 9.8-9.8Z",fill:"currentColor"});
    } else if (kind === "telegram") {
      shape(svg, "path", {d:"m21 3.5-2.8 16.7-6.5-4.9-3.5 3.1.6-5.4L20 5.5 6.5 12.3l-3.8-1.4L21 3.5Z",fill:"currentColor", "stroke":"currentColor","stroke-linejoin":"round","stroke-width":".6"});
    } else if (kind === "vk") {
      shape(svg, "rect", {x:"2",y:"4",width:"20",height:"16",rx:"5",fill:"currentColor"});
      shape(svg, "text", {x:"12",y:"15.4","text-anchor":"middle","font-family":"Arial,sans-serif","font-weight":"900","font-size":"9.8",fill:"#20252a"}, "vk");
    } else if (kind === "threads") {
      shape(svg, "path", {d:"M19.7 11.2c-.5-5-3.4-7.7-7.7-7.7-4.7 0-7.8 3.2-7.8 8.6 0 5.5 2.7 8.5 7.6 8.5 4 0 7.4-2.3 7.4-6.1 0-3.4-3.6-5.6-7.7-5.3-2.4.2-3.9 1.5-3.9 3.3 0 1.7 1.3 2.8 3.3 2.8 3.6 0 5.7-3.3 4.1-7.8",fill:"none",stroke:"currentColor","stroke-width":"2","stroke-linecap":"round"});
    } else if (kind === "x") {
      shape(svg, "path", {d:"M4 3h3.8l12.3 18h-3.8L4 3Zm15.4 0L4.6 21",fill:"none",stroke:"currentColor","stroke-width":"2","stroke-linecap":"square"});
    } else if (kind === "max") {
      shape(svg, "path", {d:"M3.5 18V6L12 13.4 20.5 6v12M7.5 9.5v7m9-7v7",fill:"none",stroke:"currentColor","stroke-width":"2.5","stroke-linecap":"round","stroke-linejoin":"round"});
    } else if (kind === "youtube") {
      shape(svg, "rect", {x:"2",y:"5",width:"20",height:"14",rx:"4.5",fill:"currentColor"});
      shape(svg, "path", {d:"m10 8.5 6 3.5-6 3.5Z",fill:"#20252a"});
    } else if (kind === "instagram") {
      shape(svg, "rect", {x:"3",y:"3",width:"18",height:"18",rx:"5",fill:"none",stroke:"currentColor","stroke-width":"2"});
      shape(svg, "circle", {cx:"12",cy:"12",r:"4",fill:"none",stroke:"currentColor","stroke-width":"2"});
      shape(svg, "circle", {cx:"17.5",cy:"6.8",r:"1.2",fill:"currentColor"});
    }
    return svg;
  }

  function mount(footer) {
    if (footer.querySelector(".hpi-social-section")) return;
    var wrap = el("section", "wrap hpi-social-section");
    var heading = el("div", "hpi-social-heading");
    var eyebrow = el("p", "hpi-social-eyebrow", "ХПИИ  /  НА СВЯЗИ");
    var title = el("h2", "hpi-social-title");
    title.id = "hpi-social-heading";
    title.append(document.createTextNode("Читайте нас "),
                 el("em", "", "где удобно."));
    var sub = el("p", "hpi-social-subtitle",
      "В разных лентах, но с одной привычкой — проверять, что ИИ натворил на самом деле.");
    heading.append(eyebrow, title, sub);
    var grid = el("nav", "hpi-social-grid");
    grid.setAttribute("aria-label", "ХПИИ на других площадках");
    platforms.forEach(function (platform) {
      var a = el("a", "hpi-social-card hpi-social-" + platform.kind +
        (platform.paused ? " hpi-social-paused" : ""));
      a.href = platform.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.setAttribute("aria-label", platform.name + " — " + platform.label + " (новая вкладка)");
      var mark = el("span", "hpi-social-mark");
      mark.appendChild(icon(platform.kind));
      var copy = el("span", "hpi-social-copy");
      copy.append(el("strong", "", platform.name), el("small", "", platform.label));
      var arrow = el("span", "hpi-social-arrow", platform.paused ? "◦" : "↗");
      arrow.setAttribute("aria-hidden", "true");
      a.append(mark, copy, arrow);
      grid.appendChild(a);
    });
    var bottom = el("div", "hpi-social-bottom");
    bottom.append(
      el("span", "", "RuTube — видеоархив · ссылка на канал уточняется"),
      el("span", "", "Никаких фанфар. Только хроники.")
    );
    wrap.append(heading, grid, bottom);
    footer.appendChild(wrap);
  }

  document.querySelectorAll("footer.footer").forEach(mount);
})();
